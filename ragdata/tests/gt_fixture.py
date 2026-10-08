"""A mini GT v1 on the mini text layer, plus a ready GT v2 build of it, for the GT tests."""

from __future__ import annotations

import copy
from pathlib import Path

import mini_build
from ragdata.gt.build import BuildResult, Provenance, build_v2, encode_doc, sha256
from ragdata.gt.corpus import ServiceText
from ragdata.gt.curated import parse_curated
from ragdata.store import read_layer

V1 = {
    "metadata": {"total_questions": 3, "description": "mini", "families": {"legacy_head": 1}},
    "questions": [
        {"question_id": "VERSE_LOOKUP_001", "question": "馬太福音18章誰是最大的？",
         "question_type": "VERSE_LOOKUP", "book_name": "馬太福音", "reference": "馬太福音 18:1-4",
         "expected_answer_points": ["凡自己謙卑像這小孩子的", "他在天國裏就是最大的"],
         "reference_answer": "耶穌說：「凡自己謙卑像這小孩子的，他在天國裡就是最大的。」"},
        {"question_id": "EVENT_QUESTION_021", "question": "掃羅往哪裏去？",
         "question_type": "EVENT_QUESTION", "book_name": "使徒行傳", "reference": "使徒行傳 9:1-3",
         "expected_answer_points": ["掃羅向主的門徒口吐威嚇兇殺的話", "詵過小河"],
         "reference_answer": "掃羅帶著文書往大馬色去，「詵過小河，忽然有光四面照着他」，這是「大馬色路上」的事。",
         "family": "trajectory"},
        {"question_id": "TOPIC_QUESTION_021", "question": "以弗所書6章怎樣教導兒女？",
         "question_type": "TOPIC_QUESTION", "book_name": "以弗所書", "reference": "以弗所書 6:1-3",
         "expected_answer_points": ["要在主裏聽從父母", "孝敬父母"],
         "reference_answer": "保羅說：「你們作兒女的，要聽從父母，這是理所當然的。」",
         "family": "longtail_book"},
    ],
}

CURATED = {
    "schema": "ragdata.gt_v2_curated.v1",
    "quote_fixes": [{"qid": "TOPIC_QUESTION_021", "field": "reference_answer",
                     "before": "要聽從父母", "after": "要在主裏聽從父母",
                     "evidence_slot": "eph.6.1", "reason": "弗6:1 原文"}],
    "quote_exempt": [{"qid": "EVENT_QUESTION_021", "field": "reference_answer",
                      "quote": "大馬士革路上", "reason": "情節名稱"}],
    "kay_review": [{"qid": "VERSE_LOOKUP_001", "issue": "測試", "detail": "測試用"}],
}

PROV = Provenance(v1={"path": "ground_truth.json", "sha256": "0" * 64},
                  generator={"command": "test", "git_sha": "0" * 40, "files": {}},
                  curated={"path": "config/gold/gt_v2_curated.yaml", "sha256": "1" * 64},
                  changes_path="config/gold/gt_v2_changes.jsonl")


def corpus(root: Path) -> ServiceText:
    text, _ = mini_build.write_layers(root)
    return ServiceText.from_layer(read_layer(text.path))


def v1() -> dict:
    return copy.deepcopy(V1)


def v1_bytes() -> bytes:
    return encode_doc(V1)


def build(corp: ServiceText, curated: dict | None = None, v1_doc: dict | None = None) -> BuildResult:
    prov = Provenance({"path": "ground_truth.json", "sha256": sha256(encode_doc(v1_doc or V1))},
                      PROV.generator, PROV.curated, PROV.changes_path)
    return build_v2(v1_doc or v1(), corp, mini_build.versification(),
                    parse_curated(copy.deepcopy(curated or CURATED)), prov)
