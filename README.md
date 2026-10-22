# 智姿 AI (PostureSense AI) —— 基于个人基线的离线坐姿守护系统

Windows 桌面端 · 本地离线 · 版本 0.1.0

> **使用边界**: 本软件用于日常姿态观察与使用习惯参考，**不提供医学诊断**，不声称预防或治疗颈椎疾病。
> 摄像头角度、遮挡与光照会影响结果；关键点质量不足时显示「无法判断」而非强行输出异常标签。
> 如需医学建议，请咨询专业医疗人员。

---

## 1. 作品简介

智姿 AI 是一款运行在 Windows 电脑上、完全本地离线的智能坐姿守护软件。它通过摄像头实时捕捉 **33 个人体关键点**，计算头部前倾、肩部倾斜、躯干弯曲等人体工学特征，在坐姿**持续**偏离时才提醒——不是单帧误报，而是会"观察一会儿再说话"。

命名点题："智"是本地智能推理，"姿"是坐姿体态；"千坐千面"突出**个人基线**（每个人的端正姿态不同，不套用通用阈值）；"离线守护"突出**全程本地、隐私无忧**。

区别于同类产品的三个特点：

1. **千人千面**：首次使用 30 秒校准个人基线，按"你自己"的端正姿态判断偏差，而非一刀切的通用角度阈值，适配不同身高体态与坐习惯；
2. **时序智能**：内置 8 状态时序状态机与滞后判决，短暂动作不误报，持续低头/驼背伏案才触发；提醒带冷却、静音、延后与反馈闭环，打扰可控；
3. **全程离线**：画面即时处理、不留存不上传，记录存于本地 SQLite（默认不存视频、不做人脸身份识别），隐私页一键删除；断网可用，核心检测不依赖任何云 API。

性能实测（普通核显笔记本 CPU，无独立 GPU）：640×480 下 30 FPS、单帧 31ms。工程上配备 180 项自动化测试与一键安装包。

---

## 2. 安装方式

| 项 | 要求 |
|---|---|
| 操作系统 | Windows 10 / 11（64 位） |
| 摄像头 | 任一内置或 USB 摄像头 |
| 网络 | **全程无需联网**（安装、运行均离线） |

### 方式一：Windows 安装包（已实测 ✅）

双击 `PostureSenseAI-Setup-0.1.0.exe`（约 180 MB，内置全部依赖）→ 按向导安装 → 开始菜单/桌面启动「智姿 AI」。卸载从开始菜单进行；卸载**保留**用户数据目录 `%USERPROFILE%\PostureSenseAI\`，可手动删除。

### 方式二：免安装冻结包

执行 `python packaging/build.py` 生成 `dist/PostureSenseAI/`（onedir 目录，含 `_internal/` 全部依赖，约 762 MB），运行其中 `PostureSenseAI.exe` 即可。删除该目录即完成卸载。

### 方式三：源码运行

```bash
cd posturesense
python -m venv .venv
.venv\Scripts\activate
pip install -e .[dev]
```

**模型文件**: 需要 `pose_landmarker_lite.task`（5,777,746 字节，Google MediaPipe 模型资产）。本仓库已放在 `posturesense/models/`。程序查找顺序:

1. 环境变量 `POSTURESENSE_POSE_MODEL`
2. PyInstaller 冻结路径 `sys._MEIPASS/models/`（打包产物内）
3. 包相对路径 `models/`
4. 项目根 `models/`

一键启动脚本: 双击 `start_posturesense.bat`（自动定位目录、检测 Python 可用性、透传命令行参数）。

---

## 3. 运行方式

```bash
python -m posturesense                    # 启动主界面（左侧 8 页导航）
python -m posturesense --list-cameras     # 列出可用摄像头后退出
python -m posturesense --camera 1         # 指定摄像头索引（默认 0）
python -m posturesense --model <path>     # 指定模型路径
python -m posturesense --width 640 --height 480   # 采集分辨率（默认 1280×720）
python -m posturesense --no-flip          # 不水平翻转画面
python -m posturesense --smoke --smoke-frames 20  # 无 GUI 冒烟自检
python -m posturesense --log-level DEBUG  # 日志级别
```

**冒烟自检**: `--smoke` 真实打开摄像头推理 N 帧后退出，结果写入 `%USERPROFILE%\PostureSenseAI\smoke_result.txt`（含 FPS/延迟/状态分布），退出码 0 通过、1 失败、3 模型缺失。用于打包验证与无 GUI 环境自检。

**界面 8 页**: 产品首页 / 实时姿态监测 / 个性化姿态校准 / 智能提醒设置 / 会话记录与历史回顾 / 数据分析中心 / 算法测试实验室 / 隐私与系统设置。

**基本流程**: 「实时姿态监测」→「开始监测」（摄像头立即开启）→「停止监测」（摄像头立即释放）。首次使用先到「个性化姿态校准」页采集 30 秒建立基线，未校准时系统明示"默认规则模式"。

---

## 4. 算法结构

> **核心声明**: 以下所有角度与比值均为**二维图像坐标**下的几何量，**不是**真实三维人体角度。摄像头俯仰、偏航、距离与画面缩放都会改变数值。

### 4.1 总体链路

```
摄像头 cv2.read()
  → PoseEstimator（MediaPipe PoseLandmarker，33 点，透传 visibility）
  → FeatureExtractor（5 个姿态特征，缺失→None）
  → TemporalAnalyzer（滑窗平滑 + 8 态状态机 + 滞回）
  → ReminderEngine（冷却/静音/延后）→ SQLite 落库
