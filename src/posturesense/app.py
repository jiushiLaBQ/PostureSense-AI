"""应用入口。

用法::

    python -m posturesense
    python -m posturesense --list-cameras
    python -m posturesense --camera 1 --model path/to/pose_landmarker_lite.task
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="posturesense",
        description="智姿 AI (PostureSense AI) — 人体工学智能感知与自适应辅助系统",
    )
    parser.add_argument("--camera", type=int, default=0, help="摄像头设备索引（默认 0）")
    parser.add_argument("--model", type=str, default="", help="pose_landmarker 模型路径")
    parser.add_argument("--width", type=int, default=1280, help="采集宽度")
    parser.add_argument("--height", type=int, default=720, help="采集高度")
    parser.add_argument("--no-flip", action="store_true", help="不水平翻转画面")
    parser.add_argument("--list-cameras", action="store_true", help="列出可用摄像头后退出")
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="无 GUI 冒烟自检：真实摄像头推理 N 帧后退出（打包验证用）",
    )
    parser.add_argument("--smoke-frames", type=int, default=15, help="冒烟帧数")
    parser.add_argument("--log-level", default="INFO", help="日志级别")
    return parser


def _load_estimator(model_arg: str) -> PoseEstimator:
    """按参数/env/默认路径加载模型；失败抛异常。"""
    from posturesense.vision.pose_estimator import PoseEstimator, resolve_default_model_path

    model_path = model_arg or ""
    if not model_path:
        model_path = resolve_default_model_path()
    return PoseEstimator(model_path)


def _make_camera(args) -> CameraManager:
    from posturesense.vision.camera_manager import CameraManager

    return CameraManager(
        device_index=args.camera,
        width=args.width,
        height=args.height,
        flip_horizontal=not args.no_flip,
    )


def _run_smoke(args) -> int:
    """冻结包验收：真实打开摄像头 + 推理 N 帧，结果写文件与 stdout。

    不做假：相机打不开或推理失败 → 返回非 0 且结果文件标注失败。
    """
    from posturesense.core.inference_service import InferenceService

    try:
        estimator = _load_estimator(args.model)
    except Exception as exc:  # noqa: BLE001
        print(f"冒烟失败: 模型加载 {exc}", file=sys.stderr)
        return 3

    camera = _make_camera(args)
    svc = InferenceService(camera, estimator)
    result_path = Path.home() / "PostureSenseAI" / "smoke_result.txt"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        svc.start()
    except Exception as exc:  # noqa: BLE001
        msg = f"冒烟失败: 相机打开 {exc}"
        print(msg, file=sys.stderr)
        result_path.write_text(msg, encoding="utf-8")
        svc.close()
        return 3

    states: dict[str, int] = {}
    last_error = ""
    try:
        for _ in range(args.smoke_frames):
            r = svc.process_once()
            if r.error:
                last_error = r.error
                break
            if r.pose is not None:
                states[r.pose.state] = states.get(r.pose.state, 0) + 1
        if last_error:
            msg = f"冒烟失败: {last_error}"
            print(msg, file=sys.stderr)
            result_path.write_text(msg, encoding="utf-8")
            return 1
        msg = (
            f"冒烟通过: {args.smoke_frames} 帧, "
            f"FPS≈{r.perf.fps:.1f} 延迟≈{r.perf.frame_latency_ms:.1f}ms\n"
            f"姿态状态分布: {states or '无人体'}"
        )
        print(msg)
        result_path.write_text(msg, encoding="utf-8")
        return 0
    finally:
        svc.close()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _setup_logging(args.log_level)
    logger = logging.getLogger("posturesense")

    if args.list_cameras:
        from posturesense.vision.camera_manager import CameraManager

        cams = CameraManager.list_available_cameras()
        if cams:
            print("可用摄像头索引:", ", ".join(str(c) for c in cams))
        else:
            print("未发现可用摄像头")
        return 0

    if args.smoke:
        return _run_smoke(args)

    # 延迟导入：--list-cameras / --smoke 不应强制加载 Qt
    try:
        from PySide6.QtWidgets import QApplication

        from posturesense.core.storage import Database
        from posturesense.ui.shell import AppShell
        from posturesense.vision.camera_manager import CameraManager
        from posturesense.vision.pose_estimator import PoseEstimator
    except ImportError as exc:
        print(f"依赖缺失: {exc}", file=sys.stderr)
        print("请执行: pip install -e .[dev]", file=sys.stderr)
        return 2

    try:
        estimator = _load_estimator(args.model)
    except Exception as exc:  # noqa: BLE001
        print(f"姿态模型加载失败: {exc}", file=sys.stderr)
        return 3

    camera = _make_camera(args)

    # 本地数据库：用户目录下，便于卸载/删除
    db_path = Path.home() / "PostureSenseAI" / "posturesense.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = Database(db_path)
    logger.info("数据库: %s", db_path)

    app = QApplication(sys.argv if argv is None else [sys.argv[0], *argv])
    window = AppShell(camera, estimator, db)
    window.show()
    logger.info(
        "主窗口已显示，camera=%s model=%s", args.camera, estimator.model_path
    )
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
