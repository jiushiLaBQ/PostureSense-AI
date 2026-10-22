"""UI 状态文案测试：守红线 3（无法判断 ≠ 姿态异常）。"""

from __future__ import annotations

from posturesense.ui.main_window import MainWindow


def test_no_person_is_not_abnormal():
    """未检测到人体不得显示为姿态异常。"""
    text = MainWindow._state_text("no_person")
    assert "未检测" in text
    assert "异常" not in text


def test_low_visibility_means_cannot_judge():
    """关键点质量不足 = 无法判断，不是异常。"""
    text = MainWindow._state_text("low_visibility")
    assert "无法判断" in text
    assert "异常" not in text


def test_ok_text():
    assert "已检测" in MainWindow._state_text("ok")


def test_error_text_is_error():
    assert "异常" in MainWindow._state_text("error")


def test_unknown_state_passthrough():
    """未知状态原样透传，不伪装。"""
    assert MainWindow._state_text("something_else") == "something_else"
