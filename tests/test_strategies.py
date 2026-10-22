"""strategies 测试：A/B/C 三方案行为差异、无基线降级、无法判断。"""

from __future__ import annotations

import pytest

from posturesense.core.baseline_manager import CalibrationCollector
from posturesense.core.strategies import (
    FixedThresholdSingleFrame,
    FixedThresholdSustained,
    PersonalBaselineSustained,
    StrategyInput,
    STRATEGY_REGISTRY,
)
from posturesense.vision.feature_extractor import PostureFeatures


def _feat(trunk=2.0, shoulder=2.0, head_fwd=0.1, valid=1.0, ts=0.0):
    return PostureFeatures(
        head_forward_ratio=head_fwd,
        trunk_tilt_deg=trunk,
        shoulder_tilt_deg=shoulder,
        head_lateral_offset=0.0,
        keypoint_valid_ratio=valid,
        timestamp=ts,
    )


def _sample(ts, feats, valid=1.0):
    return StrategyInput(timestamp=ts, features=feats, valid_ratio=valid)


def _bad_feats(ts=0.0):
    """明显偏离的姿态特征。"""
    return _feat(trunk=45.0, shoulder=30.0, head_fwd=1.5, ts=ts)


# ---------------------------------------------------------------------------
# 方案 A：单帧
# ---------------------------------------------------------------------------
def test_A_flags_single_frame():
    a = FixedThresholdSingleFrame(threshold=2.0)
    out = a.update(_sample(0.0, _bad_feats()))
    assert out.is_abnormal is True
    assert out.state == "abnormal"


def test_A_normal_frame():
    a = FixedThresholdSingleFrame(threshold=2.0)
    out = a.update(_sample(0.0, _feat(trunk=1.0, shoulder=1.0, head_fwd=0.0)))
    assert out.is_abnormal is False


def test_A_unknown_on_none_features():
    a = FixedThresholdSingleFrame()
    out = a.update(_sample(0.0, None, valid=0.0))
    assert out.is_abnormal is False
    assert out.state == "unknown"


# ---------------------------------------------------------------------------
# 方案 B：持续判断
# ---------------------------------------------------------------------------
def test_B_short_spike_not_abnormal():
    """B: 短暂偏离不判异常（对比 A 会判异常）。"""
    b = FixedThresholdSustained(threshold=2.0, sustain_sec=3.0, window_size=1)
    # 1 帧异常后立即正常
    r1 = b.update(_sample(0.0, _bad_feats()))
    r2 = b.update(_sample(0.1, _feat(trunk=1.0, shoulder=1.0, head_fwd=0.0)))
    assert r1.is_abnormal is False  # 未达持续时间
    assert r2.is_abnormal is False


def test_B_sustained_becomes_abnormal():
    b = FixedThresholdSustained(threshold=2.0, sustain_sec=1.0, window_size=1)
    outs = []
    for i in range(20):
        outs.append(b.update(_sample(i * 0.2, _bad_feats())))
    assert any(o.is_abnormal for o in outs)


def test_B_and_A_differ_on_same_input():
    """同一输入下 A 与 B 行为不同（对比有效性）。"""
    a = FixedThresholdSingleFrame(threshold=2.0)
    b = FixedThresholdSustained(threshold=2.0, sustain_sec=3.0, window_size=1)
    feats = _bad_feats()
    assert a.update(_sample(0.0, feats)).is_abnormal is True
    assert b.update(_sample(0.0, feats)).is_abnormal is False


# ---------------------------------------------------------------------------
# 方案 C：个性化基线
# ---------------------------------------------------------------------------
def test_C_without_baseline_degrades_honestly():
    """无基线时 C 诚实降级，reason 标注降级。"""
    c = PersonalBaselineSustained(baseline=None, z_threshold=2.0, sustain_sec=1.0, window_size=1)
    out = c.update(_sample(0.0, _bad_feats()))
    assert "降级" in out.reason


def test_C_with_baseline_uses_z():
    """有基线时偏离用 z 值。"""
    coll = CalibrationCollector(min_samples=5)
    for i in range(10):
        coll.add(_feat(trunk=2.0, shoulder=2.0, head_fwd=0.1, ts=float(i)))
    baseline = coll.compute()

    c = PersonalBaselineSustained(
        baseline=baseline, z_threshold=2.0, sustain_sec=1.0, window_size=1
    )
    # 与基线一致 → 不异常
    out = c.update(_sample(0.0, _feat(trunk=2.0)))
    assert out.is_abnormal is False
    # 大幅偏离 → z 大
    out2 = c.update(_sample(1.0, _feat(trunk=20.0)))
    assert out2.deviation is not None


def test_C_params_recorded():
    c = PersonalBaselineSustained(baseline=None, z_threshold=1.5)
    p = c.params()
    assert p["has_baseline"] is False
    assert p["z_threshold"] == 1.5


# ---------------------------------------------------------------------------
# 注册表 / 参数
# ---------------------------------------------------------------------------
def test_registry_has_three_schemes():
    assert set(STRATEGY_REGISTRY) == {"A", "B", "C"}


def test_params_serializable():
    for cls in (FixedThresholdSingleFrame, FixedThresholdSustained, PersonalBaselineSustained):
        p = cls().params()
        assert isinstance(p, dict)


def test_none_features_never_abnormal():
    """无法判断的帧绝不判为异常（红线）。"""
    for strat in (
        FixedThresholdSingleFrame(),
        FixedThresholdSustained(),
        PersonalBaselineSustained(),
    ):
        out = strat.update(_sample(0.0, None, valid=0.1))
        assert out.is_abnormal is False
