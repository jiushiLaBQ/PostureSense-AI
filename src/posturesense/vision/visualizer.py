"""骨架与关键点叠加绘制。

仅做可视化，不做任何判断。坐标为图像归一化 [0,1]，按实际图像宽高换算。
"""

from __future__ import annotations

import cv2
import numpy as np

from .pose_estimator import (
    Landmark,
    PoseResult,
)

# MediaPipe Pose 骨架连接（索引对）
POSE_CONNECTIONS: tuple[tuple[int, int], ...] = (
    (0, 1), (0, 2), (0, 3), (0, 4), (0, 5), (0, 6), (0, 7), (0, 8),
    (9, 10),
    (11, 12), (11, 13), (13, 15), (15, 17), (15, 19), (15, 21), (17, 19),
    (12, 14), (14, 16), (16, 18), (16, 20), (16, 22), (18, 20),
    (11, 23), (12, 24), (23, 24),
    (23, 25), (25, 27), (27, 29), (27, 31), (29, 31),
    (24, 26), (26, 28), (28, 30), (28, 32), (30, 32),
)

# 配色：深色科技风（青色骨架，可信度低时变紫）
_COLOR_OK = (255, 200, 0)  # BGR 青色系
_COLOR_LOW = (180, 80, 200)  # BGR 紫色
_COLOR_TEXT = (220, 220, 220)
_COLOR_BADGE_OK = (0, 180, 120)
_COLOR_BADGE_WARN = (0, 140, 255)
_COLOR_BADGE_ERR = (60, 60, 220)


def _to_px(lm: Landmark, w: int, h: int) -> tuple[int, int]:
    return int(lm.x * w), int(lm.y * h)


def draw_pose(
    image: np.ndarray,
    result: PoseResult,
    show_labels: bool = True,
) -> np.ndarray:
    """在 BGR 图像上叠加骨架与状态徽标。返回新图像（不修改输入）。"""
    canvas = image.copy()
    h, w = canvas.shape[:2]

    if result.has_pose:
        lms = result.landmarks
        color = _COLOR_OK if result.valid_ratio >= 0.7 else _COLOR_LOW

        for a, b in POSE_CONNECTIONS:
            la, lb = lms[a], lms[b]
            # 任一端点不可信则不画，避免骨架错乱
            if la.visibility < 0.3 or lb.visibility < 0.3:
                continue
            cv2.line(canvas, _to_px(la, w, h), _to_px(lb, w, h), color, 2, cv2.LINE_AA)

        for lm in lms:
            if lm.visibility < 0.3:
                continue
            px, py = _to_px(lm, w, h)
            r = 3 if lm.visibility >= 0.5 else 2
            cv2.circle(canvas, (px, py), r, color, -1, cv2.LINE_AA)

        if show_labels:
            _draw_validity(canvas, result)
    else:
        _draw_state_badge(canvas, result)

    return canvas


def _draw_validity(canvas: np.ndarray, result: PoseResult) -> None:
    """在左上角绘制关键点有效率。"""
    h, w = canvas.shape[:2]
    text = f"keypoint validity: {result.valid_ratio * 100:.0f}%"
    cv2.rectangle(canvas, (8, 8), (8 + 230, 36), (30, 30, 30), -1)
    cv2.putText(
        canvas, text, (16, 28),
        cv2.FONT_HERSHEY_SIMPLEX, 0.55, _COLOR_TEXT, 1, cv2.LINE_AA,
    )


def _draw_state_badge(canvas: np.ndarray, result: PoseResult) -> None:
    """无人体 / 质量不足 / 异常时的状态徽标。"""
    if result.state.value == "no_person":
        label, color = "no person detected", _COLOR_BADGE_WARN
    elif result.state.value == "low_visibility":
        label, color = "low keypoint quality", _COLOR_BADGE_WARN
    else:
        label, color = "detection error", _COLOR_BADGE_ERR

    cv2.rectangle(canvas, (8, 8), (8 + 280, 44), (30, 30, 30), -1)
    cv2.rectangle(canvas, (8, 8), (16, 44), color, -1)
    cv2.putText(
        canvas, label, (26, 32),
        cv2.FONT_HERSHEY_SIMPLEX, 0.6, _COLOR_TEXT, 1, cv2.LINE_AA,
    )
