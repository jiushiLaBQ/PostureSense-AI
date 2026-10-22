"""PerformanceMonitor 测试：真实时间计量，无占位值。"""

from __future__ import annotations

import time

from posturesense.core.profiler import PerformanceMonitor


def test_no_frames_reports_zero():
    """未处理任何帧时 FPS/延迟为 0，不返回虚构值。"""
    mon = PerformanceMonitor(window_size=5)
    stats = mon.snapshot()
    assert stats.fps == 0.0
    assert stats.frame_latency_ms == 0.0
    assert stats.frames_processed == 0


def test_latency_is_real_measured():
    """延迟应接近真实 sleep 时间，而不是固定值。"""
    mon = PerformanceMonitor(window_size=10)
    mon.begin_frame()
    time.sleep(0.05)  # 50ms
    stats = mon.end_frame()

    assert stats.frame_latency_ms >= 40.0  # 允许计时误差
    assert stats.frame_latency_ms < 200.0
    assert stats.frames_processed == 1


def test_fps_reflects_real_pacing():
    """FPS 应由真实帧间隔计算，且落在真实节奏的量级内。"""
    mon = PerformanceMonitor(window_size=10)
    for _ in range(5):
        mon.begin_frame()
        time.sleep(0.02)  # 20ms/帧 → 理论 ~50 FPS
        mon.end_frame()

    stats = mon.snapshot()
    assert stats.frames_processed == 5
    # 允许调度抖动，但必须落在合理量级（防止单位错误/假常数）
    assert 20.0 <= stats.fps <= 90.0


def test_frame_latency_is_latest_not_max():
    """frame_latency_ms 必须是最近一帧，不是窗口最大值。"""
    mon = PerformanceMonitor(window_size=10)

    mon.begin_frame()
    time.sleep(0.010)  # 10ms
    mon.end_frame()
    mon.begin_frame()
    time.sleep(0.030)  # 30ms（窗口最大）
    mon.end_frame()
    mon.begin_frame()
    time.sleep(0.002)  # 2ms（最近）
    s = mon.end_frame()

    # end_frame 传入的是最近一帧
    assert s.frame_latency_ms < 15.0
    # snapshot() 不带参数时也必须返回最近一帧，而非最大
    s2 = mon.snapshot()
    assert s2.frame_latency_ms == s.frame_latency_ms


def test_window_size_bounds_memory():
    """窗口大小限制 deque 长度。"""
    mon = PerformanceMonitor(window_size=3)
    for _ in range(10):
        mon.begin_frame()
        mon.end_frame()
    assert len(mon._latencies_ms) == 3
    assert mon.snapshot().frames_processed == 10
