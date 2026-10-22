"""InferenceService 测试：调度、资源释放语义、无相机不伪造数据。"""

from __future__ import annotations

import numpy as np
import pytest

from posturesense.core.inference_service import InferenceService
from posturesense.vision.pose_estimator import (
    NUM_POSE_LANDMARKS,
    Landmark,
    PoseResult,
    PoseState,
)


class FakeCamera:
    def __init__(self, frames=None, open_ok=True):
        self.frames = list(frames or [])
        self.open_ok = open_ok
        self.release_count = 0
        self.device_index = 0

    def open(self):
        return self.open_ok

    def release(self):
        self.release_count += 1

    def read_frame(self):
        if not self.frames:
            return False, None
        return True, self.frames.pop(0)


class FakeFrame:
    def __init__(self, img):
        self.image = img
        self.timestamp = 1.0
        self.width = img.shape[1]
        self.height = img.shape[0]
        self.index = 0


class FakeEstimator:
    def __init__(self, result):
        self.result = result
        self.closed = False

    def estimate(self, bgr, ts):
        return self.result

    def close(self):
        self.closed = True


def _pose_ok():
    lms = [
        Landmark(x=0.5, y=0.5, z=0.0, visibility=1.0)
        for _ in range(NUM_POSE_LANDMARKS)
    ]
    return PoseResult(state=PoseState.OK, landmarks=lms, valid_ratio=1.0, timestamp=1.0)


def test_process_once_returns_annotated_frame():
    """有相机数据时返回叠加图像与真实性能快照。"""
    img = np.zeros((48, 64, 3), dtype=np.uint8)
    cam = FakeCamera(frames=[FakeFrame(img)])
    est = FakeEstimator(_pose_ok())
    svc = InferenceService(cam, est, draw_skeleton=True)

    res = svc.process_once()
    assert res.has_camera is True
    assert res.annotated_bgr is not None
    assert res.annotated_bgr.shape == (48, 64, 3)
    assert res.perf.frames_processed == 1


def test_process_once_extracts_features():
    """姿态特征应从关键点计算得到。"""
    from posturesense.vision.pose_estimator import IDX_LEFT_HIP, IDX_LEFT_SHOULDER, IDX_NOSE, IDX_RIGHT_HIP, IDX_RIGHT_SHOULDER

    img = np.zeros((48, 64, 3), dtype=np.uint8)
    lms = [Landmark(x=0.5, y=0.5, z=0.0, visibility=1.0) for _ in range(NUM_POSE_LANDMARKS)]
    # 直立几何
    lms[IDX_NOSE] = Landmark(0.50, 0.20, 0.0, 1.0)
    lms[IDX_LEFT_SHOULDER] = Landmark(0.40, 0.40, 0.0, 1.0)
    lms[IDX_RIGHT_SHOULDER] = Landmark(0.60, 0.40, 0.0, 1.0)
    lms[IDX_LEFT_HIP] = Landmark(0.42, 0.70, 0.0, 1.0)
    lms[IDX_RIGHT_HIP] = Landmark(0.58, 0.70, 0.0, 1.0)
    pose = PoseResult(state=PoseState.OK, landmarks=lms, valid_ratio=1.0, timestamp=1.0)

    cam = FakeCamera(frames=[FakeFrame(img)])
    est = FakeEstimator(pose)
    svc = InferenceService(cam, est, draw_skeleton=False)

    res = svc.process_once()
    assert res.features is not None
    assert res.features.trunk_tilt_deg == pytest.approx(0.0, abs=1.0)
    assert res.features.keypoint_valid_ratio == pytest.approx(1.0)


def test_no_person_features_none():
    """无人体时 features 为 None（无法判断），不是零值特征。"""
    img = np.zeros((48, 64, 3), dtype=np.uint8)
    pose = PoseResult(state=PoseState.NO_PERSON, landmarks=[], valid_ratio=0.0, timestamp=1.0)
    cam = FakeCamera(frames=[FakeFrame(img)])
    est = FakeEstimator(pose)
    svc = InferenceService(cam, est, draw_skeleton=True)

    res = svc.process_once()
    assert res.features is None


def test_camera_failure_does_not_fake_image():
    """读帧失败 → 不返回伪造图像。"""
    cam = FakeCamera(frames=[])
    est = FakeEstimator(_pose_ok())
    svc = InferenceService(cam, est)

    res = svc.process_once()
    assert res.has_camera is False
    assert res.annotated_bgr is None
    assert res.error == "camera read failed"


def test_stop_releases_camera_but_not_estimator():
    """stop() 释放相机、保留模型（支持再次开始）。"""
    cam = FakeCamera(frames=[])
    est = FakeEstimator(_pose_ok())
    svc = InferenceService(cam, est)

    svc.stop()
    assert cam.release_count == 1
    assert est.closed is False


def test_close_releases_everything():
    """close() 释放相机 + 模型。"""
    cam = FakeCamera(frames=[])
    est = FakeEstimator(_pose_ok())
    svc = InferenceService(cam, est)

    svc.close()
    assert cam.release_count == 1
    assert est.closed is True


def test_stop_is_idempotent():
    """stop() 可重复调用。"""
    cam = FakeCamera(frames=[])
    est = FakeEstimator(_pose_ok())
    svc = InferenceService(cam, est)
    svc.stop()
    svc.stop()
    assert cam.release_count == 2


def test_start_failure_raises_camera_error():
    """相机打不开时 start() 抛 CameraError。"""
    from posturesense.vision.camera_manager import CameraError

    cam = FakeCamera(open_ok=False)
    est = FakeEstimator(_pose_ok())
    svc = InferenceService(cam, est)

    with pytest.raises(CameraError):
        svc.start()
