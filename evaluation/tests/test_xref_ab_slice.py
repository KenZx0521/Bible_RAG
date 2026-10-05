"""Opt-in xref A/B slice (KG batch 1 plan §5.2).

One W1 image answers with cross_ref_expand + cross_reference on the old data
(control) and on the new data (treatment). The report counts the questions
whose ordered passages changed — more than 34 means stop and investigate, it
is not a gate — and, on the 68 kg_xref questions, which ones reach a gold
passage only through a cross-reference strategy.
"""

import json

import pytest

import xref_ab_slice as xab

APPLIED = {"cross_ref_expand,cross_reference": 3}


def _src(cid, gold=False, found_by=("hybrid_hybrid",)):
    return {"id": cid, "gold": gold, "found_by": list(found_by)}


def _entry(*detail, invalid=False, route="R5"):
    return {"sources": [d["id"] for d in detail], "source_detail": list(detail),
            "invalid": invalid, "route": route}


def _run(per_question, **config):
    return {"config": {"top_k": 5, "metric_k": 6, "metric_version": "v1",
                       "graph_strategies_applied": APPLIED, **config},
            "per_question": per_question}


def _xref_gold(cid="g:1:0"):
    return _src(cid, gold=True, found_by=["cross_ref_expand"])


def _write(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


# --- touched: ordered sources ---------------------------------------------------

def test_touched_uses_ordered_sources():
    a, b, c = _src("a:1:0"), _src("b:1:0"), _src("c:1:0")
    control = _run({"Q1": _entry(a, b), "Q2": _entry(a, b), "Q3": _entry(a, b),
                    "Q4": _entry(a)})
    treatment = _run({"Q1": _entry(b, a), "Q2": _entry(a, b), "Q3": _entry(a, c)})

    report = xab.slice_report(control, treatment, [])

    assert report["n_common"] == 3
    assert report["touched_all"] == 2
    assert report["touched_ids"] == ["Q1", "Q3"]


# --- gold reached only via xref -------------------------------------------------

def test_gold_via_xref_requires_only_xref_found_by():
    run = _run({
        "Q1": _entry(_src("a:1:0", gold=True, found_by=["cross_ref_expand"])),
        "Q2": _entry(_src("a:1:0", gold=True, found_by=["cross_reference", "cross_ref_expand"])),
        "Q3": _entry(_src("a:1:0", gold=True, found_by=["hybrid_hybrid", "cross_reference"])),
        "Q4": _entry(_src("a:1:0", gold=False, found_by=["cross_reference"])),
        "Q5": _entry(_src("a:1:0", gold=True, found_by=[])),
        "Q6": _entry({"id": "a:1:0", "gold": True, "strategy": "cross_reference"}),
        "Q7": _entry(_src("a:1:0", found_by=["cross_reference"]), _src("b:1:0", gold=True)),
    })
    every = [f"Q{i}" for i in range(1, 8)]

    assert xab.gold_via_xref(run, every) == ["Q1", "Q2"]
    assert xab.gold_via_xref(run, ["Q2", "Q3"]) == ["Q2"]


def test_kg_xref_slice_reports_gained_and_lost():
    plain = _src("h:1:0", gold=True)
    control = _run({"Q1": _entry(_xref_gold()), "Q2": _entry(_xref_gold()),
                    "Q3": _entry(plain), "Q4": _entry(_src("z:1:0"))})
    treatment = _run({"Q1": _entry(plain), "Q2": _entry(_xref_gold()),
                      "Q3": _entry(_xref_gold()), "Q4": _entry(_src("y:1:0"))})

    report = xab.slice_report(control, treatment, ["Q3", "Q1", "Q2", "Q9"])

    kg = report["kg_xref"]
    assert (kg["n_ids"], kg["n"]) == (4, 3)
    assert (kg["touched"], kg["touched_ids"]) == (2, ["Q1", "Q3"])
    assert kg["gold_via_xref"] == {"control": ["Q1", "Q2"], "treatment": ["Q2", "Q3"]}
    assert (kg["gained"], kg["lost"]) == (["Q3"], ["Q1"])
    assert report["touched_ids"] == ["Q1", "Q3", "Q4"]


def test_invalid_questions_skipped():
    a, b = _src("a:1:0"), _src("b:1:0")
    control = _run({"Q1": _entry(a), "Q2": _entry(_xref_gold(), invalid=True),
                    "Q3": _entry(b)})
    treatment = _run({"Q1": _entry(invalid=True), "Q2": _entry(_xref_gold()),
                      "Q3": _entry(b)})

    report = xab.slice_report(control, treatment, ["Q1", "Q2", "Q3"])

    assert report["invalid"] == ["Q1", "Q2"]
    assert (report["n_common"], report["touched_all"], report["touched_ids"]) == (1, 0, [])
    assert report["kg_xref"]["n"] == 1
    assert report["kg_xref"]["gold_via_xref"] == {"control": [], "treatment": []}


def test_route_mismatch_is_listed_but_still_touched():
    a, b = _src("a:1:0"), _src("b:1:0")
    control = _run({"Q1": _entry(a, route="R4"), "Q2": _entry(b)})
    treatment = _run({"Q1": _entry(b, route="R5"), "Q2": _entry(b)})

    report = xab.slice_report(control, treatment, [])

    assert report["route_mismatch"] == ["Q1"]
    assert report["touched_ids"] == ["Q1"]


# --- ids file -------------------------------------------------------------------

def test_ids_file_accepts_objects_with_qid(tmp_path):
    objects = tmp_path / "sel.json"
    _write(objects, [{"qid": "Q2", "family": "typology"}, {"qid": "Q1"}, {"qid": "Q2"}])
    plain = tmp_path / "ids.json"
    _write(plain, ["Q1", "Q2"])
    lines = tmp_path / "ids.txt"
    lines.write_text("Q2\nQ1\n", encoding="utf-8")

    assert xab.load_slice_ids(objects) == ["Q1", "Q2"]
    assert xab.load_slice_ids(plain) == ["Q1", "Q2"]
    assert xab.load_slice_ids(lines) == ["Q1", "Q2"]


def test_default_ids_file_is_the_68_kg_xref_questions():
    ids = xab.load_slice_ids(xab.DEFAULT_IDS)

    assert len(ids) == 68
    assert "GENERAL_BIBLE_QUESTION_021" in ids


# --- CLI: version guard and the investigate signal ------------------------------

def _pair_files(tmp_path, control, treatment):
    ids = _write(tmp_path / "sel.json", ["Q1"])
    return (_write(tmp_path / "control.json", control),
            _write(tmp_path / "treatment.json", treatment), ids)


@pytest.mark.parametrize("key, value", [
    ("graph_strategies_applied", {"cross_ref_expand,cross_reference": 2, "(none)": 1}),
    ("top_k", 6),
    ("metric_k", 5),
    ("metric_version", "v2"),
])
def test_config_mismatch_exits_2(tmp_path, monkeypatch, capsys, key, value):
    monkeypatch.setattr(xab, "_OUT_DIR", tmp_path)
    entries = {"Q1": _entry(_src("a:1:0"))}
    c, t, ids = _pair_files(tmp_path, _run(entries), _run(entries, **{key: value}))

    assert xab.main([c, t, "--ids", ids, "--label", "w1"]) == 2

    assert key in capsys.readouterr().err
    assert not (tmp_path / "xref_ab_w1.json").exists()


@pytest.mark.parametrize("entry", [
    {"sources": ["a:1:0"], "source_detail": [{"id": "a:1:0", "strategy": "cross_reference"}]},
    {"sources": ["a:1:0"], "source_detail": [{"id": "a:1:0", "gold": True, "found_by": None}]},
    {"sources": ["a:1:0"]},
], ids=["no_gold_no_found_by", "found_by_none", "no_source_detail"])
def test_runs_without_provenance_exit_2(tmp_path, monkeypatch, capsys, entry):
    """A run from before found_by would report 'gold only via xref: 0 → 0' silently."""
    monkeypatch.setattr(xab, "_OUT_DIR", tmp_path)
    ok = _run({"Q1": _entry(_src("a:1:0"))})
    c, t, ids = _pair_files(tmp_path, ok, _run({"Q1": entry}))

    assert xab.main([c, t, "--ids", ids, "--label", "w1"]) == 2

    assert "found_by" in capsys.readouterr().err
    assert not (tmp_path / "xref_ab_w1.json").exists()
    assert xab.missing_provenance(_run({"Q1": entry, "Q2": _entry(invalid=True)})) == ["Q1"]


def test_max_touched_exit_3(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(xab, "_OUT_DIR", tmp_path)
    a, b = _src("a:1:0"), _src("b:1:0")
    control = _run({"Q1": _entry(a), "Q2": _entry(a), "Q3": _entry(a)})
    treatment = _run({"Q1": _entry(b), "Q2": _entry(b), "Q3": _entry(a)})
    c, t, ids = _pair_files(tmp_path, control, treatment)

    assert xab.main([c, t, "--ids", ids, "--max-touched", "1", "--label", "w1"]) == 3
    assert "stop and investigate" in capsys.readouterr().out
    assert xab.main([c, t, "--ids", ids, "--max-touched", "2"]) == 0
    assert xab.main([c, t, "--ids", ids]) == 0

    saved = json.loads((tmp_path / "xref_ab_w1.json").read_text(encoding="utf-8"))
    assert (saved["touched_all"], saved["max_touched"]) == (2, 1)
    assert saved["inputs"] == {"control": c, "treatment": t, "ids": ids}
    assert saved["kg_xref"]["touched_ids"] == ["Q1"]
