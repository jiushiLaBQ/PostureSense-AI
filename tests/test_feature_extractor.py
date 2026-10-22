"""feature_extractor 测试：几何正确性、边界情况、缺失处理。

守红线：关键点缺失/退化 → None（无法判断），不返回伪造角度。
"""

from __future__ import annotations

import math

import pytest

from posturesense.vision.feature_extractor import (
    PostureFeatures,
    extract_features,
    features_to_dict,
)
from posturesense.vision.pose_estimator import (
    IDX_LEFT_HIP,
    IDX_LEFT_SHOULDER,
    IDX_NOSE,
    IDX_RIGHT_HIP,
    IDX_RIGHT_SHOULDER,
    NUM_POSE_LANDMARKS,
    Landmark,
    PoseResult,
    PoseState,
)


def _make_pose(**overrides) -> PoseResult:
    """构造一个直立坐姿的合成关键点集合。

    仅用于验证几何公式，不代表真实人体测量。
    图像坐标 y 向下：头 y 小，肩 y 中，髋 y 大。
    """
    coords = {
        IDX_NOSE: (0.50, 0.20),
        IDX_LEFT_SHOULDER: (0.40, 0.40),
        IDX_RIGHT_SHOULDER: (0.60, 0.40),
        IDX_LEFT_HIP: (0.42, 0.70),
        IDX_RIGHT_HIP: (0.58, 0.70),
    }
    lms = []
    for i in range(NUM_POSE_LANDMARKS):
        x, y = coords.get(i, (0.5, 0.5))
        vis = 1.0
        if i in overrides.get("low_vis", set()):
            vis = 0.1
        lms.append(Landmark(x=x, y=y, z=0.0, visibility=vis))
    return PoseResult(
        state=PoseState.OK,
        landmarks=lms,
        valid_ratio=1.0,
        timestamp=1.0,
    )


def test_upright_pose_gives_near_zero_trunk_tilt():
    """直立坐姿（肩中点在髋中点正上方）→ 躯干倾角 ≈ 0。"""
    f = extract_features(_make_pose())
    assert f is not None
    assert f.trunk_tilt_deg == pytest.approx(0.0, abs=1.0)
    assert f.shoulder_tilt_deg == pytest.approx(0.0, abs=1.0)


def test_side_lean_increases_trunk_tilt():
    """躯干侧倾 → 倾角增大。"""
    pose = _make_pose()
    # 整体上半身右移，肩中点相对髋中点偏右
    for i in (IDX_LEFT_SHOULDER, IDX_RIGHT_SHOULDER, IDX_NOSE):
        lm = pose.landmarks[i]
        lm.x += 0.10
    f = extract_features(pose)
    assert f.trunk_tilt_deg > 5.0


def test_shoulder_tilt_sign_and_magnitude():
    """肩线倾斜 → 肩部倾角 > 0，且始终为锐角 [0°, 90°]。"""
    pose = _make_pose()
    pose.landmarks[IDX_LEFT_SHOULDER].y -= 0.05  # 左肩更高
    f = extract_features(pose)
    assert f.shoulder_tilt_deg is not None
    assert f.shoulder_tilt_deg > 2.0
    assert 0.0 <= f.shoulder_tilt_deg <= 90.0


def test_shoulder_tilt_acute_when_reversed():
    """左右肩反向（x 差为负）时仍取锐角，不出现 >90° 的值。"""
    pose = _make_pose()
    # 让 R_sh 在 L_sh 左侧（翻转场景）
    pose.landmarks[IDX_RIGHT_SHOULDER].x = 0.30
    pose.landmarks[IDX_LEFT_SHOULDER].x = 0.70
    pose.landmarks[IDX_LEFT_SHOULDER].y = 0.35
    f = extract_features(pose)
    assert f.shoulder_tilt_deg is not None
    assert f.shoulder_tilt_deg <= 90.0


