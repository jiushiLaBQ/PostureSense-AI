# 智姿 AI 项目审计报告（竞赛 PPT 用）

审计日期：2026-10-20　审计对象：`E:\CODE\posture\posturesense\`　审计方式：逐文件阅读源码 + 运行测试 + 检查真实数据文件

---

## 1. 项目概况

| 项 | 实际情况 |
|---|---|
| 项目名称 | 智姿 AI (PostureSense AI) —— 人体工学智能感知与自适应辅助系统 |
| 平台 | Windows 10/11 桌面端（PySide6 / Qt 6.9.2），本地离线 |
| 代码规模 | `src/` 445 KB（约 20 个模块），`tests/` 548 KB（16 个测试文件） |
| 测试 | **180 项自动化测试，全部通过**（pytest 8.4.2，Python 3.13.9，约 4 秒） |
| 打包 | PyInstaller onedir + Inno Setup 安装包（已实测静默安装/卸载链） |
| 模型 | MediaPipe `pose_landmarker_lite.task`（5,777,746 字节，SHA-256 已校验并写入构建脚本） |
| 项目来源 | 独立项目代码库；视觉层使用 MediaPipe / OpenCV 公开库，无上游业务代码依赖 |

## 2. 架构（与代码逐一对应）

```
摄像头 cv2.read()                         vision/camera_manager.py
  → MediaPipe PoseLandmarker（33 点）      vision/pose_estimator.py
  → 5 个姿态特征（缺失 → None）            vision/feature_extractor.py
  → 滑窗 + 8 态状态机 + 滞回              core/temporal_analyzer.py
  → 提醒冷却 / 静音 / 延后 / 反馈          core/reminder_engine.py
  → SQLite 4 表落库                       core/storage.py
  → 统计查询 / CSV 导出                   core/analytics.py, core/csv_export.py
  → A/B/C 三策略对比评估框架              core/strategies.py, core/evaluation.py, core/annotations.py
