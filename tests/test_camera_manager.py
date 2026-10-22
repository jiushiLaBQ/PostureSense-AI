"""CameraManager 单元测试：打开失败、读帧失败、释放幂等、重连。

全部使用假 VideoCapture，不触碰真实硬件。
"""

from __future__ import annotations

import numpy as np
import pytest

from posturesense.vision.camera_manager import CameraError, CameraManager


class FakeCapture:
    """可控的 cv2.VideoCapture 假件。"""

    def __init__(self, opened: bool = True, frames=None):
        self.opened = opened
        self.frames = list(frames or [])
        self.released = False
        self.props = {}

    def isOpened(self):
        return self.opened and not self.released

    def read(self):
        if not self.isOpened():
            return False, None
        if not self.frames:
            return False, None
        return True, self.frames.pop(0)

    def set(self, prop, val):
        self.props[prop] = val
        return True

    def get(self, prop):
        # CAP_PROP_FRAME_WIDTH=3, CAP_PROP_FRAME_HEIGHT=4
        return {3: 640, 4: 480}.get(prop, 0)

    def release(self):
        self.released = True


def test_open_failure_returns_false(monkeypatch):
    """打不开设备时 open() 返回 False，不抛异常、不留下半开状态。"""
    monkeypatch.setattr(
        "posturesense.vision.camera_manager.cv2.VideoCapture",
        lambda *a, **k: FakeCapture(opened=False),
    )
    cam = CameraManager(device_index=999)
    assert cam.open() is False
    assert cam.is_open is False


def test_read_before_open_returns_false():
    """未打开且关闭自动重连时读帧 → (False, None)，不伪造图像。"""
    cam = CameraManager(auto_reconnect=False)
    ok, frame = cam.read_frame()
    assert ok is False
    assert frame is None


def test_read_failure_returns_false_not_black_frame(monkeypatch):
    """读帧失败时返回 (False, None)，绝不返回静默黑帧。"""
    fake = FakeCapture(opened=True, frames=[])
    monkeypatch.setattr(
        "posturesense.vision.camera_manager.cv2.VideoCapture",
        lambda *a, **k: fake,
    )
    monkeypatch.setattr(CameraManager, "_try_reconnect", lambda self: False)

    cam = CameraManager(auto_reconnect=False)
    assert cam.open() is True
    ok, frame = cam.read_frame()
    assert ok is False
    assert frame is None


def test_successful_read_returns_frame(monkeypatch):
    """正常读帧返回 CameraFrame，帧序号递增。"""
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    fake = FakeCapture(opened=True, frames=[img, img.copy()])
    monkeypatch.setattr(
        "posturesense.vision.camera_manager.cv2.VideoCapture",
        lambda *a, **k: fake,
    )

    cam = CameraManager(flip_horizontal=False)
    assert cam.open() is True

    ok1, f1 = cam.read_frame()
    ok2, f2 = cam.read_frame()
    assert ok1 and ok2
    assert f1.index == 0 and f2.index == 1
    assert f1.width == 640 and f1.height == 480


def test_release_is_idempotent(monkeypatch):
    """release() 可重复调用。"""
    fake = FakeCapture(opened=True, frames=[np.zeros((4, 4, 3), np.uint8)])
    monkeypatch.setattr(
        "posturesense.vision.camera_manager.cv2.VideoCapture",
        lambda *a, **k: fake,
    )
    cam = CameraManager()
    cam.open()
    cam.release()
    cam.release()  # 不应抛异常
    assert cam.is_open is False
    assert fake.released is True


def test_context_manager_releases(monkeypatch):
    """with 退出后资源已释放。"""
    fake = FakeCapture(opened=True, frames=[np.zeros((4, 4, 3), np.uint8)])
    monkeypatch.setattr(
        "posturesense.vision.camera_manager.cv2.VideoCapture",
        lambda *a, **k: fake,
    )
    with CameraManager() as cam:
        assert cam.is_open is True
    assert fake.released is True


def test_context_manager_raises_on_open_failure(monkeypatch):
    """with 打不开时抛 CameraError。"""
    monkeypatch.setattr(
        "posturesense.vision.camera_manager.cv2.VideoCapture",
        lambda *a, **k: FakeCapture(opened=False),
    )
    with pytest.raises(CameraError):
        with CameraManager(device_index=42):
            pass


