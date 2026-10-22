"""个人姿态基线：校准采样、统计量、标准化偏差。

设计要点（见仓库根 README.md §4.4 个人基线）:
- 仅在用户主动触发时采样，不持续采集身份信息。
- 只统计特征值本身（角度/比值），不保存原始图像、不保存人脸。
- 样本质量过滤：特征为 None 的帧直接丢弃，不参与统计。
- 样本不足 → 拒绝保存，不产生半成品基线。
- 偏差 z_i = (x_i - μ_i) / (σ_i + ε)；低方差特征改用绝对偏差混合。

红线: 基线未建立时不得伪装成个性化模式。
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Optional

from ..vision.feature_extractor import PostureFeatures

logger = logging.getLogger(__name__)

# 稳定项，防止 σ=0 时除零
EPSILON = 1e-3
# 低于该标准差视为"低方差特征"，z 值会爆炸，改用绝对偏差归一化
LOW_VARIANCE_SIGMA = 0.02
# 校准最少有效样本数
DEFAULT_MIN_SAMPLES = 30


class BaselineError(ValueError):
    """基线校准失败（样本不足等）。"""


@dataclass
class FeatureStats:
    """单个特征的统计量。count=0 表示该特征在校准全程都不可用。"""

    count: int = 0
    mean: float = 0.0
    median: float = 0.0
    std: float = 0.0
    min_value: float = 0.0
    max_value: float = 0.0

    @property
    def is_available(self) -> bool:
        return self.count > 0


@dataclass
class BaselineProfile:
    """一份个人基线。

    不含任何身份信息；profile_id 为本地随机标识。
    """

    profile_id: str
    name: str
    created_at: float
    sample_count: int
    # 特征名 → 统计量；某特征全程缺失则不存在该键
    stats: dict[str, FeatureStats] = field(default_factory=dict)
    version: int = 1

    def feature_names(self) -> list[str]:
        return [k for k, v in self.stats.items() if v.is_available]


FEATURE_KEYS = (
    "head_forward_ratio",
    "trunk_tilt_deg",
    "shoulder_tilt_deg",
    "head_lateral_offset",
)


@dataclass
class CalibrationCollector:
    """校准采样器：喂入特征帧，出统计基线。"""

    min_samples: int = DEFAULT_MIN_SAMPLES
    _samples: dict[str, list[float]] = field(default_factory=dict, repr=False)
    _total_frames: int = 0
    _valid_frames: int = 0

    def add(self, features: Optional[PostureFeatures]) -> None:
        """加入一帧特征。None 或不可用特征不入统计。"""
        self._total_frames += 1
        if features is None:
            return

        got_any = False
        for key in FEATURE_KEYS:
            value = getattr(features, key)
            if value is not None and math.isfinite(value):
                self._samples.setdefault(key, []).append(float(value))
                got_any = True
        if got_any:
            self._valid_frames += 1

    @property
    def total_frames(self) -> int:
        return self._total_frames

    @property
    def valid_frames(self) -> int:
        return self._valid_frames

    @property
    def is_sufficient(self) -> bool:
        return self._valid_frames >= self.min_samples

    def compute(self, name: str = "校准基线", profile_id: str = "") -> BaselineProfile:
        """计算并返回基线。样本不足抛 BaselineError，不产出半成品。"""
        if not self.is_sufficient:
            raise BaselineError(
                f"有效样本不足：{self._valid_frames}/{self.min_samples}，请继续校准"
            )

        stats: dict[str, FeatureStats] = {}
        for key, values in self._samples.items():
            if not values:
                continue
            stats[key] = _calc_stats(values)

        # 至少要有一个可用特征
        if not any(s.is_available for s in stats.values()):
            raise BaselineError("没有可用的姿态特征，无法建立基线")

        logger.info(
            "基线已计算: profile=%s 样本=%d 特征=%s",
            name, self._valid_frames, list(stats.keys()),
        )
        return BaselineProfile(
            profile_id=profile_id or f"bp-{int(time.time())}",
            name=name,
            created_at=time.time(),
            sample_count=self._valid_frames,
            stats=stats,
        )


def profile_from_row(row: dict) -> BaselineProfile:
    """从数据库行（calibration_profiles）反序列化为 BaselineProfile。

    stats_json 由校准页 _on_finish 的 json.dumps 产出，结构一一对应；
    解析失败抛 BaselineError，不产出半成品基线。
    """
    import json

    try:
        raw = json.loads(row["stats_json"])
    except (KeyError, TypeError, ValueError) as exc:
        raise BaselineError(f"基线数据损坏，无法加载: {exc}") from exc

    stats: dict[str, FeatureStats] = {}
    for key, d in raw.items():
        stats[key] = FeatureStats(
            count=int(d["count"]),
            mean=float(d["mean"]),
            median=float(d["median"]),
            std=float(d["std"]),
            min_value=float(d["min"]),
            max_value=float(d["max"]),
        )
    return BaselineProfile(
        profile_id=str(row["profile_id"]),
        name=str(row["name"]),
        created_at=float(row["created_at"]) / 1000.0,
        sample_count=int(row["sample_count"]),
        stats=stats,
        version=int(row.get("version", 1)),
    )


def _calc_stats(values: list[float]) -> FeatureStats:
    n = len(values)
    ordered = sorted(values)
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / n
    std = math.sqrt(var)
    median = (
        ordered[n // 2]
        if n % 2 == 1
        else (ordered[n // 2 - 1] + ordered[n // 2]) / 2.0
    )
    return FeatureStats(
        count=n,
        mean=mean,
        median=median,
        std=std,
        min_value=ordered[0],
        max_value=ordered[-1],
    )


# ---------------------------------------------------------------------------
# 偏差计算
# ---------------------------------------------------------------------------
@dataclass
class DeviationResult:
    """单帧相对基线的偏差。None 表示该特征无法判断。"""

    z: dict[str, Optional[float]] = field(default_factory=dict)
    # 综合偏离指标：可用特征 |z| 的加权平均
    composite: Optional[float] = None
    used_features: list[str] = field(default_factory=list)

    @property
    def is_reliable(self) -> bool:
        return self.composite is not None and bool(self.used_features)


def compute_deviation(
    features: Optional[PostureFeatures],
    baseline: BaselineProfile,
) -> DeviationResult:
    """计算当前特征相对个人基线的标准化偏差。

    z_i = (x_i - μ_i) / (σ_i + ε)
    低方差特征（σ < LOW_VARIANCE_SIGMA）改用绝对偏差归一化，避免 z 爆炸。
    特征为 None 或基线无该特征统计 → z_i = None。
    """
    result = DeviationResult()
    if features is None:
        return result

    abs_zs: list[float] = []
    for key in FEATURE_KEYS:
        value = getattr(features, key)
        fs = baseline.stats.get(key)
        if value is None or fs is None or not fs.is_available:
            result.z[key] = None
            continue

        if fs.std < LOW_VARIANCE_SIGMA:
            # 低方差：z 分母趋近 ε 会爆炸，改用绝对偏差归一化
            abs_dev = abs(value - fs.mean)
            z = math.copysign(abs_dev / LOW_VARIANCE_SIGMA, value - fs.mean)
        else:
            z = (value - fs.mean) / (fs.std + EPSILON)

        result.z[key] = z
        result.used_features.append(key)
        abs_zs.append(abs(z))

    if abs_zs:
        result.composite = sum(abs_zs) / len(abs_zs)
    return result