GUI：8 页（ui/shell.py + ui/pages.py），推理在 QThread（ui/shell.py InferenceWorker）
```

核心层（`core/`、`vision/`）不依赖 Qt，可独立单测——已被 16 个测试文件证实。

## 3. 关键算法实现（代码核实）

### 3.1 姿态感知
- OpenCV 采集：`camera_manager.py`，buffer_size=1 降延迟，失败显式报错，不补黑帧/零帧。
- MediaPipe PoseLandmarker VIDEO 模式：33 个关键点，**visibility/presence 原样透传**，代码注释明确禁止硬编码置信度。
- 5 个特征（`feature_extractor.py`）：`head_forward_ratio`、`trunk_tilt_deg`、`shoulder_tilt_deg`、`head_lateral_offset`、`keypoint_valid_ratio`。
- 缺失语义：必要关键点 visibility < 0.5 → 该特征为 `None`，按特征独立判定（髋部出画时仅躯干倾角缺失）。**缺失 ≠ 异常**。
- 全部为二维图像坐标几何量，README 与代码注释均明示"非真实三维人体角度"。

### 3.2 个性化基线（已实现，效果待验证）
- `baseline_manager.py`：用户主动校准 ≥30 秒采样 → 过滤 None 帧 → mean/std/min/max/median → 落库；样本不足拒绝保存。
- 判定：`z_i = (x_i - μ_i) / (σ_i + ε)`，ε = 1e-3；σ < 0.02 的低方差特征改用绝对偏差归一化；综合偏离量 = 各特征 |z| 平均。
- 未校准时回退绝对几何偏离量（`_abs_geometry_deviation`，`strategies.py`），UI 明示"默认规则模式（未校准）"。
- **真实校准证据**：用户数据库中存在 1 条校准记录（59 个样本，head_forward_ratio 均值 -0.128 ± 0.025，shoulder_tilt 均值 2.03° ± 1.46）。

### 3.3 连续时间判断与提醒（已实现且有测试）
- 8 态状态机：INIT→NORMAL→SUSPECT→SUSTAINED→REMINDED→RECOVERING→NORMAL，旁路 PAUSED/UNKNOWN。
- 默认参数（`AnalyzerConfig`/`ReminderConfig` dataclass 默认值）：
  进入阈值 2.0、退出阈值 1.7（滞回 0.3）、滑窗 30 帧、持续 30 秒判异常、恢复 10 秒解除、有效率下限 0.5、提醒冷却 300 秒、延后 120 秒。
- 单帧超阈不报警；提醒在 SUSTAINED→REMINDED 跳变时触发一次；冷却/静音/延后/用户反馈闭环均有测试覆盖。
- **阈值默认值在 README 与 UI 中均标注"初值待实测标定"**。

### 3.4 数据与隐私
- SQLite 4 表：sessions / posture_events / user_feedback / calibration_profiles（schema_version 迁移，单事务）。
- 默认不存视频、不存图像、不做人脸识别；只存特征统计与事件元数据。
- 隐私页一键 `delete_user_data()`（有测试）；CSV 导出 UTF-8 BOM。
- 真实使用证据：用户库存在 1 条已完成会话（128.2 秒，100% 有效时长）。

### 3.5 算法实验室（框架已实现，无实验结果）
- 三策略同源对比：A 固定阈值单帧 / B 固定阈值连续 / C 个人基线连续（同一特征提取器、同一样本）。
- 事件级匹配：IoU ≥ 0.3 + 起点容差 ±2 s，贪心一对一；指标 P/R/F1/FPR/每小时误报/检测延迟（`evaluation.py`，17 项测试）。
- JSONL 标注读写（`annotations.py`，11 项测试）。
- **当前无标注数据集，未产生任何 P/R/F1 数字**——UI 实验室页与 README 均如实标注。

## 4. 工程与性能证据

| 证据 | 内容 | 来源 |
|---|---|---|
| 自动化测试 | 180 项全部通过（16 文件） | 本次审计实跑 `pytest tests/ -q`：180 passed in 3.99s |
| 冒烟自检 | 15 帧，FPS≈10.5，延迟≈131.8 ms（1280×720 默认参数，摄像头被遮挡 → 全部 LOW_VISIBILITY） | `%USERPROFILE%\PostureSenseAI\smoke_result.txt`（2026-10-19 实跑） |
| 开发期性能实测 | 640×480 下 30 FPS、单帧 31 ms（核显笔记本 CPU） | README §1（开发阶段实测记录，无原始日志文件留存） |
| 安装包 | PostureSenseAI-Setup-0.1.0.exe（约 180 MB），静默安装/卸载链已实测 | `dist/installer/` |
| 真实会话 | 128.2 s 完成会话 1 条；真实校准基线 1 条（59 样本） | `%USERPROFILE%\PostureSenseAI\posturesense.db` |

## 5. 功能状态分类（竞赛陈述必须遵守）

**A. 已实现且已验证**（代码 + 测试/运行证据）
摄像头采集、MediaPipe 33 点提取、5 特征计算、缺失语义（None 不伪造）、8 态状态机、滞回/持续时间判断、提醒冷却/静音/延后/反馈、SQLite 落库、历史回顾、数据分析（空库空态）、CSV 导出、一键删除数据、校准采样与保存流程、8 页 GUI、冒烟自检、安装包。

**B. 已实现但尚未充分验证**
个人基线判定的实际效果（代码与 15 项单测存在、有 1 条真实校准记录，但无标注数据验证其降低误报的效果）；A/B/C 评估框架（代码与 28 项测试存在，未跑过真实标注数据集）；默认阈值参数（初值，未经标定实验）。

**C. 正在优化**
提醒投递方式（当前为状态栏消息，桌面 toast/声音未实现）；默认参数的实测标定。

**D. 计划功能（代码中不存在）**
视频/图片文件输入、数据库加密、云端同步、多摄像头、医学级姿态评估。

## 6. 医学与宣传边界（README 与 UI 一致）

- 不提供医学诊断，不声称预防或治疗颈椎疾病。
- 二维图像几何量 ≠ 三维人体角度；摄像头角度/遮挡/光照影响结果。
- 关键点不足时显示"无法判断"，不强行输出异常标签。
