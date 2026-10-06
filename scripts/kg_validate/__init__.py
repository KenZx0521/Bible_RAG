"""KG quality gate library behind scripts/validate_kg.py (plan §3.6).

  model.py          the in-memory KG; kg_snapshot/v1 reader/writer; live Neo4j projection
  registry.py       baseline/probe config, run Context, CheckResult, the check registry
  checks_h.py       H1–H11
  checks_r.py       R1–R11
  checks_probes.py  W and the config/kg_probes.yaml facts
  gate.py           statuses against the baseline, exit code, ratchet, report

D1 lives in scripts/validate_kg.py with the subprocess it runs. Importing the
package registers every other check. Which checks are hard is the baseline's
call (config/kg_quality_baseline/), not the code's; validate_kg.py lists them.
"""

from . import checks_h, checks_probes, checks_r  # noqa: F401  (registers the checks)
