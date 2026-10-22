"""annotations 测试：JSONL 读写、校验、正样本转换。"""

from __future__ import annotations

import pytest

from posturesense.core.annotations import (
    Annotation,
    annotations_to_spans,
    load_annotations,
    save_annotations,
)


def _ann(**kw):
    d = {"clip_id": "c1", "start_s": 0.0, "end_s": 10.0, "label": "bad_posture"}
    d.update(kw)
    return Annotation(**d)


def test_roundtrip(tmp_path):
    p = tmp_path / "a.jsonl"
    anns = [_ann(), _ann(start_s=20, end_s=30, label="good_posture")]
    assert save_annotations(p, anns) == 2
    loaded = load_annotations(p)
    assert len(loaded) == 2
    assert loaded[0].label == "bad_posture"
    assert loaded[1].label == "good_posture"


def test_chinese_note(tmp_path):
    p = tmp_path / "a.jsonl"
    save_annotations(p, [_ann(note="用户在喝水")])
    loaded = load_annotations(p)
    assert loaded[0].note == "用户在喝水"


def test_invalid_label_rejected():
    with pytest.raises(ValueError):
        _ann(label="whatever").validate()


def test_invalid_confidence_rejected():
    with pytest.raises(ValueError):
        _ann(confidence="maybe").validate()


def test_end_before_start_rejected():
    with pytest.raises(ValueError):
        _ann(start_s=10, end_s=5).validate()


def test_zero_length_span_excluded_from_positive():
    """零长度时间段不是正样本。"""
    anns = [_ann(start_s=5, end_s=5)]
    spans, skipped = annotations_to_spans(anns)
    assert spans == []
    assert len(skipped) == 1


def test_uncertain_not_positive():
    anns = [
        _ann(confidence="uncertain"),
        _ann(label="uncertain"),
        _ann(label="not_in_frame"),
    ]
    spans, skipped = annotations_to_spans(anns)
    assert spans == []
    assert len(skipped) == 3


def test_positive_spans_extracted():
    anns = [
        _ann(start_s=0, end_s=10),
        _ann(start_s=20, end_s=30, label="good_posture"),
        _ann(start_s=40, end_s=50),
    ]
    spans, skipped = annotations_to_spans(anns)
    assert len(spans) == 2
    assert spans[0].start == 0 and spans[0].end == 10
    assert len(skipped) == 1


def test_filter_by_clip_id():
    anns = [_ann(clip_id="c1"), _ann(clip_id="c2")]
    spans, _ = annotations_to_spans(anns, clip_id="c1")
    assert len(spans) == 1


def test_load_rejects_bad_json(tmp_path):
    p = tmp_path / "bad.jsonl"
    p.write_text("{not json}\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_annotations(p)


def test_load_skips_comments_and_blanks(tmp_path):
    p = tmp_path / "c.jsonl"
    p.write_text(
        "# comment\n\n"
        '{"clip_id":"c1","start_s":0,"end_s":5,"label":"bad_posture"}\n',
        encoding="utf-8",
    )
    assert len(load_annotations(p)) == 1
