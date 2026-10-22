"""PoseEstimator 单元测试：可见性透传、无人体、异常处理、模型缺失。

不加载真实模型 —— 用假 landmarker 注入，验证数据流与状态判定逻辑。
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pytest

from posturesense.vision.pose_estimator import (
    NUM_POSE_LANDMARKS,
    Landmark,
    PoseEstimator,
    PoseResult,
    PoseState,
    PoseModelError,
    resolve_default_model_path,
)


# ---------------------------------------------------------------------------
# 假 MediaPipe 结果
# ---------------------------------------------------------------------------
class _FakeRawLandmark:
    def __init__(self, x, y, z, visibility=1.0, presence=1.0):
        self.x, self.y, self.z = x, y, z
        self.visibility = visibility
        self.presence = presence


class _FakeDetection:
    def __init__(self, pose_landmarks):
        self.pose_landmarks = pose_landmarks


class _FakeLandmarker:
    def __init__(self, detection):
        self._detection = detection
        self.closed = False

    def detect_for_video(self, mp_image, ts_ms):
        return self._detection

    def close(self):
        self.closed = True


class _FakeMpImage:
    """替代 mediapipe.Image，避免测试依赖真实 mediapipe 构造。"""

    def __init__(self, image_format=None, data=None):
        self.image_format = image_format
        self.data = data


def _make_estimator(monkeypatch, detection) -> PoseEstimator:
    """绕过模型加载，注入假 landmarker。"""
    est = PoseEstimator.__new__(PoseEstimator)
    est.visibility_threshold = 0.5
    est._landmarker = _FakeLandmarker(detection)
    est._mp_image_cls = _FakeMpImage
    est._mp_image_format = "SRGB"
    est._model_path = "<fake>"
    est._last_ts_ms = -1
    return est


def _full_landmarks(visibility=1.0):
    return [
        _FakeRawLandmark(0.1 * i, 0.2, 0.0, visibility=visibility)
        for i in range(NUM_POSE_LANDMARKS)
    ]


# ---------------------------------------------------------------------------
# 测试
# ---------------------------------------------------------------------------
def test_ok_state_with_full_visibility(monkeypatch):
    """全部关键点可见 → state=OK, valid_ratio=1.0。"""
    det = _FakeDetection([_full_landmarks(visibility=1.0)])
    est = _make_estimator(monkeypatch, det)
    img = np.zeros((480, 640, 3), dtype=np.uint8)

    result = est.estimate(img, timestamp=1.0)
    assert result.state is PoseState.OK
    assert result.has_pose is True
    assert result.valid_ratio == pytest.approx(1.0)
    assert len(result.landmarks) == NUM_POSE_LANDMARKS


def test_visibility_is_passed_through(monkeypatch):
    """visibility 必须从 MediaPipe 透传，不得硬编码。"""
    raw = _full_landmarks(visibility=1.0)
    raw[11].visibility = 0.2  # 左肩低可见性
    det = _FakeDetection([raw])
    est = _make_estimator(monkeypatch, det)

    result = est.estimate(np.zeros((10, 10, 3), np.uint8), timestamp=1.0)
    assert result.landmarks[11].visibility == pytest.approx(0.2)
    assert result.landmarks[11].is_reliable is False
    assert result.landmarks[0].is_reliable is True


def test_low_visibility_state(monkeypatch):
    """大量低可见性关键点 → LOW_VISIBILITY，不判为 OK。"""
    det = _FakeDetection([_full_landmarks(visibility=0.1)])
    est = _make_estimator(monkeypatch, det)

    result = est.estimate(np.zeros((10, 10, 3), np.uint8), timestamp=1.0)
    assert result.state is PoseState.LOW_VISIBILITY
    assert result.has_pose is False
    assert result.valid_ratio == pytest.approx(0.0)


def test_no_person_state(monkeypatch):
    """无人体入镜 → NO_PERSON，不是异常。"""
    det = _FakeDetection([])
    est = _make_estimator(monkeypatch, det)

    result = est.estimate(np.zeros((10, 10, 3), np.uint8), timestamp=1.0)
    assert result.state is PoseState.NO_PERSON
    assert result.has_pose is False
    assert result.landmarks == []


def test_empty_image_is_error(monkeypatch):
    """空输入图像 → ERROR，不崩溃。"""
    det = _FakeDetection([_full_landmarks()])
    est = _make_estimator(monkeypatch, det)

    result = est.estimate(None, timestamp=1.0)
    assert result.state is PoseState.ERROR
    assert result.error_message


def test_inference_exception_is_captured(monkeypatch):
    """推理抛异常 → ERROR 快照，不向上冒泡。"""
    class _BoomLandmarker(_FakeLandmarker):
        def detect_for_video(self, mp_image, ts_ms):
            raise RuntimeError("boom")

    est = _make_estimator(monkeypatch, _FakeDetection([]))
    est._landmarker = _BoomLandmarker(_FakeDetection([]))

    result = est.estimate(np.zeros((10, 10, 3), np.uint8), timestamp=1.0)
    assert result.state is PoseState.ERROR
    assert "boom" in result.error_message


def test_resolve_model_prefers_env_var(tmp_path, monkeypatch):
    model = tmp_path / "pose_landmarker_lite.task"
    model.write_bytes(b"fake")
    monkeypatch.setenv("POSTURESENSE_POSE_MODEL", str(model))
    assert resolve_default_model_path() == str(model)


def test_resolve_model_uses_frozen_meipass(tmp_path, monkeypatch):
    """PyInstaller 打包后，模型位于 sys._MEIPASS/models/。"""
    meipass = tmp_path
    model = meipass / "models" / "pose_landmarker_lite.task"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"fake")
    monkeypatch.delenv("POSTURESENSE_POSE_MODEL", raising=False)
    # 内建 sys 模块无 _MEIPASS 时 monkeypatch 会失败，手动置位 + 还原
    had = hasattr(sys, "_MEIPASS")
    old = getattr(sys, "_MEIPASS", None)
    sys._MEIPASS = str(meipass)
    try:
        # 确保不会误命中真实仓库里的模型（env 未设置时从 _MEIPASS 找）
        assert resolve_default_model_path() == str(model)
    finally:
        if had:
            sys._MEIPASS = old
        else:
            del sys._MEIPASS


def test_resolve_model_missing_raises(tmp_path, monkeypatch):
    """所有候选都不存在时抛 PoseModelError。"""
    monkeypatch.delenv("POSTURESENSE_POSE_MODEL", raising=False)
    had = hasattr(sys, "_MEIPASS")
    old = getattr(sys, "_MEIPASS", None)
    sys._MEIPASS = str(tmp_path)
    try:
        monkeypatch.setattr(
            "posturesense.vision.pose_estimator.os.path.isfile", lambda _p: False
        )
        with pytest.raises(PoseModelError):
            resolve_default_model_path()
    finally:
        if had:
            sys._MEIPASS = old
        else:
            del sys._MEIPASS


def test_model_file_missing_raises():
    """模型文件不存在 → PoseModelError，不静默降级。"""
    with pytest.raises(PoseModelError):
        PoseEstimator(model_path="Z:/definitely/not/here.task")


def test_close_is_idempotent(monkeypatch):
    """close() 可重复调用。"""
    det = _FakeDetection([_full_landmarks()])
    est = _make_estimator(monkeypatch, det)
    est.close()
    est.close()
    assert est._landmarker is None
