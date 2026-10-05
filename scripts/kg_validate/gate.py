"""Score check results against the baseline: statuses, exit code, ratchet, report.

Metric statuses:
  ok          meets the hard target / did not regress past baseline + tolerance
  fail        hard target not met (or the target itself is unavailable)
  regressed   record metric worse than its baseline (subset: a new failing id)
  unmeasured  value None with no declared reason: the check did not really run
  n/a         value None for a reason the check declared (e.g. D1 on a snapshot)
A metric is hard or record by its own "severity" when the baseline gives one,
else by its check's; the check takes its worst metric status (_PRECEDENCE), so
a record metric inside a hard check regresses (exit 2) and never fails.
Exit code: 1 when any non-warn check is fail, unmeasured or error; else 2 when
any regressed; else 0.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from .registry import CheckResult

_PRECEDENCE = ("error", "fail", "unmeasured", "regressed", "ok")
_BREAKING = {"error", "fail", "unmeasured"}


def _meets(value, bound, direction: str) -> bool:
    if direction == "down":
        return value <= bound
    if direction == "up":
        return value >= bound
    if direction == "equal":
        return value == bound
    if direction == "subset":
        return set(value) <= set(bound)
    return True


def _regressed(value, base, direction: str, tolerance) -> bool:
    if base is None or direction == "none":
        return False
    if direction in ("equal", "subset"):
        return not _meets(value, base, direction)
    return not _meets(value, base + tolerance if direction == "down" else base - tolerance, direction)


def _ratcheted(value, base, direction: str):
    """The baseline after a --ratchet run: only ever an improvement."""
    if base is None:
        return value
    if direction == "down":
        return min(value, base)
    if direction == "up":
        return max(value, base)
    if direction == "subset":
        # Each probe ratchets on its own: healed ids leave the baseline, new
        # failures never enter it (they stay regressions until fixed).
        return sorted(set(base) & set(value))
    return base  # equal / none move only with --accept


def _histogram_warnings(current: dict, base: dict | None, pct: float) -> list[str]:
    warnings = []
    for group in ("labels", "relationships"):
        old, new = (base or {}).get(group) or {}, current[group]
        for key in sorted(set(old) | set(new)):
            a, b = old.get(key, 0), new.get(key, 0)
            if base is not None and (a == 0 or abs(b - a) / a * 100 > pct) and a != b:
                warnings.append(f"{group}.{key}: {a} -> {b}")
    return warnings


def external_targets(baseline: dict, step0_sha: Path) -> dict[tuple[str, str], object]:
    """Hard targets that live in another tracked file (`target_from`). H7's sha
    is check_step0's own baseline, so re-recording Step 0 moves both gates
    together instead of leaving a second copy to drift."""
    try:
        files = json.loads(Path(step0_sha).read_text(encoding="utf-8")).get("files") or {}
    except (OSError, ValueError):
        files = {}
    out = {}
    for spec in baseline["checks"]:
        for name, m in spec["metrics"].items():
            if m.get("target_from"):
                key = m["target_from"].partition(":")[2]
                out[(spec["id"], name)] = (files.get(key) or {}).get("sha256")
    return out


def _score(spec: dict, name: str, m: dict, res: CheckResult, targets: dict) -> dict:
    value = res.metrics.get(name)
    target = targets.get((spec["id"], name)) if "target_from" in m else m.get("target")
    out = {"value": value, "baseline": m["value"], "target": target, "direction": m["direction"]}
    severity = m.get("severity", spec["severity"])
    if "severity" in m:
        out["severity"] = severity  # the report says which bound an overridden metric is held to
    if value is None:
        reason = res.na_reason(name)
        out.update({"status": "n/a", "reason": reason} if reason else {"status": "unmeasured"})
        return out
    if severity == "hard":
        bound = target
        if target is None and "target_from" in m:
            out.update(status="fail", reason=f"target {m['target_from']} unavailable")
            return out
        failed = target is not None and not _meets(value, target, m["direction"])
        out["status"] = "fail" if failed else "ok"
    else:
        bound = m["value"]
        out["status"] = "regressed" if _regressed(value, bound, m["direction"], m.get("tolerance", 0)) else "ok"
    if m["direction"] == "subset" and bound is not None:
        out["new"] = sorted(set(value) - set(bound))
        out["fixed"] = sorted(set(bound) - set(value))
    return out


def evaluate(results: dict[str, CheckResult], baseline: dict, targets: dict | None = None) -> dict:
    targets = targets or {}
    checks = {}
    for spec in baseline["checks"]:
        res = results.get(spec["id"])
        if res is None:
            continue
        entry = {"title": spec.get("title", ""), "severity": spec["severity"], "metrics": {},
                 "detail": res.detail, "samples": res.samples}
        if res.error:
            entry.update(status="error", error=res.error)
        elif "tolerance_pct" in spec:   # W
            current = res.metrics.get("histogram")
            if current is None:
                entry.update(status="skipped", reason=res.na_reason("histogram") or "not measured")
            else:
                warnings = _histogram_warnings(current, spec["metrics"]["histogram"]["value"],
                                               spec["tolerance_pct"])
                entry.update(status="warn" if warnings else "ok", warnings=warnings,
                             compared=sum(len(group) for group in current.values()))
        else:
            for name, m in spec["metrics"].items():
                entry["metrics"][name] = _score(spec, name, m, res, targets)
            statuses = {e["status"] for e in entry["metrics"].values()}
            entry["status"] = next((s for s in _PRECEDENCE if s in statuses), "skipped")
        checks[spec["id"]] = entry

    failures = [cid for cid, e in checks.items() if e["status"] in _BREAKING and e["severity"] != "warn"]
    regressed = [cid for cid, e in checks.items() if e["status"] == "regressed"]
    return {"exit_code": 1 if failures else 2 if regressed else 0,
            "failures": failures,
            "hard_failures": [cid for cid in failures if checks[cid]["severity"] == "hard"],
            "regressions": regressed, "checks": checks}


def apply_ratchet(baseline: dict, results: dict[str, CheckResult], ratchet: bool,
                  accept: set[str], measured: dict) -> dict:
    """Return a new baseline: improvements (and null baselines) adopted when
    `ratchet`, every metric of the `accept`ed checks adopted as-is. Each check
    that changed is stamped with `measured`, since one baseline file mixes
    values from live and snapshot runs. Metrics whose target lives elsewhere
    (`target_from`) are never copied in; a count of an id set (`count_of`) is
    re-derived as len(ids), never ratcheted on its own."""
    new = copy.deepcopy(baseline)
    for spec in new["checks"]:
        res = results.get(spec["id"])
        if res is None or res.error:
            continue
        changed = False
        for name, m in spec["metrics"].items():
            value = res.metrics.get(name)
            if value is None or m.get("target_from") or m.get("count_of"):
                continue
            if spec["id"] in accept:
                adopted = value
            elif ratchet:
                adopted = _ratcheted(value, m["value"], m["direction"])
            else:
                continue
            if adopted != m["value"]:
                m["value"] = adopted
                changed = True
        # A swap (one id healed, one new) ratchets the ids to their intersection
        # while min() would keep the count: failures=1 next to failing=[].
        for m in spec["metrics"].values():
            if m.get("count_of"):
                ids = spec["metrics"][m["count_of"]]["value"]
                derived = None if ids is None else len(ids)
                if derived != m["value"]:
                    m["value"] = derived
                    changed = True
        if changed:
            spec["measured"] = measured
    return new


def _fmt(value) -> str:
    if isinstance(value, float):
        return f"{value:.4g}"
    if isinstance(value, list):
        return f"{len(value)} ids"
    if isinstance(value, str) and len(value) > 16:
        return value[:12] + "…"
    return str(value)


def _metric_text(name: str, m: dict, severity: str) -> str:
    bound = m["target"] if m.get("severity", severity) == "hard" else m["baseline"]
    text = f"{name}={_fmt(m['value'])} (vs {_fmt(bound)})"
    if m["status"] == "n/a":
        return text + f" [n/a: {m['reason']}]"
    if m["status"] != "ok":
        text += f" [{m['status']}{': ' + m['reason'] if m.get('reason') else ''}]"
    if m.get("new"):
        text += " new: " + ", ".join(m["new"][:6])
    return text


def print_report(report: dict) -> None:
    print(f"KG quality gate — {report['origin']}  (baseline {report['baseline']})")
    if report.get("partial"):
        print(f"  PARTIAL snapshot, missing {report['partial']}: checks reading them are n/a")
    for cid, e in report["checks"].items():
        reasons = {m.get("reason") for m in e["metrics"].values()}
        if e["metrics"] and all(m["status"] == "n/a" for m in e["metrics"].values()) and len(reasons) == 1:
            parts = [f"n/a: {reasons.pop()}"]  # a whole check out of scope here: say why once
        else:
            parts = [_metric_text(name, m, e["severity"]) for name, m in e["metrics"].items()]
        if e["status"] == "error":
            parts.append(e["error"])
        if e.get("reason"):
            parts.append(e["reason"])
        if "compared" in e:
            parts.append(f"{e['compared']} label/relationship counts compared")
        if e.get("warnings"):
            parts.append(f"{len(e['warnings'])} drifts: " + "; ".join(e["warnings"][:6]))
        print(f"  {cid:<7}{e['severity']:<7}{e['status'].upper():<11}{'  '.join(parts)}")
    code = report["exit_code"]
    reason = {0: "pass", 1: f"failure (hard target, error or unmeasured) {report['failures']}",
              2: f"regression {report['regressions']}"}[code]
    print(f"exit {code}: {reason}")
