"""人体姿态关键点提取（MediaPipe PoseLandmarker, 33 点）。

设计要点（对照仓库根 README.md §4.1–4.3）:
- 透传 MediaPipe 的 visibility / presence，**不硬编码置信度**。
  硬编码置信度（如固定 0.88）属于假数据，本产品禁止。
- 初始化失败显式抛 PoseModelError，不静默降级为 stub。
- 无人体入镜返回空关键点列表 —— 这是"未检测到人体"，不是"姿态异常"。
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)

# MediaPipe Pose 33 个关键点的语义名称（顺序即索引）。
POSE_LANDMARK_NAMES: tuple[str, ...] = (
    "nose", "left_eye_inner", "left_eye", "left_eye_outer",
    "right_eye_inner", "right_eye", "right_eye_outer",
    "left_ear", "right_ear", "mouth_left", "mouth_right",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_pinky", "right_pinky",
    "left_index", "right_index", "left_thumb", "right_thumb",
    "left_hip", "right_hip", "left_knee", "right_knee",
    "left_ankle", "right_ankle", "left_heel", "right_heel",
    "left_foot_index", "right_foot_index",
)

# 姿态分析常用索引（与上面的名称一一对应）。
IDX_NOSE = 0
IDX_LEFT_EAR = 7
IDX_RIGHT_EAR = 8
IDX_LEFT_SHOULDER = 11
IDX_RIGHT_SHOULDER = 12
IDX_LEFT_HIP = 23
IDX_RIGHT_HIP = 24

NUM_POSE_LANDMARKS = 33


class PoseState(str, Enum):
    """单帧姿态估计状态。"""

    OK = "ok"  # 检测到人体，关键点可用
    NO_PERSON = "no_person"  # 画面中未检测到人体
    LOW_VISIBILITY = "low_visibility"  # 检测到人体但关键点质量不足
    ERROR = "error"  # 推理异常


@dataclass
class Landmark:
    """单个关键点。坐标为图像归一化值 [0,1]，z 为相对深度。"""

    x: float
    y: float
    z: float
    visibility: float = 1.0  # MediaPipe visibility，0-1
    presence: float = 1.0  # MediaPipe presence，0-1

    @property
    def is_reliable(self) -> bool:
        return self.visibility >= 0.5


@dataclass
class PoseResult:
    """一帧姿态估计结果。"""

    state: PoseState
    landmarks: list[Landmark] = field(default_factory=list)
    # 关键点有效率：visibility 达标的关键点占比。未检测到人体时为 0.0。
    valid_ratio: float = 0.0
    timestamp: float = 0.0
    error_message: str = ""

    @property
    def has_pose(self) -> bool:
        return self.state is PoseState.OK and len(self.landmarks) == NUM_POSE_LANDMARKS


class PoseModelError(RuntimeError):
    """姿态模型加载失败。"""


class PoseEstimator:
    """MediaPipe PoseLandmarker 封装。

    线程约束: 单实例只应在同一推理线程使用。
    关闭时必须调用 close() 释放模型资源。
    """

    def __init__(
        self,
        model_path: str,
        min_pose_detection_confidence: float = 0.5,
        min_pose_presence_confidence: float = 0.5,
        min_tracking_confidence: float = 0.5,
        visibility_threshold: float = 0.5,
    ) -> None:
        self.visibility_threshold = visibility_threshold
        self._min_detection = min_pose_detection_confidence
        self._min_presence = min_pose_presence_confidence
        self._min_tracking = min_tracking_confidence

        if not os.path.isfile(model_path):
            raise PoseModelError(f"姿态模型文件不存在: {model_path}")

        self._model_path = model_path
        self._landmarker = None
        self._mp_image_cls = None
        self._mp_image_format = None
        self._last_ts_ms: int = -1
        self._load_model()

    # ------------------------------------------------------------------
    # 模型生命周期
    # ------------------------------------------------------------------
    def _load_model(self) -> None:
        """加载 MediaPipe PoseLandmarker。失败抛 PoseModelError，不静默降级。"""
        try:
            import mediapipe as mp
            from mediapipe.tasks.python import BaseOptions
            from mediapipe.tasks.python.vision import (
                PoseLandmarker,
                PoseLandmarkerOptions,
                RunningMode,
            )
        except ImportError as exc:
            raise PoseModelError(
                "mediapipe 未安装或版本不兼容。请执行: pip install mediapipe>=1.0.0"
            ) from exc

        try:
            options = PoseLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=self._model_path),
                running_mode=RunningMode.VIDEO,
                num_poses=1,
                min_pose_detection_confidence=self._min_detection,
                min_pose_presence_confidence=self._min_presence,
                min_tracking_confidence=self._min_tracking,
            )
            self._landmarker = PoseLandmarker.create_from_options(options)
            self._mp_image_cls = mp.Image
            self._mp_image_format = mp.ImageFormat.SRGB
            logger.info("姿态模型已加载: %s", self._model_path)
        except Exception as exc:  # noqa: BLE001 - 包装为领域异常
            raise PoseModelError(f"姿态模型加载失败: {exc}") from exc

    @property
    def model_path(self) -> str:
        return self._model_path

    def close(self) -> None:
        """释放模型资源。幂等。"""
        if self._landmarker is not None:
            try:
                self._landmarker.close()
            except Exception:  # noqa: BLE001
                logger.exception("关闭姿态模型时出现异常")
            finally:
                self._landmarker = None

    def __enter__(self) -> "PoseEstimator":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # 推理
    # ------------------------------------------------------------------
    def estimate(self, bgr_image, timestamp: float) -> PoseResult:
        """对一帧 BGR 图像做姿态估计。

        bgr_image: numpy.ndarray, shape=(h, w, 3), dtype=uint8
        timestamp: 单调递增的时间戳（秒），供 MediaPipe 视频模式跟踪使用。
        """
        if self._landmarker is None:
            return PoseResult(state=PoseState.ERROR, error_message="模型未加载", timestamp=timestamp)
        if bgr_image is None or getattr(bgr_image, "size", 0) == 0:
            return PoseResult(state=PoseState.ERROR, error_message="输入图像为空", timestamp=timestamp)

        try:
            import cv2
            import mediapipe as mp

            rgb = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2RGB)
            mp_image = self._mp_image_cls(image_format=self._mp_image_format, data=rgb)
            # 毫秒时间戳，VIDEO 模式要求**严格**单调递增。
            # 输入时间戳可能来自墙钟或精度不足，这里强制 +1 保证递增。
            ts_ms = int(timestamp * 1000)
            if ts_ms <= self._last_ts_ms:
                ts_ms = self._last_ts_ms + 1
            self._last_ts_ms = ts_ms
            detection = self._landmarker.detect_for_video(mp_image, ts_ms)
        except Exception as exc:  # noqa: BLE001 - 推理异常不能中断采集循环
            logger.exception("姿态推理失败")
            return PoseResult(
                state=PoseState.ERROR, error_message=str(exc), timestamp=timestamp
            )

        if not detection.pose_landmarks:
            return PoseResult(state=PoseState.NO_PERSON, timestamp=timestamp)

        raw = detection.pose_landmarks[0]
        landmarks: list[Landmark] = []
        for lm in raw:
            landmarks.append(
                Landmark(
                    x=float(lm.x),
                    y=float(lm.y),
                    z=float(lm.z),
                    visibility=float(getattr(lm, "visibility", 1.0) or 0.0),
                    presence=float(getattr(lm, "presence", 1.0) or 0.0),
                )
            )

        if len(landmarks) != NUM_POSE_LANDMARKS:
            # 理论上不会发生；防御性处理，视作质量不足
            return PoseResult(
                state=PoseState.LOW_VISIBILITY,
                landmarks=landmarks,
                timestamp=timestamp,
            )

        valid = sum(1 for lm in landmarks if lm.visibility >= self.visibility_threshold)
        valid_ratio = valid / NUM_POSE_LANDMARKS

        state = PoseState.OK if valid_ratio >= 0.5 else PoseState.LOW_VISIBILITY
        return PoseResult(
            state=state,
            landmarks=landmarks,
            valid_ratio=valid_ratio,
            timestamp=timestamp,
        )


def resolve_default_model_path() -> str:
    """定位 pose_landmarker_lite.task。

    查找顺序:
    1. 环境变量 POSTURESENSE_POSE_MODEL
    2. PyInstaller 冻结路径 sys._MEIPASS/models/
    3. 包内 models/ 目录
    4. 项目根 models/ 目录
    """
    env = os.environ.get("POSTURESENSE_POSE_MODEL")
    if env and os.path.isfile(env):
        return env

    here = os.path.dirname(os.path.abspath(__file__))
    candidates = []
    # PyInstaller onedir 打包后模型在 _internal/models/
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(os.path.join(meipass, "models", "pose_landmarker_lite.task"))
    candidates.extend([
        os.path.join(here, "..", "..", "..", "models", "pose_landmarker_lite.task"),
        os.path.join(here, "..", "..", "..", "..", "models", "pose_landmarker_lite.task"),
    ])
    for c in candidates:
        c = os.path.normpath(c)
        if os.path.isfile(c):
            return c

    raise PoseModelError(
        "未找到姿态模型 pose_landmarker_lite.task。"
        "请设置环境变量 POSTURESENSE_POSE_MODEL，或将其放入 models/ 目录。"
    )
