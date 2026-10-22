"""evaluation 测试：事件匹配规则、指标计算、边界情况。"""

from __future__ import annotations

import pytest

from posturesense.core.evaluation import (
    IOU_THRESHOLD,
    Span,
    compute_metrics,
    match_events,
    span_iou,
)


def test_span_iou_exact_overlap():
    a = Span(0, 10)
    b = Span(0, 10)
    assert span_iou(a, b) == pytest.approx(1.0)


def test_span_iou_partial():
    a = Span(0, 10)
    b = Span(5, 15)
    assert span_iou(a, b) == pytest.approx(5 / 15)


def test_span_iou_disjoint():
    assert span_iou(Span(0, 5), Span(10, 15)) == 0.0


def test_perfect_match():
    preds = [Span(10, 40)]
    gts = [Span(10, 40)]
    m = match_events(preds, gts)
    assert m.true_positives == 1
    assert m.false_positives == 0
    assert m.false_negatives == 0
    assert m.detection_delays == [0.0]


def test_no_match():
    preds = [Span(100, 110)]
    gts = [Span(10, 40)]
    m = match_events(preds, gts)
    assert m.true_positives == 0
    assert m.false_positives == 1
    assert m.false_negatives == 1


def test_iou_threshold_boundary():
    """IoU 低于阈值 → 不匹配（起点误差均在容差内）。"""
    # pred 0-10, gt 0-12 → IoU = 10/12 = 0.833 ≥ 0.3 → 匹配
    assert match_events([Span(0, 10)], [Span(0, 12)]).true_positives == 1
    # pred 0-10, gt 2-12 → IoU = 8/12 = 0.667 ≥ 0.3 → 匹配
    assert match_events([Span(0, 10)], [Span(2, 12)]).true_positives == 1
    # 极低重叠：pred 0-10, gt 9-30 → IoU = 1/30 ≈ 0.033 < 0.3 → 不匹配
    assert match_events([Span(0, 10)], [Span(9, 30)]).true_positives == 0


def test_start_tolerance_boundary():
    """起点误差超容差 → 即使 IoU 够也不匹配。"""
    # 起点差 3s > 2s 容差
    m = match_events([Span(0, 50)], [Span(3, 53)])
    assert m.true_positives == 0


def test_one_to_one_matching():
    """一个预测不能同时匹配多个标注。"""
    preds = [Span(0, 100)]
    gts = [Span(0, 50), Span(50, 100)]
    m = match_events(preds, gts)
    assert m.true_positives == 1
    assert m.false_negatives == 1


def test_uncertain_skipped():
    """不确定标注跳过，不计入 P/R，也不与预测匹配。"""
    preds = [Span(0, 10)]
    gts = [Span(0, 10, uncertain=True), Span(20, 30)]
    m = match_events(preds, gts)
    assert m.uncertain_skipped == 1
    # 跳过 uncertain 后只剩 gt 20-30，与 pred 0-10 无重叠
    assert m.true_positives == 0
    assert m.false_positives == 1
    assert m.false_negatives == 1  # 只算 20-30 那个


# ---------------------------------------------------------------------------
# 指标
# ---------------------------------------------------------------------------
def test_metrics_perfect():
    preds = [Span(10, 40), Span(100, 130)]
    gts = [Span(10, 40), Span(100, 130)]
    m = compute_metrics(preds, gts, total_duration_sec=3600)
    assert m.precision == pytest.approx(1.0)
    assert m.recall == pytest.approx(1.0)
    assert m.f1 == pytest.approx(1.0)
    assert m.mean_detection_delay_sec == pytest.approx(0.0)


def test_metrics_partial():
    preds = [Span(10, 40), Span(100, 110)]  # 第二个是误报
    gts = [Span(10, 40), Span(200, 230)]  # 第二个漏报
    m = compute_metrics(preds, gts, total_duration_sec=3600)
    assert m.precision == pytest.approx(0.5)
    assert m.recall == pytest.approx(0.5)
    assert m.f1 == pytest.approx(0.5)
    assert m.false_positives_per_hour == pytest.approx(1.0)


def test_metrics_no_predictions():
    m = compute_metrics([], [Span(0, 10)], total_duration_sec=3600)
    assert m.precision is None  # 无预测 → 不编造
    assert m.recall == 0.0
    assert m.f1 is None


def test_metrics_no_ground_truth():
    m = compute_metrics([Span(0, 10)], [], total_duration_sec=3600)
    assert m.recall is None
    assert m.precision == 0.0


def test_metrics_empty_both():
    m = compute_metrics([], [], total_duration_sec=3600)
    assert m.precision is None
    assert m.recall is None
    assert m.f1 is None


def test_false_positive_rate_by_duration():
    preds = [Span(0, 60)]  # 60s 误报
    gts = []
    m = compute_metrics(preds, gts, total_duration_sec=3600)
    assert m.false_positive_rate == pytest.approx(60 / 3600)
    assert m.false_positives_per_hour == pytest.approx(1.0)


def test_detection_delay():
    preds = [Span(12, 42)]
    gts = [Span(10, 40)]
    m = compute_metrics(preds, gts, total_duration_sec=3600)
    assert m.mean_detection_delay_sec == pytest.approx(2.0)


def test_metrics_dict_serializable():
    m = compute_metrics([Span(0, 10)], [Span(0, 10)], total_duration_sec=60)
    d = m.to_dict()
    assert d["precision"] == 1.0
    assert d["evaluated_duration_sec"] == 60
