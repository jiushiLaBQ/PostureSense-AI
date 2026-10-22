"""深色科技风主题。深海军蓝 + 青色 + 少量紫。"""

# 主色
BG_DEEP = "#0B1220"      # 深海军蓝，窗口底
BG_PANEL = "#111A2E"     # 卡片/面板
BG_INPUT = "#0F1B2D"     # 输入框
BORDER = "#1E3A5F"       # 边框
ACCENT = "#0EA5E9"       # 青色主强调
ACCENT_HOVER = "#38BDF8"
ACCENT_2 = "#7DD3FC"     # 浅青，指标文字
PURPLE = "#A78BFA"       # 少量紫
TEXT = "#E2E8F0"
TEXT_DIM = "#94A3B8"
DANGER = "#B91C1C"
DANGER_TEXT = "#FEE2E2"
WARN = "#F59E0B"
OK = "#10B981"

MAIN_STYLESHEET = f"""
QMainWindow, QWidget {{
    background-color: {BG_DEEP};
    color: {TEXT};
    font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
    font-size: 14px;
}}
QLabel#pageTitle {{
    font-size: 22px;
    font-weight: 700;
    color: {TEXT};
    padding: 4px 0 8px 0;
}}
QLabel#pageSubtitle {{
    font-size: 13px;
    color: {TEXT_DIM};
    padding-bottom: 12px;
}}
QLabel#metrics {{
    font-size: 13px;
    color: {ACCENT_2};
    padding: 3px 6px;
}}
QLabel#statValue {{
    font-size: 26px;
    font-weight: 700;
    color: {TEXT};
}}
QLabel#statLabel {{
    font-size: 12px;
    color: {TEXT_DIM};
}}
QLabel#video {{
    background-color: {BG_PANEL};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
QFrame#card {{
    background-color: {BG_PANEL};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QPushButton {{
    background-color: {ACCENT};
    color: #04121F;
    border: none;
    padding: 8px 18px;
    border-radius: 6px;
    font-weight: 600;
}}
QPushButton:hover {{ background-color: {ACCENT_HOVER}; }}
QPushButton:disabled {{ background-color: #334155; color: {TEXT_DIM}; }}
QPushButton#stopBtn {{ background-color: {DANGER}; color: {DANGER_TEXT}; }}
QPushButton#stopBtn:hover {{ background-color: #DC2626; }}
QPushButton#ghost {{
    background-color: transparent;
    border: 1px solid {BORDER};
    color: {TEXT};
}}
QPushButton#ghost:hover {{ border-color: {ACCENT}; color: {ACCENT}; }}
QListWidget#navList {{
    background-color: {BG_PANEL};
    border: none;
    border-right: 1px solid {BORDER};
    outline: none;
    font-size: 14px;
}}
QListWidget#navList::item {{
    padding: 12px 16px;
    color: {TEXT_DIM};
    border-left: 3px solid transparent;
}}
QListWidget#navList::item:selected {{
    background-color: {BG_DEEP};
    color: {ACCENT};
    border-left: 3px solid {ACCENT};
    font-weight: 600;
}}
QListWidget#navList::item:hover {{
    background-color: {BG_DEEP};
    color: {TEXT};
}}
QTableWidget {{
    background-color: {BG_PANEL};
    border: 1px solid {BORDER};
    border-radius: 6px;
    gridline-color: {BORDER};
}}
QHeaderView::section {{
    background-color: {BG_DEEP};
    color: {TEXT_DIM};
    border: none;
    padding: 6px;
    font-weight: 600;
}}
QStatusBar {{ background-color: {BG_DEEP}; color: {TEXT_DIM}; }}
QScrollArea {{ border: none; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 4px 8px;
    color: {TEXT};
}}
QTextEdit {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    color: {TEXT};
}}
QGroupBox {{
    border: 1px solid {BORDER};
    border-radius: 8px;
    margin-top: 10px;
    padding-top: 12px;
    font-weight: 600;
    color: {ACCENT_2};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 4px;
}}
"""

# 页面标题
PAGE_TITLES = {
    "home": ("产品首页", "智姿 AI · 人体工学智能感知与自适应辅助系统"),
    "monitor": ("实时姿态监测", "摄像头实时画面 · 关键点可视化 · 真实性能指标"),
    "calibration": ("个性化姿态校准", "采集自然坐姿 · 建立个人基线"),
    "reminders": ("智能提醒设置", "阈值 · 频率 · 冷却 · 反馈"),
    "history": ("会话记录与历史回顾", "会话列表 · 姿态事件时间线"),
    "analytics": ("数据分析中心", "真实统计数据 · 图表 · 导出"),
    "lab": ("算法测试实验室", "方案 A/B/C 对比 · 评估指标"),
    "privacy": ("隐私与系统设置", "数据管理 · 使用边界声明"),
}
