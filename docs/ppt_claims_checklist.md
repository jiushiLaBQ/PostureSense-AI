# 智姿 AI 竞赛陈述核对表（Claims Checklist）

每条 PPT 主张 ↔ 证据 ↔ 可信等级。等级：**A** 代码+测试/运行双重证据；**B** 代码存在但效果未验证；**C** 仅文档记录；**禁止** = 不得出现在 PPT。

| # | PPT 主张 | 证据来源 | 等级 |
|---|---|---|---|
| 1 | 通过摄像头实时提取 33 个人体关键点 | pose_estimator.py（MediaPipe PoseLandmarker）+ 11 项测试 | A |
| 2 | 计算头前倾/躯干倾角/肩倾角/头偏移/有效率 5 个特征 | feature_extractor.py + 12 项测试 | A |
| 3 | 关键点缺失时显示"无法判断"，绝不补假值 | feature_extractor.py 缺失→None；README §4.2；monitor 页空态截图 | A |
| 4 | 连续 30 秒偏离才判定异常事件（单帧不报警） | temporal_analyzer.py + 15 项测试；README §4.5 | A |
| 5 | 滞回阈值（进 2.0 / 出 1.7）防边界抖动 | temporal_analyzer.py AnalyzerConfig + 测试 | A |
| 6 | 提醒带 300s 冷却、120s 延后、静音与反馈闭环 | reminder_engine.py + 15 项测试 | A |
| 7 | 个人基线：30 秒校准，z 分数个性化判定 | baseline_manager.py + 15 项测试 + 真实校准记录（59 样本） | B（流程已验证；**降误报效果未验证**） |
| 8 | 未校准时明示"默认规则模式"，不伪装个性化 | shell.py / monitor 页截图"默认规则（未校准）" | A |
| 9 | 会话/事件/反馈/基线存本地 SQLite | storage.py + 19 项测试 + 真实库 1 会话 | A |
| 10 | 默认不保存视频与图像 | 全库无视频/图像字段（storage schema）；README §1 | A |
| 11 | 全程离线，核心检测不依赖云 API | 运行时依赖全为本地库（NOTICE）；无网络调用代码 | A |
| 12 | 一键删除全部本地数据 | storage.delete_user_data() + 测试 + privacy 页 | A |
| 13 | 180 项自动化测试全部通过 | 2026-10-20 实跑 180 passed | A |
| 14 | 冒烟自检：15 帧 FPS≈10.5 延迟≈131.8ms（1280×720） | smoke_result.txt（2026-10-19） | A（条件：摄像头遮挡、默认分辨率） |
| 15 | 开发期实测 640×480 下 30 FPS、单帧 31ms | README §1 记录，无原始日志 | C（PPT 须注明"开发期实测"） |
| 16 | 一键安装包，已实测安装/卸载 | dist/installer/*.exe | A |
| 17 | A/B/C 三策略对比评估框架（IoU 匹配 + P/R/F1） | strategies.py / evaluation.py + 29 项测试 | B（框架已验证；**未跑真实数据**） |
| 18 | 三档事件统计、跨会话趋势等数据分析 | analytics.py + 12 项测试 + analytics 页真实截图 | A |
| 19 | 阈值参数（2.0/30s/10s 等）为初值待标定 | README §4.5 明示 | A（诚实声明本身） |
| 20 | **个人基线可降低误报 X%** | 无实验数据 | **禁止** |
| 21 | **识别准确率 / F1 具体数字** | 无标注数据集 | **禁止** |
| 22 | **预防/治疗颈椎问题、医学诊断能力** | 越界声明（README 明确排除） | **禁止** |
| 23 | **久坐人群患病率等流行病学数字** | 无可靠来源引用 | **禁止**（除非补权威出处） |
| 24 | **用户量、试点单位、获奖** | 无 | **禁止** |
| 25 | **视频文件分析、数据库加密** | 代码未实现（只能列入未来规划） | **禁止作为现有能力** |
| 26 | **toast/声音提醒已可用** | 当前投递为状态栏消息 | **禁止**（列"优化中"） |

## 现场可复核操作

1. `cd posturesense && python -m pytest tests/ -q` → 180 passed
2. `type %USERPROFILE%\PostureSenseAI\smoke_result.txt` → 冒烟数字
3. 启动软件 → 校准页采集 30s → 数据库出现新 calibration_profiles 行
4. 数据分析中心数字与 SQLite 查询一致
