"""pytest 共享 fixture。

约定（测试假件声明）:
- 摄像头 / 模型测试一律用可控假件，不依赖真实硬件。
- 假件只用于验证软件逻辑，不得伪装成真实检测结果。
"""

from __future__ import annotations

import numpy as np
import pytest


@pytest.fixture
def fake_bgr_frame():
    """一张合成 BGR 图像（纯色 + 渐变），不含人体。"""
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    img[:, :, 1] = np.linspace(0, 120, 640, dtype=np.uint8)[None, :]
    return img


@pytest.fixture
def synthetic_landmarks():
    """33 个合成关键点坐标（归一化），用于特征计算测试。

    仅模拟数据结构，不代表真实人体测量。
    """
    from posturesense.vision.pose_estimator import NUM_POSE_LANDMARKS, Landmark

    lms = []
    for i in range(NUM_POSE_LANDMARKS):
        lms.append(Landmark(x=0.3 + 0.01 * i, y=0.4 + 0.005 * i, z=0.0, visibility=1.0))
    return lms
