"""Validity of the P1/P2 questions (prereg §5.6; qset.md §3, §4): the P2 validity check, pinned at F1a.

An item is **invalid** (dropped; its slot refilled once, by the same persona and writer; never in any denominator) iff
  v_blind       its job's output run breaks a blinding rule (qset.md §3: transcript_g.blinding of
                transcript_g.check_run on the run whose output is used; re-checked here from the saved transcript)
  v_slot        the job's output does not hold exactly its slot labels with one non-empty question of at most
                MAX_CHARS each (qset.md §4; a job with no usable output fails it for every slot; a label given
                twice has no single question, so it fails too: stricter than qset's code, which kept the first)
  v_simplified  a simplified-only character (qset.md §4's list, copied)
  v_duplicate   the same text (NFKC, white space dropped) as an earlier item of the same set
  P2_RULES      positives only: any of mech_g.syntax_violations(question, spec, names), the nine question rules
                (names_present, extra_name, marker_rule, v_number, v_kin, v_source, ordinal_form, yes_no,
                multi_question) on the slot's HO view (prompts_g.slot_spec)
v_answer does not apply (§5.6: the writer never sees the answer). Everything else stays in the denominator.
Near misses get the four generic checks only: a family is outside the positive slot shape by design (another book,
a yes/no form, a generation count, the Cain line, one person, d = 1), so the question rules would reject exactly what
it asks for; every near miss stays in the set's near-miss count (n = 20; run_qg counts one still invalid after its
refill as fired, the conservative side of §9's release clause).

Order of assembly (``assemble``): first-round items of every job in spec order, duplicates marked in set order;
each job's invalid slots (duplicates included) form its one refill job ``<job_id>-r`` (``refill_job``; a refill job
never gets one); a slot whose refill draft exists takes the refill item (``refilled``, the first violations kept);
then duplicates are marked again with first-round items first, so a refill never displaces an item that was valid.
Pure functions over the spec, a draft reader and a blinding check (run_qg passes the store's). Nothing here launches
an agent or calls an LLM.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any, Callable, Iterable, Mapping, Sequence

import mech_g as M
import prompts_g as P

MAX_CHARS = 200
# qset.md §4 (mech_q.SIMPLIFIED, copied): characters that exist only in simplified Chinese
SIMPLIFIED = frozenset("这们说时国为过对来见问门长东车书经实关会犹亚约罗吗让还从与亲谁该应开")
GENERIC_RULES = ("v_blind", "v_slot", "v_simplified", "v_duplicate")
RULES = GENERIC_RULES + M.P2_RULES
REFILL_SUFFIX = "-r"
SLOT_KEYS = ("item_id", "slot", "kind", "sid", "qtype", "chapter", "stratum", "x", "y", "gold", "marker_required",
             "family", "source", "copy")
Read = Callable[[str], "Mapping[str, Any] | None"]
Blind = Callable[[Mapping[str, Any]], Sequence[Any]]


@dataclass(frozen=True)
class Violation:
    rule: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def norm(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text or ""))


def slot_violations(labels: Sequence[str], output: Mapping[str, Any] | None) -> tuple[dict[str, str], list[Violation]]:
    """({label: question}, v_slot violations) of a writer job's structured output (qset's rule)."""
    got: dict[str, str] = {}
    bad = []
    items = (output or {}).get("items") if isinstance(output, Mapping) else None
    entries = [(it["slot"] if isinstance(it.get("slot"), str) else None, it.get("question"))
               if isinstance(it, Mapping) else (None, None) for it in (items if isinstance(items, list) else [])]
    twice = {lab for lab in labels if sum(e[0] == lab for e in entries) > 1}
    bad += [Violation("v_slot", f"{lab}: given more than once") for lab in labels if lab in twice]
    for lab, q in entries:
        if lab in twice:
            continue
        if lab not in labels:
            bad.append(Violation("v_slot", f"unexpected slot {lab!r}"))
            continue
        if not isinstance(q, str) or not q.strip() or len(q) > MAX_CHARS:
            bad.append(Violation("v_slot", f"{lab}: empty or longer than {MAX_CHARS}"))
            continue
        got[lab] = q.strip()
    bad += [Violation("v_slot", f"{lab}: no question") for lab in labels if lab not in got
            and not any(v.detail.startswith(f"{lab}:") for v in bad)]
    return got, bad


def question_violations(slot: Mapping[str, Any], question: str, names: P.Names) -> list[Violation]:
    """v_simplified, and on a positive the nine question rules of mech_g (P2_RULES)."""
    out = []
    simp = SIMPLIFIED & set(question)
    if simp:
        out.append(Violation("v_simplified", f"{len(simp)} simplified-only character(s)"))
    if slot["kind"] == "pos":
        spec = P.slot_spec(slot, names, "Q01")
        out += [Violation(v.rule, v.detail) for v in M.syntax_violations(question, spec, names)]
    return out


def _item(job: Mapping[str, Any], slot: Mapping[str, Any]) -> dict[str, Any]:
    return {**{k: slot.get(k) for k in SLOT_KEYS}, "set": job["set"], "job": job["job_id"].removesuffix(REFILL_SUFFIX),
            "run_job": job["job_id"], "writer": job["writer"], "persona": job["persona"], "question": None,
            "refilled": False}


def job_items(job: Mapping[str, Any], draft: Mapping[str, Any] | None, names: P.Names,
              blind: Blind) -> list[dict[str, Any]]:
    """One item per slot of a (first or refill) job from its draft: valid or with its violations."""
    labels = [s["slot"] for s in job["slots"]]
    if draft is None:
        common = [Violation("v_slot", "no draft (the job has not run)")]
        got, bad = {}, []
    else:
        void = list(blind(draft))
        common = [Violation("v_blind", f"{len(void)} blinding error(s) in the output run")] if void else []
        out = draft.get("output") if draft.get("ok") and not void else None
        got, bad = slot_violations(labels, out) if out is not None else ({}, [])
        if out is None and not void:
            common = [Violation("v_slot", "the job produced no usable output")]
    items = []
    for s in job["slots"]:
        it = _item(job, s)
        q = got.get(s["slot"])
        vs = list(common) or [v for v in bad if v.detail.startswith(f"{s['slot']}:")]
        if q is None and not vs:
            vs = [Violation("v_slot", f"{s['slot']}: no question")]
        if q is not None and not common:
            vs = question_violations(s, q, names)
        items.append({**it, "question": q if not common else None, "valid": not vs,
                      "violations": [v.as_dict() for v in vs]})
    return items


def dedupe(items: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """v_duplicate on the later copy among valid items; first-round items keep priority over refills."""
    out = [dict(it) for it in items]
    seen: set[str] = set()
    for it in sorted(out, key=lambda it: bool(it.get("refilled"))):     # stable: set order within each round
        if not it["valid"]:
            continue
        key = norm(it["question"])
        if key in seen:
            it["valid"] = False
            it["violations"] = list(it["violations"]) + [Violation("v_duplicate", "same text as an earlier item").as_dict()]
        else:
            seen.add(key)
    return out


def refill_job(job: Mapping[str, Any], first: Iterable[Mapping[str, Any]]) -> dict[str, Any] | None:
    """The one refill job of a first-round job: its invalid slots, same persona and writer; none for a refill job."""
    if job["job_id"].endswith(REFILL_SUFFIX):
        return None
    bad = {it["slot"] for it in first if it["job"] == job["job_id"] and not it["valid"]}
    slots = [s for s in job["slots"] if s["slot"] in bad]
    return {**job, "job_id": job["job_id"] + REFILL_SUFFIX, "refill_of": job["job_id"], "slots": slots} if slots else None


def first_round(spec: Mapping[str, Any], read: Read, names: P.Names, blind: Blind) -> list[dict[str, Any]]:
    by_id = {j["job_id"]: j for j in spec["jobs"]}
    return dedupe([it for jid in spec["order"] for it in job_items(by_id[jid], read(jid), names, blind)])


def refill_jobs(spec: Mapping[str, Any], read: Read, names: P.Names, blind: Blind) -> list[dict[str, Any]]:
    """Every refill job the first round asks for, in spec order (whether or not it has run)."""
    first, by_id = first_round(spec, read, names, blind), {j["job_id"]: j for j in spec["jobs"]}
    return [r for jid in spec["order"] if (r := refill_job(by_id[jid], first))]


def assemble(spec: Mapping[str, Any], read: Read, names: P.Names, blind: Blind) -> list[dict[str, Any]]:
    """Every slot of the set in spec order, refills applied, duplicates marked (this module's docstring)."""
    first, by_id = first_round(spec, read, names, blind), {j["job_id"]: j for j in spec["jobs"]}
    second: dict[str, dict[str, Any]] = {}
    for jid in spec["order"]:
        r = refill_job(by_id[jid], first)
        draft = read(r["job_id"]) if r else None
        if draft is not None:
            second |= {it["item_id"]: it for it in job_items(r, draft, names, blind)}
    out = []
    for it in first:
        if not it["valid"] and it["item_id"] in second:
            it = {**second[it["item_id"]], "refilled": True, "first_violations": it["violations"]}
        out.append(it)
    return dedupe(out)


def tally(items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Counts only (no text, no id): slots, valid, refilled, invalid by rule, per kind."""
    out: dict[str, Any] = {}
    for kind in ("pos", "near"):
        mine = [i for i in items if i["kind"] == kind]
        rules: dict[str, int] = {}
        for i in mine:
            if not i["valid"]:
                for r in dict.fromkeys(v["rule"] for v in i["violations"]):
                    rules[r] = rules.get(r, 0) + 1
        out[kind] = {"slots": len(mine), "valid": sum(i["valid"] for i in mine),
                     "refilled": sum(bool(i.get("refilled")) for i in mine), "invalid_by_rule": dict(sorted(rules.items()))}
    return out
