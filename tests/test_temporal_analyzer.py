"""TemporalAnalyzer 测试：状态机转移、滞回、误报抑制、恢复、暂停、无法判断。

守红线：短暂动作不触发事件；关键点不足 = UNKNOWN 不是异常。
"""

from __future__ import annotations

import pytest

from posturesense.core.temporal_analyzer import (
    AnalyzerConfig,
    PostureState,
    FrameSample,
    TemporalAnalyzer,
)


CFG = AnalyzerConfig(
    deviation_threshold=2.0,
    hysteresis_margin=0.3,  # 退出阈值 1.7
    sustain_sec=3.0,
    recover_sec=2.0,
    min_valid_ratio=0.5,
    window_size=3,
    min_dwell_sec=0.0,  # 测试关闭驻留，单独测驻留
)


def _run(an, frames):
    """喂入 [(ts, deviation, valid), ...]，返回快照列表。"""
    snaps = []
    for ts, dev, valid in frames:
        snaps.append(an.update(FrameSample(timestamp=ts, deviation=dev, valid_ratio=valid)))
    return snaps


# ---------------------------------------------------------------------------
# 基本转移
# ---------------------------------------------------------------------------
def test_init_to_normal():
    an = TemporalAnalyzer(CFG)
    assert an.state is PostureState.INIT
    snap = an.update(FrameSample(0.0, 0.5, 1.0))
    assert snap.state is PostureState.NORMAL


def test_short_spike_does_not_trigger_event():
    """短暂动作（< sustain_sec）不得触发持续异常事件。"""
    an = TemporalAnalyzer(CFG)
    _run(an, [(0.0, 0.5, 1.0)])
    # 1 秒高偏离，然后回落
    snaps = _run(an, [(0.5, 5.0, 1.0), (1.0, 5.0, 1.0)])
    assert any(s.state is PostureState.SUSPECT for s in snaps)
    # 多帧低值让滑窗排空高偏离样本
    snaps = _run(an, [(1.5, 0.2, 1.0), (2.0, 0.2, 1.0), (2.5, 0.2, 1.0), (3.0, 0.2, 1.0)])
    assert an.state is PostureState.NORMAL
    assert all(s.closed_event is None for s in snaps)
    assert all(s.should_remind is False for s in snaps)


def test_sustained_triggers_event():
    """持续偏离 ≥ sustain_sec 进入 SUSTAINED 并产生事件。"""
    an = TemporalAnalyzer(CFG)
    frames = [(float(i) * 0.5, 5.0, 1.0) for i in range(10)]  # 0..4.5s
    snaps = _run(an, frames)
    states = [s.state for s in snaps]
    assert PostureState.SUSTAINED in states
    assert an.state in (PostureState.SUSTAINED, PostureState.REMINDED)


def test_remind_emitted_once():
    """提醒只触发一次。"""
    an = TemporalAnalyzer(CFG)
    frames = [(float(i) * 0.5, 5.0, 1.0) for i in range(12)]
    snaps = _run(an, frames)
    assert sum(1 for s in snaps if s.should_remind) == 1


def test_hysteresis_band_holds_state():
    """滞回区间（退出阈值~进入阈值）内不反复切换。"""
    an = TemporalAnalyzer(CFG)
    _run(an, [(0.0, 5.0, 1.0), (1.0, 5.0, 1.0), (2.0, 5.0, 1.0), (3.0, 5.0, 1.0), (4.0, 5.0, 1.0)])
    assert an.state in (PostureState.SUSTAINED, PostureState.REMINDED)
    # 带内值 1.85（介于 1.7 与 2.0）
    snaps = _run(an, [(5.0, 1.85, 1.0), (6.0, 1.85, 1.0)])
    assert all(
        s.state in (PostureState.SUSTAINED, PostureState.REMINDED, PostureState.RECOVERING)
        for s in snaps
    ), f"滞回带内不应退回 NORMAL，实际 {[s.state for s in snaps]}"


def test_recovery_closes_event():
    """连续正常 ≥ recover_sec 解除异常并关闭事件。"""
    an = TemporalAnalyzer(CFG)
    _run(an, [(float(i) * 0.5, 5.0, 1.0) for i in range(10)])
    # 回落并保持足够久（窗口排空 + recover_sec）
    snaps = _run(
        an,
        [(10.0 + i, 0.1, 1.0) for i in range(6)],
    )
    closed = [s.closed_event for s in snaps if s.closed_event is not None]
    assert len(closed) == 1
    ev = closed[0]
    assert ev.duration_sec > 0
    assert ev.reminded is True
    assert an.state is PostureState.NORMAL


