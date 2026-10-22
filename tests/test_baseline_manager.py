"""baseline_manager 测试：统计正确性、样本不足、缺失、低方差、偏差计算。

注：本文件曾在编辑事故中丢失，依据 __pycache__ 字节码语义逐条重建
（断言对象与数值与原版一致）。
"""

from __future__ import annotations

import math

import pytest

from posturesense.core.baseline_manager import (
    EPSILON,
    LOW_VARIANCE_SIGMA,
    BaselineError,
    CalibrationCollector,
    compute_deviation,
    profile_from_row,
)
from posturesense.vision.feature_extractor import PostureFeatures


def _feat(
    head_fwd=0.1,
    trunk=5.0,
    shoulder=3.0,
    head_lat=0.02,
    valid=1.0,
    ts=1.0,
):
    return PostureFeatures(
        head_forward_ratio=head_fwd,
        trunk_tilt_deg=trunk,
        shoulder_tilt_deg=shoulder,
        head_lateral_offset=head_lat,
        keypoint_valid_ratio=valid,
        timestamp=ts,
    )


def _collect(n=50, **kwargs) -> CalibrationCollector:
    c = CalibrationCollector(min_samples=30)
    for i in range(n):
        c.add(_feat(ts=float(i), **kwargs))
    return c


# ---------------------------------------------------------------------------
# 采样与统计
# ---------------------------------------------------------------------------
def test_insufficient_samples_rejects():
    """样本不足 → 抛 BaselineError，不产出半成品。"""
    c = CalibrationCollector(min_samples=30)
    for i in range(10):
        c.add(_feat(ts=float(i)))
    assert c.is_sufficient is False
    with pytest.raises(BaselineError):
        c.compute()


def test_all_none_frames_rejects():
    """全部 None 帧无效 → 拒绝产出。"""
    c = CalibrationCollector(min_samples=10)
    for _ in range(20):
        c.add(None)
    assert c.total_frames == 20
    assert c.valid_frames == 0
    with pytest.raises(BaselineError):
        c.compute()


def test_none_frames_do_not_pollute_stats():
    """None 帧不进统计（缺失 ≠ 数值 0）。"""
    c = CalibrationCollector(min_samples=10)
    for _ in range(10):
        c.add(_feat(trunk=None))
    for _ in range(5):
        c.add(_feat())
    p = c.compute()
    s = p.stats["trunk_tilt_deg"]
    assert s.count == 5
    assert s.mean == pytest.approx(5.0)


def test_per_feature_missing_counts():
    """某特征全部缺失 → 完全不出现在 stats 中，不冒充 0。"""
    c = CalibrationCollector(min_samples=10)
    for _ in range(15):
        c.add(_feat(trunk=None))
    p = c.compute()
    assert "trunk_tilt_deg" not in p.stats
    assert "head_forward_ratio" in p.stats
    assert p.feature_names() == [
        "head_forward_ratio", "shoulder_tilt_deg", "head_lateral_offset",
    ]


def test_stats_median_mean_std():
    """统计量计算正确（偶数个取中间两位均值）。"""
    c = CalibrationCollector(min_samples=4)
    for v in (1.0, 2.0, 3.0, 4.0):
        c.add(_feat(trunk=v))
    p = c.compute()
    s = p.stats["trunk_tilt_deg"]
    assert s.count == 4
    assert s.mean == pytest.approx(2.5)
    assert s.median == pytest.approx(2.5)
    assert s.std == pytest.approx(math.sqrt(1.25))
    assert s.min_value == 1.0
    assert s.max_value == 4.0
    assert p.created_at > 0


def test_stats_odd_median():
    """奇数个取正中位数。"""
    c = CalibrationCollector(min_samples=3)
    for v in (1.0, 5.0, 9.0):
        c.add(_feat(trunk=v))
    s = c.compute().stats["trunk_tilt_deg"]
    assert s.median == pytest.approx(5.0)


def test_baseline_profile_fields():
    """compute 传入的 name / profile_id 落到基线字段。"""
    p = _collect(40, trunk=7.0).compute(name="我的基线", profile_id="bp-test")
    assert p.name == "我的基线"
    assert p.profile_id == "bp-test"
    assert p.sample_count == 40
    assert p.version == 1
    assert p.created_at > 0


# ---------------------------------------------------------------------------
# 偏差计算
# ---------------------------------------------------------------------------
def test_deviation_zero_at_mean():
    """当前值等于基线均值 → z≈0。"""
    c = _collect(50, trunk=5.0)
    p = c.compute()
    d = compute_deviation(_feat(trunk=5.0), p)
    assert d.z["trunk_tilt_deg"] == pytest.approx(0.0, abs=0.1)
    assert d.is_reliable


