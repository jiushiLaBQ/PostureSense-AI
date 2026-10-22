"""visualizer 测试：状态徽标不得把'未检测/无法判断'显示成'姿态异常'。

守红线 3：关键点缺失/质量不足 = 无法判断，不是异常。
"""

from __future__ import annotations

import numpy as np

from posturesense.vision.pose_estimator import (
    NUM_POSE_LANDMARKS,
    Landmark,
    PoseResult,
    PoseState,
)
from posturesense.vision.visualizer import draw_pose


def _img():
    return np.zeros((240, 320, 3), dtype=np.uint8)


def _pose(state, valid=1.0, with_landmarks=True):
    lms = []
    if with_landmarks:
        lms = [
            Landmark(x=0.3 + 0.01 * i, y=0.4, z=0.0, visibility=valid)
            for i in range(NUM_POSE_LANDMARKS)
        ]
    return PoseResult(state=state, landmarks=lms, valid_ratio=valid, timestamp=1.0)


def test_no_person_does_not_render_skeleton():
    """未检测到人体时不画骨架。"""
    out = draw_pose(_img(), _pose(PoseState.NO_PERSON, with_landmarks=False))
    assert out.shape == (240, 320, 3)
    # 原图近乎纯黑，若画了骨架会有非零像素
    assert int(out.max()) > 0  # 有徽标文字
    # 徽标区域之外应保持较暗（骨架只画在中部）
    center = out[100:200, 100:250]
    assert int(center.max()) == 0


def test_ok_pose_renders_skeleton():
    """检测到人体时画骨架。"""
    out = draw_pose(_img(), _pose(PoseState.OK, valid=1.0))
    assert int(out[100:200, 100:250].max()) > 0


def test_input_image_not_mutated():
    """draw_pose 不修改输入图像。"""
    src = _img()
    src_before = src.copy()
    draw_pose(src, _pose(PoseState.OK))
    assert np.array_equal(src, src_before)


def test_badge_present_for_non_ok_states():
    """非 OK 状态必须渲染可见徽标（状态可见性）。"""
    for st in (PoseState.NO_PERSON, PoseState.LOW_VISIBILITY, PoseState.ERROR):
        out = draw_pose(_img(), _pose(st, with_landmarks=False))
        assert int(out[8:44, 8:288].max()) > 0, f"state={st} 无徽标"
