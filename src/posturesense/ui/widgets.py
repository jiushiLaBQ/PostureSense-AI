"""共用控件：统计卡片、空状态、表格助手。"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class StatCard(QFrame):
    """数字统计卡片。值必须来自真实数据源。"""

    def __init__(self, label: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        self.value_label = QLabel("—")
        self.value_label.setObjectName("statValue")
        self.name_label = QLabel(label)
        self.name_label.setObjectName("statLabel")
        lay.addWidget(self.value_label)
        lay.addWidget(self.name_label)

    def set_value(self, text: str) -> None:
        self.value_label.setText(text)


class EmptyState(QFrame):
    """空状态提示。数据库为空时显示，不填假数字。"""

    def __init__(self, message: str, hint: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 32, 24, 32)
        lay.setAlignment(Qt.AlignCenter)

        msg = QLabel(message)
        msg.setStyleSheet("font-size: 16px; color: #94A3B8; font-weight: 600;")
        msg.setAlignment(Qt.AlignCenter)
        lay.addWidget(msg)

        if hint:
            h = QLabel(hint)
            h.setStyleSheet("font-size: 13px; color: #64748B;")
            h.setAlignment(Qt.AlignCenter)
            h.setWordWrap(True)
            lay.addWidget(h)


def make_table(headers: list[str]) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.horizontalHeader().setStretchLastSection(True)
    t.setEditTriggers(QTableWidget.NoEditTriggers)
    t.setSelectionBehavior(QTableWidget.SelectRows)
    t.verticalHeader().setVisible(False)
    return t


def fill_table(table: QTableWidget, rows: list[list[str]]) -> None:
    table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, val in enumerate(row):
            item = QTableWidgetItem(str(val))
            table.setItem(r, c, item)


def format_ms(ms: int | float) -> str:
    """毫秒 → 人读时长。"""
    s = float(ms) / 1000.0
    if s < 60:
        return f"{s:.1f} s"
    if s < 3600:
        return f"{s / 60:.1f} min"
    return f"{s / 3600:.2f} h"


def format_ratio(r: float) -> str:
    return f"{r * 100:.1f}%"