def test_degenerate_shoulder_returns_none():
    """左右肩重合 → 肩倾角与横向偏移为 None，不是 0 或 180。"""
    pose = _make_pose()
    lm = pose.landmarks[IDX_RIGHT_SHOULDER]
    lm.x = pose.landmarks[IDX_LEFT_SHOULDER].x
    lm.y = pose.landmarks[IDX_LEFT_SHOULDER].y
    f = extract_features(pose)
    assert f.shoulder_tilt_deg is None
    assert f.head_lateral_offset is None
    # 躯干仍可用（肩中点与髋中点不重合）
    assert f.trunk_tilt_deg is not None


def test_degenerate_trunk_returns_none():
    """肩中点与髋中点重合 → 躯干倾角 None，不是伪造角度。"""
    pose = _make_pose()
    # 让肩中点 = 髋中点
    mid_x = 0.5
    mid_y = 0.70
    for i, x in ((IDX_LEFT_SHOULDER, mid_x - 0.1), (IDX_RIGHT_SHOULDER, mid_x + 0.1)):
        pose.landmarks[i].x = x
        pose.landmarks[i].y = mid_y
    for i, x in ((IDX_LEFT_HIP, mid_x - 0.08), (IDX_RIGHT_HIP, mid_x + 0.08)):
        pose.landmarks[i].x = x
        pose.landmarks[i].y = mid_y
    f = extract_features(pose)
    assert f.trunk_tilt_deg is None


def test_low_visibility_yields_none_features():
    """必要关键点不可靠 → 对应特征为 None（无法判断）。"""
    pose = _make_pose(low_vis={IDX_LEFT_SHOULDER, IDX_RIGHT_SHOULDER})
    f = extract_features(pose)
    assert f is not None
    assert f.head_forward_ratio is None
    assert f.trunk_tilt_deg is None
    assert f.shoulder_tilt_deg is None
    assert f.head_lateral_offset is None
    assert f.is_reliable is False


def test_hips_occluded_keeps_shoulder_head_features():
    """髋部不可见（桌面摄像头常见）→ 躯干倾角 None，肩/头特征仍可用。"""
    pose = _make_pose(low_vis={IDX_LEFT_HIP, IDX_RIGHT_HIP})
    f = extract_features(pose)
    assert f is not None
    assert f.trunk_tilt_deg is None
    assert f.shoulder_tilt_deg is not None
    assert f.head_forward_ratio is not None
    assert f.head_lateral_offset is not None
    # is_reliable 要求头+躯干都可用 → False
    assert f.is_reliable is False


def test_no_pose_returns_none():
    """无人体 → extract_features 返回 None。"""
    empty = PoseResult(state=PoseState.NO_PERSON, landmarks=[], valid_ratio=0.0)
    assert extract_features(empty) is None


def test_head_lateral_offset_sign():
    """头偏向右肩侧 → 横向偏移符号符合定义。"""
    pose = _make_pose()
    pose.landmarks[IDX_NOSE].x = 0.70  # 明显偏右
    f = extract_features(pose)
    assert f.head_lateral_offset is not None
    # 叉积定义：头偏右应为负（肩线从左到右）
    assert f.head_lateral_offset < 0


def test_features_to_dict_roundtrip():
    f = extract_features(_make_pose())
    d = features_to_dict(f)
    assert d["trunk_tilt_deg"] == f.trunk_tilt_deg
    assert d["keypoint_valid_ratio"] == f.keypoint_valid_ratio
    assert features_to_dict(None) == {}


def test_none_features_serialized_as_none():
    """不可靠特征序列化后仍为 None，不变成 0。"""
    pose = _make_pose(low_vis={IDX_NOSE, IDX_LEFT_HIP, IDX_RIGHT_HIP})
    d = features_to_dict(extract_features(pose))
    assert d["head_forward_ratio"] is None
    assert d["trunk_tilt_deg"] is None
