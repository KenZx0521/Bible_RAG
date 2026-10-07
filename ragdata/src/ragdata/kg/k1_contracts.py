"""The R1 event registry's two contract files and its report.

- ``event_registry_v2.json``: the design §2.21 shape — ``ev`` ids, slot-range anchors,
  provenance on every anchor and trigger. The backend reads it from the next stage on.
- ``event_registry_v1.json``: the shape the current backend reads
  (``utils/retrieval/event_registry.py``), anchors as passage ids. ``V1_VS_V2`` lists how
  they differ and what the backend must change to read either.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping, Sequence

V2_SCHEMA = "ragdata.event_registry.v2"
V1_GENERATOR = "ragdata build events（R1，由 backend/data/event_registry.json 經 legacy_ids 機械轉換）"
V1_ANCHOR_ORDER = "legacy order (book, chapter, pericope index); each anchor is now its passage_id"
V1_VS_V2 = (
    "事件 id：v1 用舊拼音 id（event:babieta）；v2 用 event_id（ev0001）並以 legacy_id 保留舊 id。"
    "R1 期間 backend 回應中的事件 id 仍是舊 id（§3.3）。",
    "錨點：v1 只是 passage_id 字串；v2 是物件，含 passage_id、start_key／end_key（半節帶 b）、"
    "start_slot／end_slot 與 provenance_class=legacy_tuned。",
    "觸發詞：v1 是 triggers 字串陣列；v2 是 legacy_triggers 物件陣列，每條附 provenance_class="
    "external_legacy、source、note、retire_by=R2，另有 pdf_terms、external_aliases 兩欄（R1 為空）。",
    "來源欄：v1 保留舊 provenance（head_event_backfill 等）；v2 改名 legacy_provenance。",
    "v1 沿用舊檔的 version／generated_at／trigger_rule／anchor_order／dropped 鍵；generator 與 "
    "anchor_order 改寫成新說明。",
)
BACKEND_NOTES = (
    "現行 backend 的 event_registry.PERICOPE_ID（[0-9a-z]+:\\d+:\\d+）會拒絕 ps: 開頭的錨點；"
    "改讀 v1 檔前要放寬成 ragcommon.ids 的 passage 文法。",
    "select_aux_anchors 的 _covered 以「cid == anchor 或 cid 以 anchor + ':' 開頭」判斷核心已含錨點；"
    "新 id 下 chunk 是 ck:…、節是 vs:…，要改用 payload 的 passage_id 判斷。",
)


def v2_doc(events: Sequence[Mapping[str, Any]], struct_version: str) -> dict[str, Any]:
    keep = ("event_id", "legacy_id", "name", "legacy_provenance", "legacy_triggers", "pdf_terms",
            "external_aliases")
    anchor_keys = ("passage_id", "start_key", "end_key", "start_slot", "end_slot",
                   "provenance_class")
    return {"schema": V2_SCHEMA, "variant": "R1", "struct": struct_version,
            "events": [{**{k: e[k] for k in keep},
                        "anchors": [{k: a[k] for k in anchor_keys} for a in e["anchors"]]}
                       for e in events]}


def v1_events(events: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [{"id": e["legacy_id"], "name": e["name"], "provenance": e["legacy_provenance"],
             "triggers": [t["text"] for t in e["legacy_triggers"]],
             "anchors": [a["passage_id"] for a in e["anchors"]]} for e in events]


def v1_doc(events: Sequence[Mapping[str, Any]], source: Mapping[str, Any]) -> dict[str, Any]:
    return {"version": 1, "generated_at": source.get("generated_at"), "generator": V1_GENERATOR,
            "trigger_rule": source.get("trigger_rule"), "anchor_order": V1_ANCHOR_ORDER,
            "events": v1_events(events), "dropped": source.get("dropped", [])}


def events_report(events: Sequence[Mapping[str, Any]],
                  anchors: Sequence[Sequence[Mapping[str, Any]]],
                  source: Mapping[str, Any], struct_version: str) -> dict[str, Any]:
    flat = [a for group in anchors for a in group]
    changes = Counter(a["change"] for a in flat)
    return {
        "schema": "ragdata.events_report.v1", "struct": struct_version,
        "source": {"file": source["file"], "sha256": source["sha256"]},
        "counts": {"events": len(events), "anchors": len(flat),
                   "passages": len({a["passage_id"] for a in flat}),
                   "same": changes["same"], "narrowed": changes["narrowed"],
                   "widened": changes["widened"],
                   "legacy_triggers": sum(len(e["legacy_triggers"]) for e in events)},
        "v1_vs_v2": list(V1_VS_V2), "backend_notes": list(BACKEND_NOTES),
        "change_rule": "依整數節範圍（§2.14）：範圍相同且無幽靈節＝same；範圍相同但含幽靈節＝narrowed；"
                       "passage 範圍包含舊範圍並多出節（半節）＝widened。same_with_half_verse 列出範圍相同、"
                       "但 passage 起或迄於半節的錨點（例如 act:9:0 → ps:act.9.1 只到 9:19 前半）。",
    }
