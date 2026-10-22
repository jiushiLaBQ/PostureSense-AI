# 智姿 AI 证据清单（PPT 素材与数据来源）

生成日期：2026-10-20。所有条目均可现场复核。

## 1. 真实截图（`docs/assets/`，2026-10-20 由 `docs/capture_ui.py` 离屏抓取真实 UI）

| 文件 | 内容 | 数据来源 |
|---|---|---|
| `ui_01_home.png` | 产品首页 | 真实 UI |
| `ui_02_monitor.png` | 实时姿态监测页（未启动空态，指标显示 `—`，"基线模式: 默认规则（未校准）"） | 真实 UI |
| `ui_03_calibration.png` | 个性化姿态校准页 | 真实 UI |
| `ui_04_reminders.png` | 智能提醒设置页（真实参数调节控件） | 真实 UI |
| `ui_05_history.png` | 会话记录与历史回顾页 | 真实 UI + 真实库 |
| `ui_06_analytics.png` | 数据分析中心（累计监测 2.1 min、有效 2.1 min、事件 0 —— 与真实数据库一致） | 真实 UI + 真实 SQLite 数据 |
| `ui_07_lab.png` | 算法测试实验室（明示"尚无实验结果，不填充虚构数字"） | 真实 UI |
| `ui_08_privacy.png` | 隐私与系统设置页 | 真实 UI |
| `skeleton_demo.png` | 骨架叠加效果（真实 `visualizer.draw_pose` 绘制；**姿态为合成示意，图上已标注 synthetic pose**） | 真实绘制代码 + 合成姿态 |

> 截图时摄像头未开启（离屏环境），监测页为空态——这本身佐证"未启动不伪造数据"。
> 现场答辩建议在真机上运行软件补充"摄像头实采 + 骨架叠加"实拍图（见 PPT_ASSET_LIST.md）。

## 2. 真实数据文件

| 文件 | 内容 | 关键数字 |
|---|---|---|
| `%USERPROFILE%\PostureSenseAI\posturesense.db` | 真实使用数据库 | sessions=1（128.2 s 完成会话，valid_ms=128216 即 100% 有效）；calibration_profiles=1；posture_events=0；user_feedback=0 |
| 同上 stats_json | 真实校准基线统计 | 59 样本；head_forward_ratio 均值 -0.128、std 0.025；shoulder_tilt_deg 均值 2.03°、std 1.46° |
| `%USERPROFILE%\PostureSenseAI\smoke_result.txt` | 冒烟自检结果（2026-10-19 实跑） | 15 帧；FPS≈10.5；延迟≈131.8 ms；状态分布 15/15 LOW_VISIBILITY（摄像头被遮挡，如实记录） |
| `dist/installer/PostureSenseAI-Setup-0.1.0.exe` | 安装包（约 180 MB） | 静默安装/卸载链已实测通过 |
| `models/pose_landmarker_lite.task` | 姿态模型 | 5,777,746 字节；SHA-256 = 59929e1d…574a（构建脚本强制校验） |

## 3. 测试证据

命令：`python -m pytest tests/ -q` → **180 passed in 3.99s**（2026-10-20 审计时实跑）。

| 测试文件 | 数量 | 覆盖对象 |
|---|---|---|
| test_storage.py | 19 | SQLite 4 表、迁移、删除用户数据 |
| test_evaluation.py | 17 | 事件 IoU 匹配、P/R/F1 计算 |
| test_baseline_manager.py | 15 | 校准采样、统计、z 偏差、样本不足拒绝 |
| test_reminder_engine.py | 15 | 冷却/静音/延后/反馈 |
| test_temporal_analyzer.py | 15 | 8 态状态机、滑窗、滞回 |
| test_camera_manager.py | 12 | 摄像头生命周期（假件） |
| test_feature_extractor.py | 12 | 5 特征几何、缺失→None |
| test_strategies.py | 12 | A/B/C 三策略 |
| test_annotations.py | 11 | JSONL 标注读写 |
| test_pose_estimator.py | 11 | 关键点透传、状态语义（假件） |
| test_analytics.py | 12 | 统计查询、空库空态 |
| test_inference_service.py | 8 | 推理调度 |
| test_csv_export.py | 7 | CSV 导出 |
| test_profiler.py | 5 | FPS/延迟计量 |
| test_ui_states.py | 5 | UI 状态切换 |
| test_visualizer.py | 4 | 骨架叠加绘制 |
| **合计** | **180** | |

注：摄像头/模型测试使用可控假件（`tests/conftest.py` 声明：假件只验证软件逻辑，不伪装成真实检测结果）。

## 4. 文档证据

| 文件 | 用途 |
|---|---|
| `README.md`（208 行，5 节） | 作品简介/安装/运行/算法结构/项目结构；阈值标注"初值待实测标定"；实验室"无标注数据集，未产生任何实验结果" |
| `NOTICE` | 11 项第三方运行时依赖许可清单（随安装包分发） |
| `pyproject.toml` | 依赖与入口声明（`python -m posturesense`） |

## 5. 缺口（PPT 不得伪造的部分）

- 无摄像头实采的人物骨架实拍图（需现场补拍）。
- 无标注数据集 → 无 P/R/F1/误报率实验数字。
- 无问卷/用户研究数据。
- 无第三方医学或工效学统计引用（本 PPT 不使用未证实的流行病数字）。
- 开发期 30 FPS@640×480 实测无原始日志留存，仅 README 记录（降一级可信度使用）。
