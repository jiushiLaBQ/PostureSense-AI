"""推理调度服务：串联相机 → 姿态估计 → 可视化 → 性能计量。

供 GUI 与测试代码共用同一入口，保证界面显示的数据与测试断言的数据同源。

线程契约（对照仓库根 README.md §4.1，推理在 QThread 执行）:
- process_once() 应在采集/推理线程调用，不要在 GUI 主线程调用。
- 输出的 ProcessResult 为不可变快照，可安全跨线程传递。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

from ..vision.camera_manager import CameraManager, CameraError, CameraFrame
from ..vision.pose_estimator import PoseEstimator, PoseResult, PoseState
from ..vision.feature_extractor import PostureFeatures, extract_features
from ..vision.visualizer import draw_pose
from ..core.profiler import PerformanceMonitor, PerformanceStats

logger = logging.getLogger(__name__)


@dataclass
class ProcessResult:
    """单帧处理结果快照。可跨线程传递。"""

    frame: Optional[CameraFrame]
    pose: Optional[PoseResult]
    features: Optional[PostureFeatures]
    perf: PerformanceStats
    annotated_bgr: Optional[object]  # numpy.ndarray | None
    error: str = ""
    has_camera: bool = True


class InferenceService:
    """统一推理调度。GUI 与测试都通过它取数据。"""

    def __init__(
        self,
        camera: CameraManager,
        estimator: PoseEstimator,
        draw_skeleton: bool = True,
    ) -> None:
        self.camera = camera
        self.estimator = estimator
        self.draw_skeleton = draw_skeleton
        self.perf = PerformanceMonitor(window_size=30)
        self._running = False

    def start(self) -> None:
        if not self.camera.open():
            raise CameraError(f"无法打开摄像头 device_index={self.camera.device_index}")
        self._running = True
        logger.info("推理服务已启动")

    def stop(self) -> None:
        """停止采集并释放相机。幂等。

        注意: 不在这里关闭 estimator —— 用户可再次开始监测，
        模型应保留在内存中复用。estimator 的关闭由窗口 closeEvent 负责。
        """
        self._running = False
        self.camera.release()
        logger.info("推理服务已停止，相机已释放")

    def close(self) -> None:
        """彻底释放所有资源（含模型）。用于应用退出。"""
        self.stop()
        self.estimator.close()
        logger.info("推理服务资源已全部释放")

    @property
    def is_running(self) -> bool:
        return self._running

    def process_once(self) -> ProcessResult:
        """处理一帧。相机失败时不伪造图像。"""
        self.perf.begin_frame()
        ok, frame = self.camera.read_frame()
        if not ok or frame is None:
            perf = self.perf.end_frame()
            return ProcessResult(
                frame=None,
                pose=None,
                features=None,
                perf=perf,
                annotated_bgr=None,
                error="camera read failed",
                has_camera=False,
            )

        pose = self.estimator.estimate(frame.image, frame.timestamp)
        features = extract_features(pose) if pose is not None else None
        annotated = draw_pose(frame.image, pose) if self.draw_skeleton else frame.image
        perf = self.perf.end_frame()

        return ProcessResult(
            frame=frame,
            pose=pose,
            features=features,
            perf=perf,
            annotated_bgr=annotated,
            error="" if pose.state is not PoseState.ERROR else pose.error_message,
            has_camera=True,
        )
