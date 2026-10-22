"""评估指标与事件匹配。

红线:
- 事件级匹配规则固定在此，不随方案变化。
- 不确定样本单独列表，不计入 P/R。
- 调参集与测试集分离由实验协议约定，本模块只算指标。

事件匹配规则（见仓库根 README.md §4.6）:
- 时间重叠比例 IoU ≥ IOU_THRESHOLD 记为匹配
- 起点误差 ≤ START_TOLERANCE_SEC
- 贪心按 IoU 降序一对一匹配
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

IOU_THRESHOLD = 0.3
START_TOLERANCE_SEC = 2.0


@dataclass
class Span:
    """一个时间段（标注事件或预测事件）。"""

    start: float  # 秒
    end: float  # 秒
    label: str = "abnormal"
    uncertain: bool = False

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass
class MatchResult:
    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    # 匹配对 (pred_index, gt_index, iou, start_delta)
    pairs: list[tuple[int, int, float, float]] = field(default_factory=list)
    # 不确定标注（不计入 P/R）
    uncertain_skipped: int = 0
    # 匹配的检测延迟（|start_pred - start_gt|）
    detection_delays: list[float] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "matches": len(self.pairs),
            "uncertain_skipped": self.uncertain_skipped,
            "mean_detection_delay_sec": (
                sum(self.detection_delays) / len(self.detection_delays)
                if self.detection_delays else None
            ),
        }


@dataclass
class Metrics:
    precision: Optional[float]
    recall: Optional[float]
    f1: Optional[float]
    false_positive_rate: Optional[float]  # 占总时长的误报时长比
    false_positives_per_hour: Optional[float]
    mean_detection_delay_sec: Optional[float]
    total_gt_events: int
    total_pred_events: int
    uncertain_skipped: int
    evaluated_duration_sec: float

    def to_dict(self) -> dict:
        return {
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "false_positive_rate": self.false_positive_rate,
            "false_positives_per_hour": self.false_positives_per_hour,
            "mean_detection_delay_sec": self.mean_detection_delay_sec,
            "total_gt_events": self.total_gt_events,
            "total_pred_events": self.total_pred_events,
            "uncertain_skipped": self.uncertain_skipped,
            "evaluated_duration_sec": self.evaluated_duration_sec,
        }


def span_iou(a: Span, b: Span) -> float:
    """两个时间段的交并比。"""
    inter = max(0.0, min(a.end, b.end) - max(a.start, b.start))
    union = a.duration + b.duration - inter
    return inter / union if union > 0 else 0.0


def match_events(
    preds: list[Span],
    gts: list[Span],
    iou_threshold: float = IOU_THRESHOLD,
    start_tolerance_sec: float = START_TOLERANCE_SEC,
) -> MatchResult:
    """贪心一对一事件匹配。

    标注 uncertain=True 的样本跳过，单独计数。
    """
    result = MatchResult()

    usable_gts = [(i, g) for i, g in enumerate(gts) if not g.uncertain]
    result.uncertain_skipped = len(gts) - len(usable_gts)

    # 计算所有 (pred, gt) 候选对
    candidates: list[tuple[float, float, int, int]] = []
    for pi, p in enumerate(preds):
        for gi, g in usable_gts:
            iou = span_iou(p, g)
            start_delta = abs(p.start - g.start)
            if iou >= iou_threshold and start_delta <= start_tolerance_sec:
                candidates.append((iou, start_delta, pi, gi))

    # 贪心：IoU 降序，起点误差升序
    candidates.sort(key=lambda t: (-t[0], t[1]))

    used_p: set[int] = set()
    used_g: set[int] = set()
    for iou, start_delta, pi, gi in candidates:
        if pi in used_p or gi in used_g:
            continue
        used_p.add(pi)
        used_g.add(gi)
        result.pairs.append((pi, gi, iou, start_delta))
        result.detection_delays.append(start_delta)

    result.true_positives = len(result.pairs)
    result.false_positives = len(preds) - len(used_p)
    result.false_negatives = len(usable_gts) - len(used_g)
    return result


def compute_metrics(
    preds: list[Span],
    gts: list[Span],
    total_duration_sec: float,
    iou_threshold: float = IOU_THRESHOLD,
    start_tolerance_sec: float = START_TOLERANCE_SEC,
) -> Metrics:
    """事件级评估指标。

    total_duration_sec: 评估片段总时长，用于每小时误报。
    无标注或无预测时相应指标为 None，不填 0 冒充。
    """
    m = match_events(preds, gts, iou_threshold, start_tolerance_sec)

    tp = m.true_positives
    fp = m.false_positives
    fn = m.false_negatives

    precision = tp / (tp + fp) if (tp + fp) > 0 else (0.0 if preds else None)
    recall = tp / (tp + fn) if (tp + fn) > 0 else (0.0 if gts else None)
    if precision is None or recall is None:
        f1 = None
    elif precision + recall == 0:
        f1 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)

    # 误报时长比：未匹配预测的时间占总时长
    unmatched = [p for i, p in enumerate(preds) if i not in {pi for pi, _, _, _ in m.pairs}]
    fp_sec = sum(p.duration for p in unmatched)
    fpr = fp_sec / total_duration_sec if total_duration_sec > 0 else None

    hours = total_duration_sec / 3600.0
    fp_per_hour = (fp / hours) if hours > 0 else None

    delay = (
        sum(m.detection_delays) / len(m.detection_delays)
        if m.detection_delays else None
    )

    return Metrics(
        precision=precision,
        recall=recall,
        f1=f1,
        false_positive_rate=fpr,
        false_positives_per_hour=fp_per_hour,
        mean_detection_delay_sec=delay,
        total_gt_events=len([g for g in gts if not g.uncertain]),
        total_pred_events=len(preds),
        uncertain_skipped=m.uncertain_skipped,
        evaluated_duration_sec=total_duration_sec,
    )
