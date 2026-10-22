# PPT 素材清单与状态（11 页 = 封面 + 标准 8 大板块（板块 3 拆为内容/创新两页） + 致谢）

| 页 | 需要素材 | 状态 | 路径 / 说明 |
|---|---|---|---|
| 1 | 封面视觉主体 | ✅ 已有 | `docs/assets/ai/cover_art.png`（AI 生成装饰插画，页面已标注「非检测效果图」；fallback：`skeleton_demo.png`） |
| 2 | 板块1 背景与问题：三痛点卡 + 伏案插画 | ✅ 已有 | 卡片见 build 脚本；`docs/assets/ai/desk_scene_art.png`（AI 生成装饰插画，页面已标注「非产品界面」） |
| 3 | 板块2 目标与意义：目标卡 + 首页截图 | ✅ 已有 | `docs/assets/ui_01_home.png` |
| 4 | 板块3a 项目内容：链路条 + 算法卡 + 判定标准卡 + 骨架示意 | ✅ 已有 | 形状见 build 脚本；`docs/assets/skeleton_demo.png`（真实绘制代码输出，姿态为示意图） |
| 5 | 板块3b 创新点：四卡片 + 图标 ×4 | ✅ 已有 | 形状见 build 脚本；`ai/icon_baseline.png` / `icon_temporal.png` / `icon_offline.png` / `icon_device.png`（AI 生成装饰图标） |
| 6 | 板块4 实施过程：六步流程 + 两卡 + 工程插画 | ✅ 已有 | pptx 形状绘制；`ai/dev_process_art.png`（AI 生成装饰插画，页面已标注） |
| 7 | 板块5 成果数据：六指标卡 + 来源声明 | ✅ 已有 | 数字全部来自真实文件：`%USERPROFILE%\PostureSenseAI\smoke_result.txt`、`posturesense.db`、README、pytest |
| 8 | 板块6 社会效益：四价值卡 + 隐私页截图 | ✅ 已有 | `docs/assets/ui_08_privacy.png` |
| 9 | 板块7 未来规划：三栏卡 + 路线图插画 | ✅ 已有 | pptx 形状绘制；`ai/roadmap_art.png`（AI 生成装饰插画，页面已标注） |
| 10 | 板块8 总结：两栏卡 | ✅ 已有 | pptx 形状绘制 |
| 11 | 致谢页插画 + 占位符 | ✅ 已有 | `docs/assets/ai/closing_art.png`（AI 生成装饰插画，页面已标注）；学校/团队/导师/联系方式待用户填写 |

## 性能数据文件位置（第 7 页数据来源）

- 冒烟自检：`%USERPROFILE%\PostureSenseAI\smoke_result.txt`（FPS≈10.5 / 延迟≈131.8ms / 1280×720）
- 会话与校准库：`%USERPROFILE%\PostureSenseAI\posturesense.db`（sessions 表 128.2s 会话、calibration_profiles 表 59 样本）
- 开发期性能：README 记录（640×480 下 30 FPS、单帧 31ms）
- 测试：pytest 实跑（180 项，约 4 秒，可现场重跑）

## 建议补充（可选，需用户操作）

1. **摄像头实采人物骨架实拍图**：真机运行软件 → 开始监测 → 截图。当前封面 fallback 与第 2 页插画已如实标注为 AI 装饰图。
2. 学校名称、团队成员、指导教师、联系方式、答辩日期 → 填入第 1、11 页占位符。
3. 若补拍提醒触发瞬间（持续 30s 后状态栏提醒消息）→ 可加强第 7 页反馈维度。

## 重新生成截图

`python docs/capture_ui.py`（复制真实用户库到临时目录后离屏抓取，不触碰真实数据）。
