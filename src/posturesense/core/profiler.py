"""真实性能计量：FPS 与单帧推理延迟。

设计要点:
- 全部基于 time.perf_counter() 实测，不使用任何占位/估算数值。
- FPS 用滑动窗口（最近 N 帧）计算，避免瞬时抖动。
- 延迟记录最近一帧的处理耗时 + 窗口平均 + p95。
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field


@dataclass
class PerformanceStats:
    """一帧的性能快照。全部为真实测量值。"""

    fps: float = 0.0  # 滑动窗口平均 FPS
    frame_latency_ms: float = 0.0  # 最近一帧推理耗时（毫秒）
    avg_latency_ms: float = 0.0  # 窗口平均耗时
    p95_latency_ms: float = 0.0  # 窗口 p95 耗时
    frames_processed: int = 0


@dataclass
class PerformanceMonitor:
    """线程内的性能计量器。非线程安全，单个采集/推理线程独占使用。"""

    window_size: int = 30
    _latencies_ms: deque[float] = field(default_factory=deque, repr=False)
    _timestamps: deque[float] = field(default_factory=deque, repr=False)
    _frames: int = field(default=0, repr=False)
    _mark_start: float | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self._latencies_ms = deque(maxlen=self.window_size)
        self._timestamps = deque(maxlen=self.window_size)

    def begin_frame(self) -> None:
        """标记单帧处理开始。"""
        self._mark_start = time.perf_counter()

    def end_frame(self) -> PerformanceStats:
        """标记单帧处理结束，返回当前性能快照。"""
        now = time.perf_counter()
        latency_ms = (now - self._mark_start) * 1000.0 if self._mark_start else 0.0
        self._mark_start = None

        self._latencies_ms.append(latency_ms)
        self._timestamps.append(now)
        self._frames += 1

        return self.snapshot(last_latency_ms=latency_ms)

    def snapshot(self, last_latency_ms: float | None = None) -> PerformanceStats:
        """返回当前快照，不改变内部状态。"""
        if self._timestamps:
            span = self._timestamps[-1] - self._timestamps[0]
            fps = (len(self._timestamps) - 1) / span if span > 1e-9 else 0.0
        else:
            fps = 0.0

        if self._latencies_ms:
            ordered = sorted(self._latencies_ms)
            avg = sum(ordered) / len(ordered)
            p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
            # 最近一帧延迟 = 插入序的最后一个，不是窗口最大值
            last = last_latency_ms if last_latency_ms is not None else self._latencies_ms[-1]
        else:
            avg = p95 = last = 0.0

        return PerformanceStats(
            fps=fps,
            frame_latency_ms=last,
            avg_latency_ms=avg,
            p95_latency_ms=p95,
            frames_processed=self._frames,
        )