def test_deviation_sign_and_scale():
    """偏离均值 → z>0；偏离越远 |z| 越大。"""
    c = CalibrationCollector(min_samples=30)
    for i in range(30):
        c.add(_feat(trunk=5.0 + (i % 5) * 0.1, ts=float(i)))
    p = c.compute()
    z_hi = compute_deviation(_feat(trunk=20.0), p).z["trunk_tilt_deg"]
    assert z_hi > 0
    z_lo = compute_deviation(_feat(trunk=0.0), p).z["trunk_tilt_deg"]
    assert z_lo < 0


def test_deviation_none_feature_is_none():
    """当前帧特征缺失 → z 为 None（而不是 0）。"""
    p = _collect(40).compute()
    d = compute_deviation(_feat(trunk=None), p)
    assert d.z["trunk_tilt_deg"] is None
    assert "trunk_tilt_deg" not in d.used_features


def test_deviation_no_baseline_feature_is_none():
    """基线没有该特征统计 → z 为 None。"""
    p = _collect(40, trunk=None).compute()
    d = compute_deviation(_feat(trunk=3.0), p)
    assert d.z["trunk_tilt_deg"] is None


def test_deviation_none_features_returns_empty():
    """当前帧全缺 → 无偏离，不伪装成 0。"""
    p = _collect(40).compute()
    d = compute_deviation(None, p)
    assert d.composite is None
    assert d.is_reliable is False
    assert d.used_features == []


def test_low_variance_feature_does_not_explode():
    """低方差特征 z 值不会爆炸（改用绝对偏差归一化）。"""
    c = CalibrationCollector(min_samples=30)
    for _ in range(30):
        c.add(_feat(trunk=5.0))
    p = c.compute()
    assert p.stats["trunk_tilt_deg"].std == pytest.approx(0.0)
    d = compute_deviation(_feat(trunk=5.05), p)
    z = d.z["trunk_tilt_deg"]
    assert z is not None
    assert abs(z) < 10.0
    assert math.isfinite(z)


def test_composite_is_mean_abs_z():
    """综合偏离 = 可用特征 |z| 的平均。"""
    p = _collect(40, trunk=5.0, shoulder=3.0).compute()
    d = compute_deviation(_feat(trunk=5.0, shoulder=3.0), p)
    assert d.composite == pytest.approx(0.0, abs=0.2)
    assert "trunk_tilt_deg" in d.used_features
    assert "shoulder_tilt_deg" in d.used_features
    assert len(d.used_features) == 4


def test_epsilon_protects_division():
    """ε 使用 >0，保证 σ=0 时 z 有限。"""
    assert EPSILON > 0
    assert LOW_VARIANCE_SIGMA > 0


# ---------------------------------------------------------------------------
# 反序列化（profile_from_row）
# ---------------------------------------------------------------------------
def _row_from(p):
    """模拟校准页 _on_finish 的序列化路径。"""
    import json

    stats_json = json.dumps(
        {
            k: {
                "count": v.count, "mean": v.mean, "median": v.median,
                "std": v.std, "min": v.min_value, "max": v.max_value,
            }
            for k, v in p.stats.items()
        },
        ensure_ascii=False,
    )
    return {
        "profile_id": p.profile_id,
        "name": p.name,
        "created_at": int(p.created_at * 1000),
        "sample_count": p.sample_count,
        "stats_json": stats_json,
        "version": 1,
    }


def test_profile_from_row_roundtrip():
    """序列化 → 反序列化 roundtrip，统计量一致。"""
    p = _collect(40, trunk=7.0).compute(name="往返", profile_id="bp-rt")
    row = _row_from(p)
    q = profile_from_row(row)
    assert q.profile_id == "bp-rt"
    assert q.name == "往返"
    assert q.sample_count == 40
    for key in p.stats:
        assert q.stats[key].mean == pytest.approx(p.stats[key].mean)
        assert q.stats[key].std == pytest.approx(p.stats[key].std)
        assert q.stats[key].count == p.stats[key].count
    # 反序列化后偏差计算结果与原基线一致
    d0 = compute_deviation(_feat(trunk=9.0), p)
    d1 = compute_deviation(_feat(trunk=9.0), q)
    assert d1.composite == pytest.approx(d0.composite, abs=1e-9)


def test_profile_from_row_bad_json_raises():
    """stats_json 损坏 → BaselineError，不产出半成品基线。"""
    with pytest.raises(BaselineError):
        profile_from_row({"profile_id": "x", "name": "x", "created_at": 0,
                          "sample_count": 30, "stats_json": "{broken"})


def test_profile_from_row_missing_key_raises():
    """缺 stats_json 字段 → BaselineError。"""
    with pytest.raises(BaselineError):
        profile_from_row({"profile_id": "x", "name": "x"})


def test_profile_from_row_default_version():
    """version 缺省按 1 处理。"""
    p = _collect(35).compute()
    row = _row_from(p)
    row.pop("version")
    q = profile_from_row(row)
    assert q.version == 1
