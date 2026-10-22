"""打包脚本：模型校验 + PyInstaller 构建。

用法::

    python packaging/build.py
    python packaging/build.py --model path/to/pose_landmarker_lite.task

设计要点:
- 构建前**校验模型存在且 SHA-256 匹配**，失败中止（不产出缺模型的包）
- 不静默吞错误
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

# 已核实的模型摘要（溯源见仓库根 README.md §2 模型文件一节）
POSE_MODEL_SHA256 = "59929e1d1ee95287735ddd833b19cf4ac46d29bc7afddbbf6753c459690d574a"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODEL = PROJECT_ROOT / "models" / "pose_landmarker_lite.task"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_model(model_path: Path) -> Path:
    """确认模型存在且摘要匹配；否则复制到 models/ 并校验。"""
    if not model_path.is_file():
        raise SystemExit(
            f"错误: 模型文件不存在 {model_path}\n"
            f"请用 --model 指定 pose_landmarker_lite.task 的路径。"
        )

    digest = sha256_of(model_path)
    if digest != POSE_MODEL_SHA256:
        print(f"警告: 模型 SHA-256 与已知值不一致。\n  实际: {digest}\n  预期: {POSE_MODEL_SHA256}")
        print("继续打包，但请确认模型来源可信。")

    models_dir = PROJECT_ROOT / "models"
    models_dir.mkdir(exist_ok=True)
    target = models_dir / "pose_landmarker_lite.task"
    if not target.is_file() or sha256_of(target) != digest:
        shutil.copy2(model_path, target)
        print(f"已复制模型 → {target}")
    return target


def run_pyinstaller() -> None:
    spec = PROJECT_ROOT / "packaging" / "posturesense.spec"
    if not spec.is_file():
        raise SystemExit(f"错误: 找不到 spec 文件 {spec}")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        str(spec),
    ]
    print("执行:", " ".join(cmd))
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    if result.returncode != 0:
        raise SystemExit(f"PyInstaller 失败，退出码 {result.returncode}")

    dist = PROJECT_ROOT / "dist" / "PostureSenseAI"
    if dist.is_dir():
        exe = dist / "PostureSenseAI.exe"
        print(f"\n构建完成: {dist}")
        if exe.is_file():
            print(f"可执行文件: {exe} ({exe.stat().st_size / 1024 / 1024:.1f} MB)")
    else:
        print("警告: 未找到 dist/PostureSenseAI")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="构建 PostureSense AI 可执行包")
    parser.add_argument(
        "--model",
        default=str(DEFAULT_MODEL),
        help="pose_landmarker_lite.task 路径",
    )
    args = parser.parse_args(argv)

    print("=== PostureSense AI 打包 ===")
    print(f"项目根: {PROJECT_ROOT}")
    print(f"模型源: {args.model}")

    ensure_model(Path(args.model))

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("错误: 未安装 PyInstaller。请执行: pip install pyinstaller", file=sys.stderr)
        return 2

    run_pyinstaller()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