```

核心层不依赖 Qt，可独立单测；推理在 QThread 执行，GUI 线程不做采集/推理。

### 4.2 姿态特征（几何公式）

坐标为图像归一化 `(x, y) ∈ [0,1]`，y 向下。记号: `m_sh`=肩中点，`m_hip`=髋中点，`head`=鼻点。

| 特征 | 必要关键点 | 公式 | 范围 |
|---|---|---|---|
| `head_forward_ratio` 头部前倾 | 左右肩 + 鼻 | `(head.x - m_sh.x) / (m_sh.y - head.y)` | 无界（典型 \|值\| < 2） |
| `trunk_tilt_deg` 躯干倾角 | 左右肩 + 左右髋 | `\|atan2(v.x, v.y)\|`，`v = m_sh - m_hip` | [0°, 180°) |
| `shoulder_tilt_deg` 肩部倾角 | 左右肩 | `atan2(\|s.y\|, \|s.x\|)`，`s = r_sh - l_sh` | [0°, 90°] |
| `head_lateral_offset` 头部偏移 | 左右肩 + 鼻 | `cross(s, head - l_sh) / \|s\|` | 归一化，有符号 |
| `keypoint_valid_ratio` 有效率 | — | `visibility ≥ 0.5 的关键点数 / 33` | [0,1] |

**缺失语义（红线）**: 某特征必要关键点任一 `visibility < 0.5` → 该特征为 `None`（UI 显示 `—`，绝不补 0/180 假值）；退化几何（肩重合等）→ `None`。髋部出画时躯干倾角为 `None`，肩/头特征仍可用——按特征独立判定，互不牵连。

### 4.3 单帧状态（缺失 ≠ 异常）

| 状态 | 条件 | 是否算异常 |
|---|---|---|
| `OK` | 检测到人体且 `valid_ratio ≥ 0.5` | 正常判定 |
| `NO_PERSON` | 未检测到人体 | **不算** |
| `LOW_VISIBILITY` | 有关键点但 `valid_ratio < 0.5` | **不算**（无法判断） |
| `ERROR` | 推理异常 | 显示错误 |

### 4.4 个人基线（个性化判定）

校准: 用户主动采集 ≥30 秒自然坐姿 → 过滤低质量样本 → 统计 mean/std → 保存；样本不足**拒绝保存**。

判定: 标准化偏差

```
z_i = (x_i - μ_i) / (σ_i + ε)        ε = 1e-3
```

低方差特征（σ < 0.02）改用绝对偏差归一化避免 z 爆炸；各特征 |z| 取平均得综合偏离量。未校准时退回绝对几何偏离量（0–10 量级）并明示"默认规则模式"。

### 4.5 时序状态机与报警阈值

**什么算「坐姿不端正」**: 本软件不用主观描述，判定完全由**综合偏离量**决定——平滑后偏离量 ≥ 2.0 即视为"坐姿偏离"（不端正），< 1.7 视为恢复。偏离量两种计算模式:

| 模式 | 偏离量定义 | ≥2.0 的含义 |
|---|---|---|
| 未校准（默认规则） | 三项几何偏离的均值: 躯干倾角超过 10° 部分 /5、肩部倾角超过 5° 部分 /5、头部前倾比绝对值 ×4（上限 10）；任一项缺失则不参与，全部缺失 → 无法判断 | 躯干明显前倾 / 肩膀明显歪斜 / 头明显前伸，三者折算后综合超标 |
| 已校准（个人基线） | 各特征 \|z 分数\| 的均值（z = 偏离个人基线均值几个标准差） | 当前坐姿偏离**你自己**的端正基线约 2 个标准差 |

单帧达到偏离还不算异常: 须经 30 帧滑窗平滑后仍 ≥ 2.0，并**连续保持 30 秒**，才记为一次"持续坐姿不端正"事件并提醒。

```
INIT → NORMAL → SUSPECT → SUSTAINED → REMINDED → RECOVERING → NORMAL
旁路: PAUSED（用户暂停）/ UNKNOWN（关键点不足，不判异常）
```

**报警条件（默认值，均为初值待实测标定，可在「智能提醒设置」页调整）**:

| 参数 | 默认 | 含义 |
|---|---|---|
| `deviation_threshold` | 2.0 | 进入阈值: 平滑后偏离量 ≥ 2.0 判"偏离" |
| `hysteresis_margin` | 0.3 | 退出阈值 = 2.0 − 0.3 = 1.7（滞回，防边界抖动） |
| `sustain_sec` | 30 秒 | 持续偏离 ≥ 30s 才算异常事件（短暂动作不报警） |
| `recover_sec` | 10 秒 | 持续正常 ≥ 10s 才解除 |
| `window_size` | 30 帧 | 滑动窗口平均，抹平单帧噪声 |
| `min_valid_ratio` | 0.5 | 有效率低于此 → 无法判断，永不报警 |
| 提醒冷却 | 300 秒 | 两次提醒最小间隔 |
| 延后时长 | 120 秒 | 点延后后安静多久 |

完整触发链: **单帧超 2.0 → 滑窗(30帧)平均后仍 ≥ 2.0 → 连续保持 30 秒 → 记异常事件 → 触发一次提醒（受 300s 冷却）**。校准后 2.0 的含义是"偏离个人正常坐姿 2 个标准差"。

### 4.6 算法实验室（评估框架）

三种判定方案同源对比: **A** 固定阈值单帧 / **B** 固定阈值连续 / **C** 个人基线连续（同一特征提取器、同一样本、同一标注，仅策略不同）。评估框架已实现: JSONL 标注读写（`annotations.py`）、事件级 IoU ≥ 0.3 + 起点容差 ±2s 的匹配规则（`evaluation.py`）、P/R/F1/FPR/每小时误报/检测延迟指标。

> 诚实声明: 当前**无标注数据集，未产生任何实验结果**，指标显示 `—`，不伪造。所有阈值默认值为初值，未经实测标定。

---

## 5. 项目结构

```
posturesense/
├── src/posturesense/
│   ├── vision/              # 视觉层
│   │   ├── camera_manager.py     # 摄像头生命周期（失败显式报错，不静默黑帧）
│   │   ├── pose_estimator.py     # MediaPipe Pose 33 点（visibility 透传）
│   │   ├── feature_extractor.py  # 姿态特征（缺失→None）
│   │   └── visualizer.py         # 骨架叠加
│   ├── core/                # 核心层（不依赖 Qt）
│   │   ├── inference_service.py  # 统一调度
│   │   ├── profiler.py           # 真实 FPS/延迟（perf_counter）
│   │   ├── baseline_manager.py   # 个人基线（校准/统计/z 偏差）
│   │   ├── temporal_analyzer.py  # 8 态状态机 + 滑窗 + 滞回
│   │   ├── reminder_engine.py    # 冷却/静音/延后/反馈
│   │   ├── storage.py            # SQLite（sessions/events/feedback/profiles 4 表）
│   │   ├── analytics.py          # 统计查询（空库空态）
│   │   ├── csv_export.py         # CSV 导出（UTF-8 BOM）
│   │   ├── strategies.py         # 方案 A/B/C + 绝对几何偏离量
│   │   ├── evaluation.py         # 事件 IoU 匹配 + P/R/F1
│   │   └── annotations.py        # JSONL 标注读写
│   ├── ui/                  # 界面层
│   │   ├── shell.py              # 主窗口 + 导航 + 业务接线
│   │   ├── pages.py              # 8 个页面
│   │   ├── theme.py              # 深色科技风样式
│   │   ├── widgets.py            # 共用控件
│   │   └── main_window.py        # 简版主窗口
│   └── app.py               # 入口（含 --smoke 冒烟自检）
├── tests/                   # 180 项自动化测试（16 文件）
├── models/                  # pose_landmarker_lite.task
├── packaging/
│   ├── posturesense.spec         # PyInstaller 配置（onedir）
│   ├── build.py                  # SHA-256 校验 + 构建
│   └── posturesense.iss          # Inno Setup 6.3+ 安装脚本（已实测）
├── NOTICE                   # 第三方组件许可清单（随包分发）
├── start_posturesense.bat   # 一键启动（源码环境）
├── dist/installer/          # 安装包产物（PostureSenseAI-Setup-0.1.0.exe；onedir 与 build/ 中间产物可从源码重建，不入库）
├── docs/                    # 竞赛答辩材料（审计/证据/讲稿/QA）+ capture_ui.py + build_pptx.py
├── output/                  # 答辩交付物（16 页 PPT、讲稿、证据清单、页面预览图）
└── pyproject.toml
```

第三方依赖许可（MediaPipe / OpenCV / PySide6 等）见 `NOTICE`。

用户数据: `%USERPROFILE%\PostureSenseAI\`（`posturesense.db` + `export/` + `smoke_result.txt`），可在「隐私与系统设置」页一键删除全部本地数据。
