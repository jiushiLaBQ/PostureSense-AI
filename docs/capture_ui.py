"""竞赛 PPT 素材采集：离屏渲染真实 UI 截图 + 骨架叠加示意图。

用法: python docs/capture_ui.py
输出: docs/assets/ui_<page>.png （8 页真实界面截图）
      docs/assets/skeleton_demo.png （visualizer 真实绘制，姿态为合成示意）

说明: 不开摄像头、不加载姿态模型；WA_DontShowOnScreen 离屏抓取
（offscreen 平台无 CJK 字体，故用原生平台 + 不上屏）。
界面数据来自临时数据库（复制真实用户库，含真实校准基线）。
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

ASSETS = PROJECT_ROOT / "docs" / "assets"
REAL_DB = Path(os.path.expanduser("~")) / "PostureSenseAI" / "posturesense.db"

NAV_ORDER = ["home", "monitor", "calibration", "reminders", "history", "analytics", "lab", "privacy"]


def capture_pages() -> None:
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication

    from posturesense.core.storage import Database
    from posturesense.ui.shell import AppShell
    from posturesense.vision.camera_manager import CameraManager

    app = QApplication([])
    app.setFont(QFont("Microsoft YaHei", 10))  # 离屏渲染需显式指定中文字体
    ASSETS.mkdir(parents=True, exist_ok=True)

    class _EstimatorStub:
        """截图不需要加载姿态模型；shell 关闭路径会调用 close()。"""

        model_path = "(screenshot-stub)"

        def close(self) -> None:
            pass

    tmp = Path(tempfile.mkdtemp(prefix="ps_shot_"))
    try:
        # 复制真实用户库：让历史/分析页展示真实会话与基线数据
        db_path = tmp / "shot.db"
        if REAL_DB.is_file():
            shutil.copy2(REAL_DB, db_path)
        db = Database(db_path)
        camera = CameraManager()  # 仅构造，不打开

        shell = AppShell(camera=camera, estimator=_EstimatorStub(), db=db)  # type: ignore[arg-type]
        from PySide6.QtCore import Qt

        shell.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        shell.resize(1280, 800)
        shell.show()
        app.processEvents()

        for i, key in enumerate(NAV_ORDER):
            shell.nav.setCurrentRow(i)
            app.processEvents()
            out = ASSETS / f"ui_{i+1:02d}_{key}.png"
            shell.grab().save(str(out))
            print("saved", out)

        shell.close()
        db.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def skeleton_demo() -> None:
    """用真实 visualizer 在合成姿态上绘制骨架（标注为示意图）。"""
    import cv2
    import numpy as np

    from posturesense.vision.pose_estimator import Landmark, PoseResult, PoseState
    from posturesense.vision.visualizer import draw_pose

    h, w = 480, 640
    canvas = np.full((h, w, 3), (54, 40, 34), dtype=np.uint8)  # BGR 深蓝灰底

    # 合成一个端正坐姿的 33 点（仅示意，非真实检测输出）
    lms = [Landmark(0.5, 0.9, 0.0, 0.0) for _ in range(33)]

    def put(i, x, y, v=0.99):
        lms[i] = Landmark(x, y, 0.0, v)

    put(0, 0.50, 0.18)   # nose
    put(7, 0.44, 0.20); put(8, 0.56, 0.20)  # ears
    put(11, 0.38, 0.38); put(12, 0.62, 0.38)  # shoulders
    put(13, 0.34, 0.58); put(14, 0.66, 0.58)  # elbows
    put(15, 0.32, 0.76); put(16, 0.68, 0.76)  # wrists
    put(23, 0.42, 0.72); put(24, 0.58, 0.72)  # hips
    put(25, 0.42, 0.88); put(26, 0.58, 0.88)  # knees
    for i in (1, 2, 3, 4, 5, 6, 9, 10, 17, 18, 19, 20, 21, 22, 27, 28, 29, 30, 31, 32):
        lms[i] = Landmark(lms[0].x, lms[0].y, 0.0, 0.6)

    result = PoseResult(state=PoseState.OK, landmarks=lms, valid_ratio=1.0, timestamp=0.0)
    canvas = draw_pose(canvas, result)  # draw_pose 返回新图像，不原地修改
    cv2.putText(canvas, "skeleton overlay demo (synthetic pose)", (12, h - 14),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 210, 225), 1, cv2.LINE_AA)
    out = ASSETS / "skeleton_demo.png"
    cv2.imwrite(str(out), canvas)
    print("saved", out)


if __name__ == "__main__":
    capture_pages()
    skeleton_demo()
