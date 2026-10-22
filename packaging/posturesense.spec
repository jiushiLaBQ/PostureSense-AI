# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（onedir）。

只打包 pose_landmarker_lite.task；不含 hand/face 模型（姿态产品不需要）。
不含 Qt3D / 插件 / 键鼠注入（上游弃用项）。

运行: python packaging/build.py
"""

import os

from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

project_root = os.path.abspath(os.path.join(SPECPATH, ".."))
models_dir = os.path.join(project_root, "models")

datas = [
    # 许可清单与项目文档随包分发
    (os.path.join(project_root, "NOTICE"), "."),
    (os.path.join(project_root, "README.md"), "."),
]
# 打包模型（若存在）
pose_model = os.path.join(models_dir, "pose_landmarker_lite.task")
if os.path.isfile(pose_model):
    datas.append((pose_model, "models"))

# mediapipe 无官方 PyInstaller hook：子模块全部收集进 PYZ，
# 数据文件（libmediapipe.dll / .fbs / .txt）收集到磁盘 ——
# 运行时用 importlib.resources.files('mediapipe.tasks.c') 定位 dll。
hiddenimports = [
    "posturesense",
    "posturesense.vision.camera_manager",
    "posturesense.vision.pose_estimator",
    "posturesense.vision.feature_extractor",
    "posturesense.vision.visualizer",
    "posturesense.core.inference_service",
    "posturesense.core.profiler",
    "posturesense.core.baseline_manager",
    "posturesense.core.temporal_analyzer",
    "posturesense.core.reminder_engine",
    "posturesense.core.storage",
    "posturesense.core.analytics",
    "posturesense.core.csv_export",
    "posturesense.core.strategies",
    "posturesense.core.evaluation",
    "posturesense.core.annotations",
    "posturesense.ui.shell",
    "posturesense.ui.pages",
    "posturesense.ui.theme",
    "posturesense.ui.widgets",
    "mediapipe",
    "mediapipe.tasks",
    "mediapipe.tasks.python",
    "mediapipe.tasks.python.vision",
    "cv2",
    "numpy",
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "pydantic",
    "yaml",
]
# 收 mediapipe 全部子模块，但剔除 test/ 测试模块 ——
# 它们引 scipy/sympy 等重型依赖，运行时完全不需要，且会拉爆构建。
_mp_submods = [
    m for m in collect_submodules("mediapipe") if ".test" not in m
]
hiddenimports += _mp_submods
datas += collect_data_files("mediapipe")

a = Analysis(
    [os.path.join(project_root, "src", "posturesense", "app.py")],
    pathex=[os.path.join(project_root, "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 上游弃用项，不打包
        "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput",
        "PySide6.Qt3DAnimation", "PySide6.Qt3DExtras", "PySide6.Qt3DLogic",
        # 同环境装有的其他 Qt 绑定，必须排除（PyInstaller 只支持一个）
        "PyQt5", "PyQt6", "PyQt5.sip",
        # 开发工具链，与运行时无关，排除以缩小体积
        "tkinter",
        "anthropic",
        "httpx",
        "sqlalchemy",
        "sphinx", "docutils", "black", "jedi", "parso",
        "nbformat", "jupyter", "IPython", "zmq",
        "cryptography", "bcrypt",
        # Anaconda base 的 torch 全家桶：matplotlib 用 sys.modules.get("torch")
        # 动态探测，被 modulegraph 静态分析误当成依赖；运行时完全不需要，
        # 且 hook-torch 的 collect_submodules 会因 OMP 重复加载崩掉。
        "torch", "torchvision", "torchaudio", "torchtext",
        "torch._dynamo", "torch._inductor",
        # mediapipe test 模块引入的重科学栈，运行时不需要
        "scipy", "sympy", "gmpy2", "mpmath", "numpy.testing",
        # Anaconda 基础环境混入的无关包（实测 bundle 顶层可见）
        "tornado", "twisted", "zope", "service_identity",
        "mypy", "psutil", "pyreadline3", "tkinter",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PostureSenseAI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # 无控制台窗口
    disable_windowed_traceback=False,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="PostureSenseAI",
)