def test_event_max_deviation_recorded():
    an = TemporalAnalyzer(CFG)
    _run(an, [(float(i) * 0.5, 5.0, 1.0) for i in range(10)])
    _run(an, [(10.0, 9.0, 1.0)])  # 更大偏离
    snaps = _run(an, [(11.0 + i, 0.1, 1.0) for i in range(6)])
    closed = [s.closed_event for s in snaps if s.closed_event]
    assert closed and closed[0].max_deviation >= 5.0


# ---------------------------------------------------------------------------
# 红线：未知 ≠ 异常
# ---------------------------------------------------------------------------
def test_low_valid_ratio_is_unknown_not_abnormal():
    """关键点有效率不足 → UNKNOWN，不产生事件。"""
    an = TemporalAnalyzer(CFG)
    _run(an, [(0.0, 0.5, 1.0)])
    snaps = _run(an, [(1.0, 99.0, 0.1), (2.0, 99.0, 0.1)])  # 高偏离但质量差
    assert all(s.state is PostureState.UNKNOWN for s in snaps)
    assert all(s.closed_event is None for s in snaps)
    assert all(s.should_remind is False for s in snaps)


def test_unknown_breaks_streak():
    """UNKNOWN 打断异常持续计时（配置可调）。"""
    an = TemporalAnalyzer(CFG)
    _run(an, [(0.0, 5.0, 1.0), (1.0, 5.0, 1.0), (2.0, 5.0, 1.0)])  # 接近 sustain
    _run(an, [(2.5, 5.0, 0.1)])  # 质量掉线
    snaps = _run(an, [(3.0, 5.0, 1.0), (3.5, 5.0, 1.0), (4.0, 5.0, 1.0)])
    # 重新计时，3.5s 内不应 SUSTAINED
    assert all(s.state is not PostureState.SUSTAINED for s in snaps)


def test_none_deviation_is_unknown():
    """deviation=None（无法判断）→ UNKNOWN。"""
    an = TemporalAnalyzer(CFG)
    snap = an.update(FrameSample(0.0, None, 1.0))
    assert snap.state is PostureState.UNKNOWN


# ---------------------------------------------------------------------------
# 暂停
# ---------------------------------------------------------------------------
def test_pause_state():
    an = TemporalAnalyzer(CFG)
    snap = an.update(FrameSample(0.0, 5.0, 1.0, is_paused=True))
    assert snap.state is PostureState.PAUSED
    assert snap.should_remind is False


def test_pause_does_not_create_event():
    an = TemporalAnalyzer(CFG)
    snaps = _run(an, [(float(i), 5.0, 1.0) for i in range(5)])
    snaps += _run(an, [(10.0, 5.0, 1.0)])
    paused = an.update(FrameSample(20.0, 5.0, 1.0, is_paused=True))
    assert paused.state is PostureState.PAUSED
    assert paused.closed_event is None


# ---------------------------------------------------------------------------
# flush / 滞回退出阈值
# ---------------------------------------------------------------------------
def test_flush_closes_open_event():
    an = TemporalAnalyzer(CFG)
    _run(an, [(float(i) * 0.5, 5.0, 1.0) for i in range(10)])
    ev = an.flush(50.0)
    assert ev is not None
    assert ev.end_ts == 50.0
    assert an.flush(51.0) is None  # 无未完成事件


def test_recover_threshold_property():
    cfg = AnalyzerConfig(deviation_threshold=2.0, hysteresis_margin=0.3)
    assert cfg.recover_threshold == pytest.approx(1.7)


def test_window_size_limits_smoothing():
    """滑动窗口大小限制平滑样本数。"""
    an = TemporalAnalyzer(CFG)
    assert an.smoothed is None
    _run(an, [(0.0, 10.0, 1.0), (1.0, 0.0, 1.0), (2.0, 0.0, 1.0)])
    assert len(an._window) == 3
    # 新样本挤出最旧的
    _run(an, [(3.0, 0.0, 1.0)])
    assert len(an._window) == 3
    assert an.smoothed == pytest.approx(0.0)
