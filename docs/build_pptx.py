"""智姿 AI 竞赛答辩 PPT 生成器（11 页：封面 + 标准 8 大板块（板块 3 拆为内容/创新两页）+ 致谢，python-pptx）。

用法: python docs/build_pptx.py
输出: output/智姿AI_竞赛答辩PPT.pptx

板块结构:
  1 项目背景与问题（重点页）  2 项目目标与意义  3 项目内容与创新点
  4 实施过程与开展情况        5 成果数据与反馈  6 社会效益与推广价值
  7 未来规划                  8 总结

设计: 16:9，白/浅灰底 #F5F7FA，标题深蓝 #17365D，辅助青蓝 #00A6C7，正文 #253247，微软雅黑。
所有数据主张与 docs/ppt_claims_checklist.md 对齐；未验证项一律如实标注。
性能数据来源（全部真实可复核）: %USERPROFILE%\\PostureSenseAI\\smoke_result.txt、
posturesense.db、README 开发期实测记录、pytest 实跑。
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.enum.shapes import MSO_SHAPE
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ASSETS = PROJECT_ROOT / "docs" / "assets"
OUT_DIR = PROJECT_ROOT / "output"
OUT_PPTX = OUT_DIR / "智姿AI_竞赛答辩PPT.pptx"

DEEP = RGBColor.from_string("17365D")    # 深蓝主色
ACCENT = RGBColor.from_string("00A6C7")  # 青蓝辅助
BG = RGBColor.from_string("F5F7FA")      # 浅灰底
TEXT = RGBColor.from_string("253247")    # 深灰正文
WHITE = RGBColor.from_string("FFFFFF")
GREY = RGBColor.from_string("8A94A6")
LIGHT = RGBColor.from_string("E3E9F2")
DARKCARD = RGBColor.from_string("22314E")

FONT = "微软雅黑"

SW, SH = Inches(13.333), Inches(7.5)
MARGIN = Inches(0.55)


# ---------------------------------------------------------------- helpers
def set_run(run, size=14, bold=False, color=TEXT, italic=False):
    f = run.font
    f.name = FONT
    f.size = Pt(size)
    f.bold = bold
    f.italic = italic
    f.color.rgb = color
    rPr = run._r.get_or_add_rPr()
    ea = rPr.find(qn("a:ea"))
    if ea is None:
        ea = rPr.makeelement(qn("a:ea"), {})
        rPr.append(ea)
    ea.set("typeface", FONT)


def add_rect(slide, l, t, w, h, fill=WHITE, line=None, shape=MSO_SHAPE.RECTANGLE, line_w=None):
    sp = slide.shapes.add_shape(shape, l, t, w, h)
    sp.fill.solid()
    sp.fill.fore_color.rgb = fill
    if line is None:
        sp.line.fill.background()
    else:
        sp.line.color.rgb = line
        sp.line.width = line_w or Pt(1)
    sp.shadow.inherit = False
    return sp


def add_text(slide, l, t, w, h, lines, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP,
             space_after=4, wrap=True):
    """lines: list of (text, size, bold, color) 或 list of dict(runs=[...])。"""
    tb = slide.shapes.add_textbox(l, t, w, h)
    tf = tb.text_frame
    tf.word_wrap = wrap
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    for i, ln in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.space_after = Pt(space_after)
        if isinstance(ln, dict):
            for txt, size, bold, color in ln["runs"]:
                r = p.add_run()
                r.text = txt
                set_run(r, size, bold, color)
        else:
            txt, size, bold, color = ln
            r = p.add_run()
            r.text = txt
            set_run(r, size, bold, color)
    return tb


def base_slide(prs, title=None, subtitle=None, page_no=None):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    add_rect(slide, 0, 0, SW, SH, fill=BG)
    if title:
        add_text(slide, MARGIN, Inches(0.32), Inches(11.5), Inches(0.6),
                 [(title, 26, True, DEEP)])
        add_rect(slide, MARGIN, Inches(0.95), Inches(0.9), Pt(3.2), fill=ACCENT)
        if subtitle:
            add_text(slide, MARGIN, Inches(1.05), Inches(11.5), Inches(0.35),
                     [(subtitle, 12, False, GREY)])
    if page_no:
        add_text(slide, SW - Inches(0.9), SH - Inches(0.42), Inches(0.5), Inches(0.3),
                 [(str(page_no), 10, False, GREY)], align=PP_ALIGN.RIGHT)
    return slide


def add_picture_fit(slide, path, l, t, max_w, max_h, border=True):
    img = Image.open(path)
    iw, ih = img.size
    scale = min(max_w / iw, max_h / ih)
    w, h = int(iw * scale), int(ih * scale)
    left = l + int((max_w - w) / 2)
    top = t + int((max_h - h) / 2)
    pic = slide.shapes.add_picture(str(path), left, top, width=w, height=h)
    if border:
        pic.line.color.rgb = LIGHT
        pic.line.width = Pt(1)
    return pic


def add_table(slide, rows_data, l, t, w, h, col_widths=None, header=True,
              font_size=11, header_size=11):
    rows, cols = len(rows_data), len(rows_data[0])
    gt = slide.shapes.add_table(rows, cols, l, t, w, h).table
    if col_widths:
        total = sum(col_widths)
        for i, cw in enumerate(col_widths):
            gt.columns[i].width = Emu(int(w * cw / total))
    for ri, row in enumerate(rows_data):
        for ci, val in enumerate(row):
            cell = gt.cell(ri, ci)
            cell.margin_left = cell.margin_right = Inches(0.06)
            cell.margin_top = cell.margin_bottom = Inches(0.02)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            tf = cell.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            r = p.add_run()
            r.text = str(val)
            if header and ri == 0:
                set_run(r, header_size, True, WHITE)
                cell.fill.solid()
                cell.fill.fore_color.rgb = DEEP
            else:
                set_run(r, font_size, False, TEXT)
                cell.fill.solid()
                cell.fill.fore_color.rgb = WHITE if ri % 2 else RGBColor.from_string("EFF3F9")
    return gt


def add_notes(slide, text):
    slide.notes_slide.notes_text_frame.text = text


def chip(slide, l, t, text, fill=ACCENT, w=Inches(1.15)):
    sp = add_rect(slide, l, t, w, Inches(0.28), fill=fill, shape=MSO_SHAPE.ROUNDED_RECTANGLE)
    tf = sp.text_frame
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.word_wrap = False
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = text
    set_run(r, 10, True, WHITE)
    return sp


# ---------------------------------------------------------------- slides
def s01_cover(prs):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    add_rect(slide, 0, 0, SW, SH, fill=BG)
    add_rect(slide, 0, 0, Inches(0.18), SH, fill=DEEP)
    add_text(slide, Inches(0.9), Inches(1.5), Inches(7.2), Inches(1.2),
             [("智姿 AI", 60, True, DEEP)])
    add_text(slide, Inches(0.9), Inches(2.75), Inches(7.2), Inches(0.6),
             [("人体工学智能感知与自适应辅助系统", 24, True, TEXT)])
    add_text(slide, Inches(0.9), Inches(3.35), Inches(7.2), Inches(0.45),
             [("PostureSense AI · 千坐千面的离线坐姿守护者", 15, False, ACCENT)])
    add_rect(slide, Inches(0.9), Inches(4.05), Inches(2.2), Pt(2.5), fill=ACCENT)
    add_text(slide, Inches(0.9), Inches(4.5), Inches(7.0), Inches(1.8), [
        ("参赛项目", 13, True, DEEP),
        ("学校：【待填写】　团队：【待填写】", 12, False, TEXT),
        ("指导教师：【待填写】", 12, False, TEXT),
        ("答辩日期：【待填写】", 12, False, TEXT),
    ], space_after=8)
    cover_art = ASSETS / "ai" / "cover_art.png"
    add_picture_fit(slide, cover_art if cover_art.exists() else ASSETS / "skeleton_demo.png",
                    Inches(8.3), Inches(1.5), Inches(4.4), Inches(3.9))
    add_text(slide, Inches(8.3), Inches(5.5), Inches(4.4), Inches(0.3),
             [("封面插画（AI 生成装饰图，非检测效果图）" if cover_art.exists()
               else "骨架叠加效果（真实绘制代码，姿态为示意图）", 10, False, GREY)],
             align=PP_ALIGN.CENTER)
    add_text(slide, Inches(0.9), Inches(6.8), Inches(11.8), Inches(0.4),
             [("本地离线 · 不提供医学诊断 · 所有性能数据均可现场复核", 11, False, GREY)])
    add_notes(slide, "15 秒：项目一句话定位——普通摄像头、本地离线、持续偏离才提醒。")


def s02_background(prs):
    """板块 1（重点页）：项目背景与问题。"""
    slide = base_slide(prs, "1  项目背景与问题：坐姿这件小事，人人都知道，却没人时时刻刻提醒", page_no=2)
    add_rect(slide, MARGIN, Inches(1.42), Inches(12.2), Inches(1.02), fill=DARKCARD,
             shape=MSO_SHAPE.ROUNDED_RECTANGLE)
    add_text(slide, MARGIN + Inches(0.3), Inches(1.56), Inches(11.6), Inches(0.76), [
        ("团队成员长期伏案学习与写代码，颈肩腰背的疲惫酸痛渐成常态——这正是我们自己的日常。",
         13.5, True, WHITE),
        ("「坐姿」这件小事人人都知道，却没人时时刻刻提醒。而市面上的现有方案，各有痛点：",
         12, False, LIGHT),
    ], space_after=5)
    cards = [
        ("硬件依赖类",
         "手机支架、专用监测设备需要额外购买硬件，携带与部署都不方便，成本门槛拦住了大多数人。",
         "→ 需求：零外设，普通摄像头即可"),
        ("云端识别类 App",
         "摄像头画面要上传服务器才能识别，而画面里是最私密的家庭与办公场景，隐私令人顾虑。",
         "→ 需求：画面不出本机，全程离线"),
        ("通用角度阈值类",
         "固定阈值对高矮胖瘦不同的人一刀切，也扛不住机位差异，误报频出、提醒最终被无视。",
         "→ 需求：因人而异的判断基准"),
    ]
    desk_art = ASSETS / "ai" / "desk_scene_art.png"
    art_w = Inches(3.9) if desk_art.exists() else Inches(0)
    card_w = Inches(8.0) if desk_art.exists() else Inches(12.2)
    if desk_art.exists():
        y = Inches(2.72)
        for title, body, need in cards:
            add_rect(slide, MARGIN, y, card_w, Inches(1.28), fill=WHITE,
                     shape=MSO_SHAPE.ROUNDED_RECTANGLE)
            add_rect(slide, MARGIN, y, Inches(0.08), Inches(1.28), fill=ACCENT)
            add_text(slide, MARGIN + Inches(0.3), y + Inches(0.12), Inches(2.3), Inches(0.4),
                     [(title, 14, True, DEEP)])
            add_text(slide, MARGIN + Inches(2.75), y + Inches(0.12), Inches(5.05), Inches(0.75),
                     [(body, 10.5, False, TEXT)], space_after=2)
            add_text(slide, MARGIN + Inches(2.75), y + Inches(0.9), Inches(5.05), Inches(0.32),
                     [(need, 11.5, True, ACCENT)])
            y += Inches(1.39)
        add_picture_fit(slide, desk_art, Inches(8.75), Inches(2.72), art_w, Inches(3.9))
        add_text(slide, Inches(8.75), Inches(6.68), art_w, Inches(0.3),
                 [("AI 生成插画（装饰，非产品界面）", 10, False, GREY)],
                 align=PP_ALIGN.CENTER)
    else:
        y = Inches(2.72)
        for title, body, need in cards:
            add_rect(slide, MARGIN, y, card_w, Inches(1.28), fill=WHITE,
                     shape=MSO_SHAPE.ROUNDED_RECTANGLE)
            add_rect(slide, MARGIN, y, Inches(0.08), Inches(1.28), fill=ACCENT)
            add_text(slide, MARGIN + Inches(0.3), y + Inches(0.12), Inches(2.3), Inches(0.4),
                     [(title, 14, True, DEEP)])
            add_text(slide, MARGIN + Inches(2.75), y + Inches(0.12), Inches(9.2), Inches(0.75),
                     [(body, 10.5, False, TEXT)], space_after=2)
            add_text(slide, MARGIN + Inches(2.75), y + Inches(0.9), Inches(9.2), Inches(0.32),
                     [(need, 11.5, True, ACCENT)])
            y += Inches(1.39)
    add_text(slide, MARGIN, Inches(7.0), Inches(12.2), Inches(0.38),
             [("目标用户：日常电脑办公与学习人群。定位为姿态观察辅助，不提供医学诊断、不声称预防疾病。",
               11, False, GREY)])
    add_notes(slide, "重点页 40 秒：从自己团队的伏案日常讲起，引出三类现有方案痛点与对应需求；不引用无来源数字。")


def s03_goal(prs):
    """板块 2：项目目标与意义。"""
    slide = base_slide(prs, "2  项目目标与意义：把持续观察交给软件，把数据留在本地", page_no=3)
    add_rect(slide, MARGIN, Inches(1.42), Inches(6.7), Inches(1.5), fill=DARKCARD,
             shape=MSO_SHAPE.ROUNDED_RECTANGLE)
    add_text(slide, MARGIN + Inches(0.28), Inches(1.6), Inches(6.15), Inches(1.2), [
        ("总目标", 13, True, ACCENT),
        ("做一个本地离线的坐姿观察助手：持续偏离才提醒、"
         "判断基准因人而异、过程可回顾可复核。", 13, True, WHITE),
    ], space_after=6)
    add_text(slide, MARGIN, Inches(3.15), Inches(6.7), Inches(0.35),
             [("三个具体目标（均已实现）", 13.5, True, DEEP)])
    goals = [
        ("可感知", "摄像头 + 33 关键点实时呈现姿态状态"),
        ("可分析", "滑窗 + 状态机做连续判断，过滤短暂动作"),
        ("可回顾", "会话落库 SQLite，统计与 CSV 导出"),
    ]
    y = Inches(3.6)
    for t, d in goals:
        add_rect(slide, MARGIN, y, Inches(6.7), Inches(0.72), fill=WHITE,
                 shape=MSO_SHAPE.ROUNDED_RECTANGLE)
        add_rect(slide, MARGIN, y, Inches(0.08), Inches(0.72), fill=ACCENT)
        add_text(slide, MARGIN + Inches(0.25), y + Inches(0.08), Inches(1.3), Inches(0.35),
                 [(t, 12.5, True, DEEP)])
        add_text(slide, MARGIN + Inches(1.6), y + Inches(0.1), Inches(5.0), Inches(0.35),
                 [(d, 11.5, False, TEXT)])
        y += Inches(0.84)
    add_text(slide, MARGIN, Inches(6.35), Inches(6.7), Inches(0.9), [
        ("意义：健康自我观察的辅助工具 · 数据完全自持 ·", 11, False, GREY),
        ("一套可测试、可复核的 AI 工程实践范例", 11, False, GREY),
    ], space_after=3)
    add_picture_fit(slide, ASSETS / "ui_01_home.png",
                    Inches(7.55), Inches(1.42), Inches(5.2), Inches(4.9))
    add_text(slide, Inches(7.55), Inches(6.4), Inches(5.2), Inches(0.3),
             [("真实运行界面：产品首页", 10, False, GREY)], align=PP_ALIGN.CENTER)
    add_notes(slide, "25 秒：总目标一句话 + 三个具体目标；右侧配真实首页截图。")


def s04_content(prs):
    """板块 3a：项目内容（流程 · 算法参考 · 判定标准）。"""
    slide = base_slide(prs, "3  项目内容：感知流程 · 核心算法 · 判定标准", page_no=4)
    add_rect(slide, MARGIN, Inches(1.4), Inches(12.2), Inches(0.62), fill=DARKCARD,
             shape=MSO_SHAPE.ROUNDED_RECTANGLE)
    add_text(slide, MARGIN + Inches(0.25), Inches(1.5), Inches(11.8), Inches(0.42),
             [("摄像头采集 → 33 关键点 → 5 个姿态特征 → 8 态状态机连续判断 → 提醒管理 → SQLite 记录回顾",
               13, True, WHITE)], align=PP_ALIGN.CENTER)
    # 左：算法参考
    add_rect(slide, MARGIN, Inches(2.3), Inches(4.55), Inches(4.5), fill=WHITE,
             shape=MSO_SHAPE.ROUNDED_RECTANGLE)
    add_rect(slide, MARGIN, Inches(2.3), Inches(0.08), Inches(4.5), fill=ACCENT)
    add_text(slide, MARGIN + Inches(0.26), Inches(2.48), Inches(4.1), Inches(4.2), [
        ("算法参考（均为公开模型与真实代码）", 13, True, DEEP),
        ("· OpenCV：摄像头采集，缓冲=1 降延迟，失败显式报错不补黑帧", 10.5, False, TEXT),
        ("· MediaPipe PoseLandmarker：33 个关键点 + visibility 透传（Google 公开模型）", 10.5, False, TEXT),
        ("· 5 个二维几何特征：头前倾比 / 躯干倾角 / 肩部倾角 / 头部偏移 / 关键点有效率", 10.5, False, TEXT),
        ("· 时序：30 帧滑窗 + 8 态状态机 + 滞回（进 2.0 / 出 1.7）", 10.5, False, TEXT),
        ("· 存储：SQLite 四表落库，CSV 导出", 10.5, False, TEXT),
    ], space_after=9)
    # 中：判定标准（深色卡）
    add_rect(slide, Inches(5.3), Inches(2.3), Inches(4.15), Inches(4.5), fill=DARKCARD,
             shape=MSO_SHAPE.ROUNDED_RECTANGLE)
    add_text(slide, Inches(5.56), Inches(2.48), Inches(3.65), Inches(4.2), [
        ("怎么算「坐姿有问题」？", 13, True, ACCENT),
        ("未校准（默认规则）：", 11, True, WHITE),
        ("躯干前倾 >10°、肩部倾角 >5°、头部明显前移 → 折算综合偏离量，平滑后 ≥ 2.0 判「偏离」", 10, False, LIGHT),
        ("已校准（个人基线）：", 11, True, WHITE),
        ("各特征偏离个人基线的 z 分数均值 ≥ 2.0，约等于偏离自己的端正坐姿 2 个标准差", 10, False, LIGHT),
        ("时序把关：", 11, True, WHITE),
        ("连续偏离 30 秒才记异常事件并提醒一次；< 1.7 恢复；关键点不足 =「无法判断」，永不报警", 10, False, LIGHT),
    ], space_after=8)
    # 右：骨架图
    add_picture_fit(slide, ASSETS / "skeleton_demo.png",
                    Inches(9.65), Inches(2.3), Inches(3.1), Inches(3.6))
    add_text(slide, Inches(9.65), Inches(5.95), Inches(3.1), Inches(0.6),
             [("骨架叠加效果（真实绘制代码，姿态为示意图）", 9.5, False, GREY)],
             align=PP_ALIGN.CENTER)
    add_notes(slide, "35 秒：链路一句话；左卡算法参考；中卡讲清判定标准——>10°/>5°/前移或 2 个标准差；右为真实骨架绘制。")


def s05_innovation(prs):
    """板块 3b：项目创新点（四方向）。"""
    slide = base_slide(prs, "3  项目创新点：千人千面 · 时序智能 · 全程离线 · 零外设", page_no=5)
    cards = [
        ("① 千人千面", "icon_baseline.png",
         "首次使用 30 秒校准个人基线，按「你自己」的端正姿态判断偏差，而非一刀切的通用角度阈值，适配不同身高体态与坐习惯。"),
        ("② 时序智能", "icon_temporal.png",
         "内置 8 状态时序状态机与滞后判决，短暂动作不误报，持续低头/驼背伏案才触发；提醒带冷却、静音、贪睡与反馈闭环，打扰可控。"),
        ("③ 全程离线", "icon_offline.png",
         "画面即时处理、不留存不上传，记录存于本地 SQLite，隐私页一键删除；断网可用，核心检测不依赖任何云 API。"),
        ("④ 无外置设备依赖", "icon_device.png",
         "普通笔记本内置或 USB 摄像头即可运行，无需支架、穿戴设备等任何额外硬件，零部署成本。"),
    ]
    positions = [(0.55, 1.5), (6.85, 1.5), (0.55, 4.3), (6.85, 4.3)]
    for (title, icon, body), (x, y) in zip(cards, positions):
        add_rect(slide, Inches(x), Inches(y), Inches(6.0), Inches(2.55), fill=BG,
                 line=LIGHT, shape=MSO_SHAPE.ROUNDED_RECTANGLE)
        add_rect(slide, Inches(x), Inches(y), Inches(0.08), Inches(2.55), fill=ACCENT)
        icon_path = ASSETS / "ai" / icon
        tx = Inches(x + 0.3)
        if icon_path.exists():
            add_picture_fit(slide, icon_path, Inches(x + 0.3), Inches(y + 0.7),
                            Inches(1.15), Inches(1.15), border=False)
            tx = Inches(x + 1.65)
        add_text(slide, tx, Inches(y + 0.28), Inches(6.0) - (tx - Inches(x)) - Inches(0.25),
                 Inches(0.45), [(title, 14.5, True, DEEP)])
        add_text(slide, tx, Inches(y + 0.82), Inches(6.0) - (tx - Inches(x)) - Inches(0.25),
                 Inches(1.6), [(body, 10.5, False, TEXT)], space_after=4)
    add_text(slide, MARGIN, Inches(7.0), Inches(12.2), Inches(0.35),
             [("复用声明：关键点模型为 MediaPipe 公开模型（NOTICE 列明许可）；创新点在模型之上的基线、时序与隐私体系。",
               10, False, GREY)])
    add_notes(slide, "30 秒：四条创新逐卡讲；强调「按你自己判断」「持续才算」「画面不出本机」「零外设」。")


def s06_process(prs):
    """板块 4：实施过程与开展情况。"""
    slide = base_slide(prs, "4  实施过程与开展情况", page_no=6)
    steps = [
        ("需求分析", "四类痛点\n逐条对应需求"),
        ("架构设计", "四层架构\n核心层不依赖 Qt"),
        ("核心实现", "关键点/特征/\n状态机/基线"),
        ("界面开发", "8 页桌面产品\n空态即红线"),
        ("自动化测试", "16 文件\n180 项全通过"),
        ("冒烟与打包", "真实摄像头自检\n一键安装包"),
    ]
    n = len(steps)
    box_w, gap = Inches(1.85), Inches(0.22)
    total = n * box_w + (n - 1) * gap
    x0 = int((SW - total) / 2)
    y = Inches(1.55)
    for i, (t, d) in enumerate(steps):
        x = x0 + i * (box_w + gap)
        add_rect(slide, x, y, box_w, Inches(1.62), fill=WHITE,
                 shape=MSO_SHAPE.ROUNDED_RECTANGLE)
        add_rect(slide, x, y, box_w, Inches(0.12), fill=ACCENT if i >= 4 else DEEP)
        add_text(slide, x + Inches(0.05), y + Inches(0.2), box_w - Inches(0.1), Inches(0.45),
                 [(f"{i+1}. {t}", 12.5, True, DEEP)], align=PP_ALIGN.CENTER)
        add_text(slide, x + Inches(0.05), y + Inches(0.72), box_w - Inches(0.1), Inches(0.85),
                 [(line, 9.5, False, GREY) for line in d.split("\n")],
                 align=PP_ALIGN.CENTER, space_after=2)
        if i < n - 1:
            add_rect(slide, x + box_w + Inches(0.02), y + Inches(0.74), Inches(0.16),
                     Inches(0.15), fill=ACCENT, shape=MSO_SHAPE.RIGHT_ARROW)
    dev_art = ASSETS / "ai" / "dev_process_art.png"
    cw = Inches(4.4) if dev_art.exists() else Inches(6.0)
    cx2 = Inches(5.15) if dev_art.exists() else Inches(6.85)
    cw2 = Inches(4.4) if dev_art.exists() else Inches(5.9)
    add_rect(slide, MARGIN, Inches(3.75), cw, Inches(3.0), fill=WHITE,
             shape=MSO_SHAPE.ROUNDED_RECTANGLE)
    add_text(slide, MARGIN + Inches(0.28), Inches(3.95), cw - Inches(0.55), Inches(2.6), [
        ("工程方法", 13.5, True, DEEP),
        ("· 每一级可独立测试；任一级失败显式报错，不静默补假数据", 11, False, TEXT),
        ("· 「无法判断」是正式状态：关键点质量不足时明说不知道", 11, False, TEXT),
        ("· 模型文件 SHA-256 校验后打包，版本可追溯", 11, False, TEXT),
    ], space_after=8)
    add_rect(slide, cx2, Inches(3.75), cw2, Inches(3.0), fill=WHITE,
             shape=MSO_SHAPE.ROUNDED_RECTANGLE)
    add_text(slide, cx2 + Inches(0.28), Inches(3.95), cw2 - Inches(0.55), Inches(2.6), [
        ("当前开展状态", 13.5, True, DEEP),
        ("· 八页桌面产品完整可用（含真实会话记录留痕）", 11, False, TEXT),
        ("· 个性化基线校准已实现，效果待标注数据验证", 11, False, TEXT),
        ("· A/B/C 评估框架就绪，等待标注数据即可产出指标", 11, False, TEXT),
    ], space_after=8)
    if dev_art.exists():
        add_picture_fit(slide, dev_art, Inches(9.75), Inches(3.75), Inches(3.0), Inches(2.55),
                        border=False)
        add_text(slide, Inches(9.75), Inches(6.38), Inches(3.0), Inches(0.3),
                 [("AI 生成插画（装饰）", 9.5, False, GREY)], align=PP_ALIGN.CENTER)
    add_notes(slide, "30 秒：六步实施过程从左到右讲；左卡讲工程红线，右卡讲当前状态（含未验证项）。")


def s07_results(prs):
    """板块 5：成果数据与反馈（性能验证数据集中在此页）。"""
    slide = base_slide(prs, "5  成果数据与反馈：所有数字均可现场复核", page_no=7)
    metrics = [
        ("180 项", "自动化测试全部通过", "16 个测试文件 · 约 4 秒 · 可现场重跑"),
        ("30 FPS", "开发期实测性能", "核显 CPU · 640×480 · 单帧 31ms（README 记录）"),
        ("FPS≈10.5", "冒烟自检（真实摄像头）", "1280×720 · 延迟≈131.8ms · 结果文件留痕"),
        ("128.2 秒", "真实会话记录", "SQLite sessions 表 · 有效检测占比 100%"),
        ("59 帧", "个性化校准样本", "全部通过质量过滤 · 统计量已入库"),
        ("8 页", "桌面产品完整可用", "含一键安装包（已实测）"),
    ]
    x0, y0 = MARGIN, Inches(1.5)
    card_w, card_h = Inches(3.95), Inches(1.98)
    for i, (num, label, sub) in enumerate(metrics):
        x = x0 + (i % 3) * Inches(4.155)
        y = y0 + (i // 3) * (card_h + Inches(0.22))
        add_rect(slide, x, y, card_w, card_h, fill=WHITE,
                 shape=MSO_SHAPE.ROUNDED_RECTANGLE)
        add_rect(slide, x, y, Inches(0.08), card_h, fill=ACCENT)
        add_text(slide, x + Inches(0.28), y + Inches(0.16), Inches(3.5), Inches(0.55),
                 [(num, 24, True, DEEP)])
        add_text(slide, x + Inches(0.28), y + Inches(0.82), Inches(3.5), Inches(0.4),
                 [(label, 12.5, True, TEXT)])
        add_text(slide, x + Inches(0.28), y + Inches(1.24), Inches(3.5), Inches(0.6),
                 [(sub, 10, False, GREY)], space_after=2)
    add_rect(slide, MARGIN, Inches(6.0), Inches(12.2), Inches(1.05), fill=DARKCARD,
             shape=MSO_SHAPE.ROUNDED_RECTANGLE)
    add_text(slide, MARGIN + Inches(0.28), Inches(6.14), Inches(11.7), Inches(0.8), [
        ("数据来源：smoke_result.txt（冒烟自检）· posturesense.db（会话/校准）· README 记录 · pytest 实跑，均可现场复核。",
         11.5, True, WHITE),
        ("诚实声明：暂无标注数据，算法效果的 P/R/F1 指标暂缺 —— 不编造数字（评估框架已就绪）。",
         10.5, False, LIGHT),
    ], space_after=4)
    add_notes(slide, "45 秒：六个数字逐个点名来源；性能=冒烟自检+开发期实测两组，场景不同如实分开。")


def s08_value(prs):
    """板块 6：社会效益与推广价值。"""
    slide = base_slide(prs, "6  社会效益与推广价值", page_no=8)
    items = [
        ("健康价值", "让久坐人群看见自己的姿态变化，形成自我观察习惯；边界清晰：自我观察辅助，非医疗诊断"),
        ("隐私价值", "全程本地离线、默认不存视频图像、一键删除本地数据（删除动作有自动化测试）"),
        ("推广价值", "普通摄像头 + 普通 Windows 电脑即可运行，无需专用硬件与云端；一键安装包已实测"),
        ("工程示范", "可测试、可复核、数据不造假的 AI 工程范式；180 项测试与留痕文件可现场验证"),
    ]
    y = Inches(1.5)
    for t, d in items:
        add_rect(slide, MARGIN, y, Inches(6.7), Inches(1.18), fill=WHITE,
                 shape=MSO_SHAPE.ROUNDED_RECTANGLE)
        add_rect(slide, MARGIN, y, Inches(0.08), Inches(1.18), fill=ACCENT)
        add_text(slide, MARGIN + Inches(0.28), y + Inches(0.12), Inches(6.1), Inches(0.4),
                 [(t, 13, True, DEEP)])
        add_text(slide, MARGIN + Inches(0.28), y + Inches(0.52), Inches(6.1), Inches(0.6),
                 [(d, 10.5, False, TEXT)], space_after=2)
        y += Inches(1.3)
    add_picture_fit(slide, ASSETS / "ui_08_privacy.png",
                    Inches(7.55), Inches(1.5), Inches(5.2), Inches(4.7))
    add_text(slide, Inches(7.55), Inches(6.27), Inches(5.2), Inches(0.3),
             [("真实界面：隐私与系统设置页", 10, False, GREY)], align=PP_ALIGN.CENTER)
    add_notes(slide, "25 秒：四个价值各一句话；隐私用真实设置页佐证；重申非医疗边界。")


def s09_future(prs):
    """板块 7：未来规划。"""
    slide = base_slide(prs, "7  未来规划：从可运行原型走向可验证产品", page_no=9)
    cols = [
        ("数据与验证", DEEP, [
            "采集标注数据，跑 A/B/C 三策略同源对比",
            "产出真实 P/R/F1 与误报率，反哺阈值标定",
            "关键点质量与事件识别指标分开报告",
        ]),
        ("产品体验", ACCENT, [
            "丰富提醒投递（toast / 声音）",
            "支持视频 / 图片文件输入",
            "个性化校准流程与引导优化",
        ]),
        ("部署与鲁棒性", DEEP, [
            "不同机位与光照条件的鲁棒性验证",
            "优化安装部署与使用引导",
            "扩大场景试用并收集真实反馈",
        ]),
    ]
    road_art = ASSETS / "ai" / "roadmap_art.png"
    cw = Inches(2.9) if road_art.exists() else Inches(3.95)
    cstep = Inches(3.1) if road_art.exists() else Inches(4.12)
    x = MARGIN
    for title, color, items in cols:
        add_rect(slide, x, Inches(1.55), cw, Inches(4.6), fill=WHITE,
                 shape=MSO_SHAPE.ROUNDED_RECTANGLE)
        add_rect(slide, x, Inches(1.55), cw, Inches(0.62), fill=color)
        add_text(slide, x, Inches(1.66), cw, Inches(0.42),
                 [(title, 14, True, WHITE)], align=PP_ALIGN.CENTER)
        add_text(slide, x + Inches(0.28), Inches(2.45), cw - Inches(0.53), Inches(3.5),
                 [("→ " + it, 11, False, TEXT) for it in items], space_after=14)
        x += cstep
    if road_art.exists():
        add_picture_fit(slide, road_art, Inches(9.85), Inches(1.55), Inches(2.9), Inches(4.6),
                        border=False)
        add_text(slide, Inches(9.85), Inches(6.2), Inches(2.9), Inches(0.3),
                 [("AI 生成插画（装饰）", 9.5, False, GREY)], align=PP_ALIGN.CENTER)
    add_text(slide, MARGIN, Inches(6.6), Inches(12.2), Inches(0.4),
             [("以上全部为未来工作，与已实现成果分开呈现；优先级最高的是标注数据采集与 A/B/C 验证。",
               11, False, GREY)])
    add_notes(slide, "25 秒：三条线并行；强调第一优先级是标注数据——它是所有效果指标的前提。")


def s10_summary(prs):
    """板块 8：总结。"""
    slide = base_slide(prs, "8  总结：真实、离线、可复核", page_no=10)
    add_rect(slide, MARGIN, Inches(1.5), Inches(6.0), Inches(5.2), fill=WHITE,
             shape=MSO_SHAPE.ROUNDED_RECTANGLE)
    add_rect(slide, MARGIN, Inches(1.5), Inches(6.0), Inches(0.55), fill=DEEP)
    add_text(slide, MARGIN, Inches(1.61), Inches(6.0), Inches(0.4),
             [("已做到（均有证据，可现场复核）", 14, True, WHITE)], align=PP_ALIGN.CENTER)
    done = [
        "八页桌面产品完整可用",
        "33 关键点 → 5 特征 → 8 态状态机 → 提醒管理",
        "个人基线校准已实现（效果待验证）",
        "180 项自动化测试全部通过",
        "冒烟自检与真实会话数据留痕",
        "一键安装包（已实测）",
    ]
    add_text(slide, MARGIN + Inches(0.3), Inches(2.25), Inches(5.4), Inches(4.2),
             [("✓ " + d, 12.5, False, TEXT) for d in done], space_after=13)
    add_rect(slide, Inches(6.85), Inches(1.5), Inches(5.9), Inches(5.2), fill=DARKCARD,
             shape=MSO_SHAPE.ROUNDED_RECTANGLE)
    add_text(slide, Inches(7.15), Inches(1.85), Inches(5.3), Inches(4.6), [
        ("一句话总结", 13, True, ACCENT),
        ("智姿 AI 把「持续观察 + 个性基线 + 连续判断」做成了"
         "普通人可用的离线桌面产品。", 13.5, True, WHITE),
        ("", 8, False, WHITE),
        ("三条原则", 13, True, ACCENT),
        ("· 用真实数据说话：性能有留痕，效果指标缺数据就不报", 12, False, WHITE),
        ("· 本地离线：摄像头数据不出本机", 12, False, WHITE),
        ("· 判断可解释：特征、阈值、状态全部摊开给用户", 12, False, WHITE),
    ], space_after=10)
    add_notes(slide, "25 秒：左栏只放有证据的成果；右栏三原则收束全场价值观。")


def s11_thanks(prs):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    add_rect(slide, 0, 0, SW, SH, fill=DEEP)
    closing_art = ASSETS / "ai" / "closing_art.png"
    if closing_art.exists():
        add_picture_fit(slide, closing_art, Inches(8.35), Inches(1.3),
                        Inches(4.35), Inches(4.35), border=False)
        tx_l, tx_w, tx_align = Inches(0.9), Inches(7.0), PP_ALIGN.LEFT
        bar_l = Inches(0.9)
    else:
        tx_l, tx_w, tx_align = Inches(1.5), Inches(10.3), PP_ALIGN.CENTER
        bar_l = int((SW - Inches(2.2)) / 2)
    add_rect(slide, bar_l, Inches(3.02), Inches(2.2), Pt(3), fill=ACCENT)
    add_text(slide, tx_l, Inches(2.0), tx_w, Inches(0.9),
             [("让姿态感知更直观，让辅助反馈更有依据",
               26 if closing_art.exists() else 30, True, WHITE)],
             align=tx_align)
    add_text(slide, tx_l, Inches(3.35), tx_w, Inches(0.6),
             [("感谢聆听，欢迎交流", 22, True, ACCENT)], align=tx_align)
    add_text(slide, tx_l, Inches(4.6), tx_w, Inches(1.6), [
        ("团队成员：【待填写】　分工：【待填写】", 13, False, LIGHT),
        ("指导教师：【待填写】", 13, False, LIGHT),
        ("联系方式：【待填写】", 13, False, LIGHT),
        ("项目：智姿 AI（PostureSense AI） · 本地离线 · 数据可复核", 11, False, GREY),
    ], align=tx_align, space_after=10)
    if closing_art.exists():
        add_text(slide, Inches(8.35), Inches(5.7), Inches(4.35), Inches(0.3),
                 [("AI 生成插画（装饰，非检测效果图）", 9.5, False, GREY)],
                 align=PP_ALIGN.CENTER)
    add_notes(slide, "10 秒：致谢 + 邀请提问。准备好讲稿附录的现场演示备查步骤。")


def main() -> None:
    prs = Presentation()
    prs.slide_width = SW
    prs.slide_height = SH
    for fn in (s01_cover, s02_background, s03_goal, s04_content, s05_innovation,
               s06_process, s07_results, s08_value, s09_future, s10_summary,
               s11_thanks):
        fn(prs)
    OUT_DIR.mkdir(exist_ok=True)
    prs.save(OUT_PPTX)
    print(f"saved {OUT_PPTX} ({OUT_PPTX.stat().st_size / 1024:.0f} KB, {len(prs.slides._sldIdLst)} slides)")


if __name__ == "__main__":
    main()
