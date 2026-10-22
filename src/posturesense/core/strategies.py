"""算法实验室：三种姿态判定方案（A/B/C）的可对比实现。

红线:
- 三方案共用同一套特征输入，仅判定策略不同，保证公平。
- 每种方案定义清晰，可单独序列化参数。
- 不在这里伪造评估结果 —— 结果由 experiment runner 对真实标注计算。

方案
    A  FixedThresholdSingleFrame   固定阈值、单帧判断
    B  FixedThresholdSustained     固定阈值、连续时间判断
    C  PersonalBaselineSustained   个性化基线、连续时间判断
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from .baseline_manager import BaselineProfile, compute_deviation
from .temporal_analyzer import (
    AnalyzerConfig,
    FrameSample,
    PostureState,
    TemporalAnalyzer,
)
from ..vision.feature_extractor import PostureFeatures

logger = logging.getLogger(__name__)


@dataclass
class StrategyInput:
    """单帧输入。三方案共用。"""

    timestamp: float
    features: Optional[PostureFeatures]
    valid_ratio: float
    is_paused: bool = False


@dataclass
class StrategyOutput:
    """单帧判定输出。"""

    timestamp: float
    is_abnormal: bool  # 该帧/该时刻判为姿态偏离
    state: str  # 方案内部状态名
    deviation: Optional[float]  # 用于调试/记录的偏离量
    reason: str = ""


class BaseStrategy(ABC):
    """方案基类。"""

    name: str = "base"

    @abstractmethod
    def update(self, sample: StrategyInput) -> StrategyOutput:
        ...

    @abstractmethod
    def reset(self) -> None:
        ...

    @abstractmethod
    def params(self) -> dict:
        """可序列化的参数快照，用于实验记录。"""
        ...


# ---------------------------------------------------------------------------
# 方案 A：固定阈值、单帧判断
# ---------------------------------------------------------------------------
@dataclass
class FixedThresholdSingleFrame(BaseStrategy):
    """A：每帧独立判断，无时序平滑、无持续时间要求。

    误报率高，作为对照基线。
    """

    threshold: float = 2.0
    name: str = "A_fixed_single"

    def update(self, sample: StrategyInput) -> StrategyOutput:
        if sample.features is None or sample.valid_ratio <= 0:
            return StrategyOutput(
                sample.timestamp, False, "unknown", None, "无法判断"
            )
        # 单帧方案只用绝对几何阈值（不依赖基线）
        dev = _abs_geometry_deviation(sample.features)
        if dev is None:
            return StrategyOutput(
                sample.timestamp, False, "unknown", None, "无法判断"
            )
        abnormal = dev >= self.threshold
        return StrategyOutput(
            sample.timestamp, abnormal,
            "abnormal" if abnormal else "normal", dev,
            "单帧超阈值" if abnormal else "正常",
        )

    def reset(self) -> None:
        return

    def params(self) -> dict:
        return {"threshold": self.threshold}


# ---------------------------------------------------------------------------
# 方案 B：固定阈值、连续时间判断
# ---------------------------------------------------------------------------
@dataclass
class FixedThresholdSustained(BaseStrategy):
    """B：固定阈值 + 滑窗平滑 + 持续时间。无个人基线。"""

    threshold: float = 2.0
    sustain_sec: float = 3.0
    recover_sec: float = 2.0
    window_size: int = 30
    min_valid_ratio: float = 0.5
    name: str = "B_fixed_sustained"

    def __post_init__(self) -> None:
        cfg = AnalyzerConfig(
            deviation_threshold=self.threshold,
            sustain_sec=self.sustain_sec,
            recover_sec=self.recover_sec,
            window_size=self.window_size,
            min_valid_ratio=self.min_valid_ratio,
        )
        self._an = TemporalAnalyzer(cfg)

    def update(self, sample: StrategyInput) -> StrategyOutput:
        dev = _abs_geometry_deviation(sample.features) if sample.features else None
        snap = self._an.update(
            FrameSample(
                timestamp=sample.timestamp,
                deviation=dev,
                valid_ratio=sample.valid_ratio,
                is_paused=sample.is_paused,
            )
        )
        abnormal = snap.state in (
            PostureState.SUSTAINED, PostureState.REMINDED, PostureState.RECOVERING,
        )
        return StrategyOutput(
            sample.timestamp, abnormal, snap.state.value, snap.smoothed_deviation,
            snap.reason,
        )

    def reset(self) -> None:
        self._an.reset()

    def params(self) -> dict:
        return {
            "threshold": self.threshold,
            "sustain_sec": self.sustain_sec,
            "recover_sec": self.recover_sec,
            "window_size": self.window_size,
            "min_valid_ratio": self.min_valid_ratio,
        }


# ---------------------------------------------------------------------------
# 方案 C：个性化基线、连续时间判断
# ---------------------------------------------------------------------------
@dataclass
class PersonalBaselineSustained(BaseStrategy):
    """C：个人基线 z 偏差 + 滑窗 + 持续时间。

    baseline=None 时退化为方案 B（诚实降级，不伪装个性化）。
    """

    baseline: Optional[BaselineProfile] = None
    z_threshold: float = 2.0
    sustain_sec: float = 3.0
    recover_sec: float = 2.0
    window_size: int = 30
    min_valid_ratio: float = 0.5
    name: str = "C_baseline_sustained"

    def __post_init__(self) -> None:
        cfg = AnalyzerConfig(
            deviation_threshold=self.z_threshold,
            sustain_sec=self.sustain_sec,
            recover_sec=self.recover_sec,
            window_size=self.window_size,
            min_valid_ratio=self.min_valid_ratio,
        )
        self._an = TemporalAnalyzer(cfg)

    def update(self, sample: StrategyInput) -> StrategyOutput:
        if self.baseline is None:
            # 诚实降级：没有基线就不用 z，退回绝对几何
            dev = _abs_geometry_deviation(sample.features) if sample.features else None
            reason_prefix = "[无基线，降级] "
        else:
            d = compute_deviation(sample.features, self.baseline)
            dev = d.composite
            reason_prefix = ""

        snap = self._an.update(
            FrameSample(
                timestamp=sample.timestamp,
                deviation=dev,
                valid_ratio=sample.valid_ratio,
                is_paused=sample.is_paused,
            )
        )
        abnormal = snap.state in (
            PostureState.SUSTAINED, PostureState.REMINDED, PostureState.RECOVERING,
        )
        return StrategyOutput(
            sample.timestamp, abnormal, snap.state.value, snap.smoothed_deviation,
            reason_prefix + snap.reason,
        )

    def reset(self) -> None:
        self._an.reset()

    def params(self) -> dict:
        return {
            "has_baseline": self.baseline is not None,
            "baseline_id": self.baseline.profile_id if self.baseline else None,
            "z_threshold": self.z_threshold,
            "sustain_sec": self.sustain_sec,
            "recover_sec": self.recover_sec,
            "window_size": self.window_size,
            "min_valid_ratio": self.min_valid_ratio,
        }


# ---------------------------------------------------------------------------
def _abs_geometry_deviation(features: PostureFeatures) -> Optional[float]:
    """无基线时的绝对几何偏离量（0–10 量级，供固定阈值方案使用）。

    只在特征可用时计算；任一关键特征缺失返回 None（无法判断）。
    定义见 ALGORITHM_DESIGN.md §6；阈值须实测标定。
    """
    parts: list[float] = []
    if features.trunk_tilt_deg is not None:
        # 直立 0°，10° 起算偏离
        parts.append(max(0.0, features.trunk_tilt_deg - 10.0) / 5.0)
    if features.shoulder_tilt_deg is not None:
        parts.append(max(0.0, features.shoulder_tilt_deg - 5.0) / 5.0)
    if features.head_forward_ratio is not None:
        parts.append(min(10.0, abs(features.head_forward_ratio) * 4.0))

    if not parts:
        return None
    return sum(parts) / len(parts)


STRATEGY_REGISTRY = {
    "A": FixedThresholdSingleFrame,
    "B": FixedThresholdSustained,
    "C": PersonalBaselineSustained,
}
