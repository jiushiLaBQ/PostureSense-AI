"""统一标注格式：JSONL 时间段标注。

每行一条 JSON:
    {"clip_id": "...", "start_s": 12.5, "end_s": 45.0,
     "label": "bad_posture", "confidence": "certain",
     "annotator": "human", "note": ""}

label 取值:
    good_posture   正常
    bad_posture    姿态偏离
    uncertain      无法判断（不计入 P/R，单独报告）
    not_in_frame   人体未入镜

confidence 取值: certain | uncertain
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .evaluation import Span

logger = logging.getLogger(__name__)

VALID_LABELS = {"good_posture", "bad_posture", "uncertain", "not_in_frame"}
VALID_CONFIDENCE = {"certain", "uncertain"}

# 事件识别只把 bad_posture 当正样本
POSITIVE_LABEL = "bad_posture"


@dataclass
class Annotation:
    clip_id: str
    start_s: float
    end_s: float
    label: str
    confidence: str = "certain"
    annotator: str = "human"
    note: str = ""

    def validate(self) -> None:
        if self.label not in VALID_LABELS:
            raise ValueError(f"非法 label: {self.label!r}，允许 {VALID_LABELS}")
        if self.confidence not in VALID_CONFIDENCE:
            raise ValueError(
                f"非法 confidence: {self.confidence!r}，允许 {VALID_CONFIDENCE}"
            )
        if self.end_s < self.start_s:
            raise ValueError(
                f"时间段非法: end_s({self.end_s}) < start_s({self.start_s})"
            )

    def to_dict(self) -> dict:
        return {
            "clip_id": self.clip_id,
            "start_s": self.start_s,
            "end_s": self.end_s,
            "label": self.label,
            "confidence": self.confidence,
            "annotator": self.annotator,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Annotation":
        ann = cls(
            clip_id=str(d["clip_id"]),
            start_s=float(d["start_s"]),
            end_s=float(d["end_s"]),
            label=str(d["label"]),
            confidence=str(d.get("confidence", "certain")),
            annotator=str(d.get("annotator", "human")),
            note=str(d.get("note", "")),
        )
        ann.validate()
        return ann


def load_annotations(path: str | Path) -> list[Annotation]:
    """读取 JSONL 标注文件。非法行抛错，不静默跳过。"""
    path = Path(path)
    out: list[Annotation] = []
    with path.open("r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{lineno} JSON 解析失败: {exc}") from exc
            try:
                out.append(Annotation.from_dict(d))
            except Exception as exc:  # noqa: BLE001
                raise ValueError(f"{path}:{lineno} 标注非法: {exc}") from exc
    logger.info("加载 %d 条标注: %s", len(out), path)
    return out


def save_annotations(path: str | Path, annotations: Iterable[Annotation]) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", encoding="utf-8") as fh:
        for a in annotations:
            a.validate()
            fh.write(json.dumps(a.to_dict(), ensure_ascii=False) + "\n")
            n += 1
    logger.info("保存 %d 条标注: %s", n, path)
    return n


def annotations_to_spans(
    annotations: Iterable[Annotation],
    clip_id: str | None = None,
) -> tuple[list[Span], list[Annotation]]:
    """转成评估用 Span。

    返回 (正样本 spans, 被跳过的不确定标注)。
    label=bad_posture 且 confidence=certain → 正样本
    label=uncertain 或 confidence=uncertain 或 not_in_frame → 跳过
    """
    spans: list[Span] = []
    skipped: list[Annotation] = []
    for a in annotations:
        if clip_id is not None and a.clip_id != clip_id:
            continue
        if (
            a.label == POSITIVE_LABEL
            and a.confidence == "certain"
            and a.end_s > a.start_s
        ):
            spans.append(Span(start=a.start_s, end=a.end_s, label=a.label))
        else:
            skipped.append(a)
    return spans, skipped
