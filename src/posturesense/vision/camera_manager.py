"""摄像头发现、连接、读取与释放。

设计要点（对照仓库根 README.md §4.1 总体链路）:
- 单一 API。只保留这一套相机接口，无重复路径。
- 失败显式抛错 / 返回 False，绝不静默补零帧 —— 静默零帧会让上层误以为"检测到空场景"。
- buffer_size=1 降低延迟；支持自动重连；release() 幂等。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

import cv2

logger = logging.getLogger(__name__)

# OpenCV 后端常量映射。DSHOW 在 Windows 上延迟最低，作为默认。
_BACKENDS = {
    "DSHOW": getattr(cv2, "CAP_DSHOW", 0),
    "MSMF": getattr(cv2, "CAP_MSMF", 1),
    "ANY": getattr(cv2, "CAP_ANY", 0),
}


class CameraError(RuntimeError):
    """摄像头打开/读取失败。"""


@dataclass
class CameraFrame:
    """一帧图像及其元数据。"""

    image: "cv2.Mat"  # BGR, shape=(h, w, 3)
    timestamp: float  # time.time()
    width: int
    height: int
    index: int  # 帧序号，自 open() 起单调递增


class CameraManager:
    """摄像头生命周期管理。

    典型用法::

        cam = CameraManager(device_index=0)
        cam.open()
        ok, frame = cam.read_frame()
        cam.release()

    线程约束: 单实例只应在采集线程使用，不要跨线程并发调 read_frame()。
    """

    def __init__(
        self,
        device_index: int = 0,
        width: int = 1280,
        height: int = 720,
        fps: int = 30,
        backend: str = "DSHOW",
        flip_horizontal: bool = True,
        auto_reconnect: bool = True,
        reconnect_interval_sec: float = 2.0,
    ) -> None:
        self.device_index = device_index
        self.width = width
        self.height = height
        self.fps = fps
        self.backend = backend.upper()
        self.flip_horizontal = flip_horizontal
        self.auto_reconnect = auto_reconnect
        self.reconnect_interval_sec = reconnect_interval_sec

        self._cap: Optional[cv2.VideoCapture] = None
        self._frame_index = 0
        self._last_reconnect_attempt = 0.0

    # ------------------------------------------------------------------
    # 状态
    # ------------------------------------------------------------------
    @property
    def is_open(self) -> bool:
        return self._cap is not None and self._cap.isOpened()

    @property
    def frame_index(self) -> int:
        return self._frame_index

    # ------------------------------------------------------------------
    # 打开 / 关闭
    # ------------------------------------------------------------------
    def open(self) -> bool:
        """打开摄像头。成功返回 True，失败返回 False 并保持未打开状态。"""
        if self.is_open:
            return True

        # 清理可能残留的失效 capture，避免句柄泄漏
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:  # noqa: BLE001
                pass
            self._cap = None

        backend_id = _BACKENDS.get(self.backend, cv2.CAP_ANY)
        cap = cv2.VideoCapture(self.device_index, backend_id)
        if not cap.isOpened():
            cap.release()
            logger.error("摄像头 %s 打开失败 (backend=%s)", self.device_index, self.backend)
            return False

        try:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            cap.set(cv2.CAP_PROP_FPS, self.fps)
            # buffer_size=1：只保留最新帧，降低端到端延迟
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

            # 读取实际生效的分辨率（驱动可能拒绝请求值）
            w = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
            h = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
            width = int(w) if w == w and w > 0 else self.width  # w==w 过滤 NaN
            height = int(h) if h == h and h > 0 else self.height
        except Exception:  # noqa: BLE001 - 配置失败必须释放句柄
            logger.exception("配置摄像头参数失败")
            cap.release()
            return False

        self._cap = cap
        self._frame_index = 0
        self.width = width
        self.height = height
        logger.info("摄像头已打开 %sx%s @ device=%s", self.width, self.height, self.device_index)
        return True

    def release(self) -> None:
        """释放摄像头资源。幂等，可重复调用。"""
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:  # noqa: BLE001 - 释放失败不应抛出
                logger.exception("释放摄像头时出现异常")
            finally:
                self._cap = None
                logger.info("摄像头已释放")

    def __enter__(self) -> "CameraManager":
        if not self.open():
            raise CameraError(f"无法打开摄像头 device_index={self.device_index}")
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()

    # ------------------------------------------------------------------
    # 读帧
    # ------------------------------------------------------------------
    def read_frame(self) -> tuple[bool, Optional[CameraFrame]]:
        """读取一帧。

        返回 (True, CameraFrame) 或 (False, None)。
        失败时**不会**返回伪造的黑帧 —— 调用方必须处理 (False, None)。
        相机断开后 auto_reconnect 会在后续调用中持续尝试重连（受节流约束）。
        """
        ok, image = self._read_raw()

        if (not ok or image is None) and self.auto_reconnect:
            # _cap 为 None 或读失败都走重连路径，避免断开后永久死锁
            if self._try_reconnect():
                ok, image = self._read_raw()

        if not ok or image is None:
            return False, None

        if self.flip_horizontal:
            image = cv2.flip(image, 1)

        h, w = image.shape[:2]
        frame = CameraFrame(
            image=image,
            # 单调时钟：MediaPipe detect_for_video 要求时间戳严格递增
            timestamp=time.perf_counter(),
            width=w,
            height=h,
            index=self._frame_index,
        )
        self._frame_index += 1
        return True, frame

    def _read_raw(self) -> tuple[bool, Optional[object]]:
        """底层读帧，不做重连。"""
        if self._cap is None:
            return False, None
        ok, image = self._cap.read()
        return (ok, image) if ok and image is not None else (False, None)

    # ------------------------------------------------------------------
    # 重连
    # ------------------------------------------------------------------
    def _try_reconnect(self) -> bool:
        now = time.time()
        if now - self._last_reconnect_attempt < self.reconnect_interval_sec:
            return False
        self._last_reconnect_attempt = now

        logger.warning("读帧失败，尝试重连摄像头 device=%s", self.device_index)
        self.release()
        return self.open()

    # ------------------------------------------------------------------
    # 设备发现
    # ------------------------------------------------------------------
    @staticmethod
    def list_available_cameras(max_index: int = 5) -> list[int]:
        """探测可用摄像头索引。

        会真实打开再关闭每个候选设备，可能需要几秒。
        """
        found: list[int] = []
        for i in range(max_index):
            cap = cv2.VideoCapture(i, _BACKENDS.get("DSHOW", cv2.CAP_ANY))
            try:
                if cap.isOpened():
                    found.append(i)
            finally:
                cap.release()
        return found