def test_reconnect_recovers_when_device_returns(monkeypatch):
    """相机拔掉后重连失败 → 设备回来后必须能自动恢复。

    回归 #2: 旧实现 `_cap is None` 直接 return，重连永久失效。
    """
    img = np.zeros((8, 8, 3), dtype=np.uint8)
    calls = {"n": 0, "alive": False}

    def factory(*a, **k):
        calls["n"] += 1
        if calls["alive"]:
            return FakeCapture(opened=True, frames=[img.copy()])
        return FakeCapture(opened=False)

    monkeypatch.setattr(
        "posturesense.vision.camera_manager.cv2.VideoCapture", factory
    )

    cam = CameraManager(auto_reconnect=True, reconnect_interval_sec=0.0)
    # 设备不在 → open 失败
    assert cam.open() is False

    # 多次读帧全部失败（设备仍未插入）
    for _ in range(3):
        ok, fr = cam.read_frame()
        assert ok is False and fr is None

    # 设备回来了
    calls["alive"] = True
    ok, fr = cam.read_frame()
    assert ok is True, "设备恢复后必须能读到帧"
    assert fr is not None


def test_reconnect_recovers_after_failure(monkeypatch):
    """读帧失败后重连成功，后续帧恢复正常。"""
    img = np.zeros((8, 8, 3), dtype=np.uint8)
    caps = [
        FakeCapture(opened=True, frames=[]),  # 第一台：无帧
        FakeCapture(opened=True, frames=[img]),  # 重连后的第二台
    ]
    monkeypatch.setattr(
        "posturesense.vision.camera_manager.cv2.VideoCapture",
        lambda *a, **k: caps.pop(0) if caps else FakeCapture(opened=True, frames=[img]),
    )

    cam = CameraManager(auto_reconnect=True, reconnect_interval_sec=0.0)
    assert cam.open() is True
    ok, frame = cam.read_frame()
    assert ok is True, "重连后应能读到帧"
    assert frame is not None


def test_reconnect_throttled(monkeypatch):
    """重连节流：间隔内的重复调用不再尝试打开。"""
    calls = {"n": 0}

    def factory(*a, **k):
        calls["n"] += 1
        return FakeCapture(opened=True, frames=[])

    monkeypatch.setattr(
        "posturesense.vision.camera_manager.cv2.VideoCapture", factory
    )
    cam = CameraManager(auto_reconnect=True, reconnect_interval_sec=60.0)
    cam.open()
    opened_before = calls["n"]

    cam.read_frame()  # 触发一次重连尝试
    cam.read_frame()  # 节流期内不应再开
    assert calls["n"] <= opened_before + 1


def test_open_after_failed_open_does_not_leak(monkeypatch):
    """open() 重入时清理残留 capture，不泄漏句柄。"""
    first = FakeCapture(opened=False)
    second = FakeCapture(opened=True, frames=[np.zeros((8, 8, 3), np.uint8)])
    seq = [first, second]
    monkeypatch.setattr(
        "posturesense.vision.camera_manager.cv2.VideoCapture",
        lambda *a, **k: seq.pop(0),
    )

    cam = CameraManager()
    assert cam.open() is False
    assert cam.open() is True
    assert cam.is_open is True
    assert first.released is True


def test_repeated_open_close_is_reproducible(monkeypatch):
    """open → release → open 应产生新的帧流（可重启）。"""
    img = np.zeros((8, 8, 3), dtype=np.uint8)

    def factory(*a, **k):
        return FakeCapture(opened=True, frames=[img.copy(), img.copy()])

    monkeypatch.setattr(
        "posturesense.vision.camera_manager.cv2.VideoCapture", factory
    )
    cam = CameraManager(flip_horizontal=False)

    cam.open()
    ok1, f1 = cam.read_frame()
    cam.release()

    cam.open()
    ok2, f2 = cam.read_frame()
    cam.release()

    assert ok1 and ok2
    assert f1.index == 0
    assert f2.index == 0  # 重启后帧序号从 0 重新计
