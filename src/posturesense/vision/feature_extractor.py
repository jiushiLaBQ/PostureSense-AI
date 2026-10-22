"""姿态特征计算：把 33 个关键点转成可解释的姿态特征。

几何定义（仓库根 README.md §4.2 同步维护，改这里必须同步文档）:

坐标系
    MediaPipe 输出为图像归一化坐标 (x, y) ∈ [0,1]，原点左上，y 向下。
    z 为相对深度（无物理单位），本模块**不使用 z 做角度**。

特征
    1. head_forward_ratio  头部前倾 proxy
       耳中点 M_ear 与肩中点 M_sh 的向量 d = M_ear - M_sh（归一化图像坐标）
       head_forward_ratio = d.x_signed / |d.y| 的水平/垂直比
       实际实现: 用 (M_ear.x - M_sh.x) / (M_sh.y - M_ear.y + ε) 的**水平分量/垂直分量**
       解释：头相对肩越靠前（朝镜头一侧倾斜），该值绝对值越大。
       ⚠ 2D 近似，非真实颈椎前倾角。摄像头俯仰会显著影响。

    2. trunk_tilt_deg  躯干倾角（度）
       定义躯干轴向量 v（由髋中点指向肩中点，图像 y 轴翻转使"向上"为正）:
           v = (M_sh.x - M_hip.x,  M_hip.y - M_sh.y)
       躯干相对图像竖直方向的夹角:
           trunk_tilt_deg = |atan2(v.x, v.y)|
       正坐（肩中点在髋中点正上方）→ 0°，侧倾越大值越大，上限 180°。
       ⚠ 2D 图像角，非真实三维躯干角。

    3. shoulder_tilt_deg  肩部倾角（度）
       向量 s = R_sh - L_sh
       肩线相对图像水平方向的**锐**夹角，取值 [0°, 90°]:
           shoulder_tilt_deg = atan2(|s.y|, |s.x|)
       肩水平 → 0°；肩线越陡（一高一低）→ 越接近 90°。
       ⚠ 2D 图像角。左右肩高度差的直观代理。

    4. head_lateral_offset  头相对肩线的横向偏移（归一化）
       头中点 M_head 到肩线段的有符号横向距离 / 肩宽
       正值表示头偏右，负值偏左。

    5. keypoint_valid_ratio  关键点有效率
       visibility ≥ threshold 的关键点占比。

    6. feature_volatility  姿态变化幅度
       由时序层计算（特征序列的滑动极差），本模块不实现。

缺失语义
    每个特征按自己的必要关键点**独立**判定可用性：
    - 肩部倾角：需左右肩
    - 头部前倾 / 头部偏移：需左右肩 + 鼻
    - 躯干倾角：需左右肩 + 左右髋
    桌面摄像头常拍不到下半身（髋部 visibility 低），此时肩/头特征仍可用，
    仅躯干倾角为 None。必要关键点不可靠 → 该特征为 None（"无法判断"），
    绝不返回 0 / 180 等伪造角度（零向量等退化情形统一返回 None）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from .pose_estimator import (
    IDX_LEFT_HIP,
    IDX_LEFT_SHOULDER,
    IDX_NOSE,
    IDX_RIGHT_HIP,
    IDX_RIGHT_SHOULDER,
    Landmark,
    PoseResult,
)

_EPS = 1e-6
# 被视为"可靠"的最低 visibility
DEFAULT_VIS_THRESHOLD = 0.5


@dataclass
class PostureFeatures:
    """单帧姿态特征。None 表示该特征无法可靠计算。"""

    head_forward_ratio: Optional[float]
    trunk_tilt_deg: Optional[float]
    shoulder_tilt_deg: Optional[float]
    head_lateral_offset: Optional[float]
    keypoint_valid_ratio: float
    timestamp: float = 0.0

    @property
    def is_reliable(self) -> bool:
        """至少头部与躯干特征都可用才算可靠。"""
        return (
            self.head_forward_ratio is not None
            and self.trunk_tilt_deg is not None
        )


def _mid(a: Landmark, b: Landmark) -> tuple[float, float]:
    return ((a.x + b.x) / 2.0, (a.y + b.y) / 2.0)


def _reliable(lm: Landmark, threshold: float) -> bool:
    return lm.visibility >= threshold


def extract_features(
    result: PoseResult,
    vis_threshold: float = DEFAULT_VIS_THRESHOLD,
) -> Optional[PostureFeatures]:
    """从 PoseResult 提取姿态特征。

    无人体 / 质量不足时返回 None —— 调用方应展示"无法判断"，
    而不是输出一组零值特征。
    """
    if not result.has_pose:
        return None

    lms = result.landmarks

    # 按特征独立判定可用性：桌面摄像头常拍不到下半身（髋部 visibility 低），
    # 此时肩/头特征仍应可用，仅躯干倾角标记为"无法判断"。
    need_sh = IDX_LEFT_SHOULDER, IDX_RIGHT_SHOULDER
    need_sh_hip = *need_sh, IDX_LEFT_HIP, IDX_RIGHT_HIP
    need_sh_head = *need_sh, IDX_NOSE

    ok_sh = all(_reliable(lms[i], vis_threshold) for i in need_sh)
    ok_sh_hip = ok_sh and all(_reliable(lms[i], vis_threshold) for i in (IDX_LEFT_HIP, IDX_RIGHT_HIP))
    ok_sh_head = ok_sh and _reliable(lms[IDX_NOSE], vis_threshold)

    head_forward = trunk_tilt = shoulder_tilt = head_lateral = None

    if ok_sh:
        l_sh, r_sh = lms[IDX_LEFT_SHOULDER], lms[IDX_RIGHT_SHOULDER]
        m_sh = _mid(l_sh, r_sh)

        # ---- 3. 肩部倾角 ----------------------------------------------
        # 取相对水平线的锐角，范围 [0°, 90°]
        s_x = r_sh.x - l_sh.x
        s_y = r_sh.y - l_sh.y
        if math.hypot(s_x, s_y) > _EPS:
            shoulder_tilt = math.degrees(math.atan2(abs(s_y), abs(s_x)))

        if ok_sh_head:
            head = lms[IDX_NOSE]

            # ---- 1. 头部前倾 proxy ------------------------------------
            # 鼻点作头部代理（耳点常低可见）；dy：肩应在头下方 → 正值
            dy = m_sh[1] - head.y
            if abs(dy) > _EPS:
                head_forward = (head.x - m_sh[0]) / dy

            # ---- 4. 头相对肩线横向偏移 --------------------------------
            shoulder_width = math.hypot(s_x, s_y)
            if shoulder_width > _EPS:
                rel_x = head.x - l_sh.x
                rel_y = head.y - l_sh.y
                cross = s_x * rel_y - s_y * rel_x
                head_lateral = cross / shoulder_width

        if ok_sh_hip:
            l_hip, r_hip = lms[IDX_LEFT_HIP], lms[IDX_RIGHT_HIP]
            m_hip = _mid(l_hip, r_hip)

            # ---- 2. 躯干倾角 ------------------------------------------
            # 躯干轴：髋中点 → 肩中点，图像 y 翻转使"向上"为正
            v_x = m_sh[0] - m_hip[0]
            v_y = m_hip[1] - m_sh[1]
            if math.hypot(v_x, v_y) > _EPS:
                trunk_tilt = abs(math.degrees(math.atan2(v_x, v_y)))

    return PostureFeatures(
        head_forward_ratio=head_forward,
        trunk_tilt_deg=trunk_tilt,
        shoulder_tilt_deg=shoulder_tilt,
        head_lateral_offset=head_lateral,
        keypoint_valid_ratio=result.valid_ratio,
        timestamp=result.timestamp,
    )


def features_to_dict(f: Optional[PostureFeatures]) -> dict:
    """序列化为可存库/导出的 dict。None 保持 None。"""
    if f is None:
        return {}
    return {
        "head_forward_ratio": f.head_forward_ratio,
        "trunk_tilt_deg": f.trunk_tilt_deg,
        "shoulder_tilt_deg": f.shoulder_tilt_deg,
        "head_lateral_offset": f.head_lateral_offset,
        "keypoint_valid_ratio": f.keypoint_valid_ratio,
        "timestamp": f.timestamp,
    }
