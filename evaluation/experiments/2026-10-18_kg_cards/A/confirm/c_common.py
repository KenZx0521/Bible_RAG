"""Paths and constants of experiment A's blind confirmation set (confirm_A.md). Host python3 -B, stdlib.

The stage-0 A/ modules are imported through sys.path and never changed; their sha256 values are
pinned in confirm_A.md §0 and checked by frozen_mismatches(). Data (segments, questions, contexts,
items, outputs) go to store reports/kg_cards_20261018/A_confirm/ only; the repo holds code and
text-free notes. Nothing here calls Ollama, the backend or claude.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
A_DIR = HERE.parent
if str(A_DIR) not in sys.path:
    sys.path.insert(0, str(A_DIR))
import a_common as ac  # noqa: E402
from a_common import (CAP_CHARS, KNAME, SEED, cc, jsonl, read_json, sha256_file, sha256_text,  # noqa: E402,F401
                      short_ref, verse_units)

# ---------------------------------------------------------------- paths
OUT = cc.OUT_ROOT / "A_confirm"
ST0 = ac.OUT                                   # stage-0 store dir (read only)
LAYER_AUTO, LAYER_REF = ac.LAYER_AUTO, ac.LAYER_REF
ST0_ITEMS, ST0_K0 = ac.ITEMS, ac.OUT / "k0_status.json"
SEGMENTS = OUT / "segments.json"
ALIAS_TABLE = OUT / "alias_table.json"
HO = OUT / "ho"                                # question-writing transcripts, state, ledger
QUESTIONS_PASSED = HO / "questions_passed.json"  # audited questions so far (§2.8 schema, "pilot": bool)
KAY_K0_1B = HO / "kay" / "k0_1b.json"          # Kay's layer check (ho_a/kay_a.py apply); the only K0-1b source
K1_JSON = OUT / "k1.json"
QUESTIONS_FROZEN = OUT / "questions_frozen.json"  # F2
QUESTIONS_FROZEN_MANIFEST = OUT / "questions_frozen_manifest.json"  # F2 record (ho_a/freeze_a.py)
K_U2 = OUT / "k_u2.json"                       # K-U2 verdict (ho_a/freeze_a.py)
CONTEXTS = OUT / "contexts.json"               # F3
ITEMS = OUT / "items.json"
SUPPORT_JSON = OUT / "support.json"
K0_STATUS = OUT / "k0_status.json"
MANIFEST = OUT / "inputs_manifest.json"        # {"frozen": {name: sha256}}: F2 (freeze_a) then F3 (run_c prepare)
GEN_SEED, GEN_ARMS = OUT / "gen_seed.jsonl", OUT / "gen_arms.jsonl"
ARMS_JOBS, ARMS_META = OUT / "arms_jobs.json", OUT / "arms_meta.json"
SCORES = OUT / "scores.json"
REPORT_JSON, REPORT_MD = OUT / "report.json", OUT / "report.md"

# ---------------------------------------------------------------- frozen inputs (confirm_A.md §0)
FROZEN_SHA = {
    "layer_auto.json": "932d2242dc3fdce8830112484c81bc0ea5364cc4caaf6978b12f8984790ee9ab",
    "ref_layer.json": "79d57efe451f675b6d2c1163d801b2a173a24a1a8b1ed0ba6a207f698ca16660",
    "cards_common.py": "ae9dc16ceedad750a0ea0e2da0ec4db8098dfa4f58ae32820e84a567ed56acef",
}
PROMPT_SHA = {
    "system_prompt": "f58c03fa9dfbdfbded1c4c6a01c72c5129078f54cdade009299448bb28ddfa54",
    "user_template": "677e91e5d33a0791a67007785f5993db8f62e4241bb62378ca639891f44328b8",
    "seed_system": "5405fbb037d50d16603adef0909be68ed1947f30f149b3f9820b0e6f57026abd",
    "seed_user_template": "dd00c3dfc2f6c30d980b110df66c4065d134339410f6dbf2e79bd060db114d62",
}
# stage-0 A/ code reused unchanged (ST0 inputs_manifest.json "code")
A0_CODE = ("engine.py", "regnal.py", "tcanon.py", "seeds_a.py", "keys_a.py", "arms_a.py", "score_a.py",
           "a_common.py", "items_a.py", "layer_re.py", "analyze_a.py", "run_a.py")

# ---------------------------------------------------------------- design constants
REPS_N = 3                                     # every arm, G-ref included (§5)
ARMS = ("G-auto", "T-canon", "T-rows", "B0", "G-ref")
REPS = {a: REPS_N for a in ARMS}
NUM_CTX = 131072                               # stage-0 K0-3
OPTIONS = dict(cc.OPTIONS, num_ctx=NUM_CTX)
KD = {"以色列": "I", "猶大": "J", "I": "I", "J": "J"}
QTYPES = ("S1a", "S1b", "S1c", "S4")
GAP_EDGES = (("J06", "J07"), ("J07", "J08"))   # 亞她利雅's two edges; 提比尼 handled by audit wording
CHAIN_EXCLUDE = ("J00",)                       # 所羅門 is not on the divided-kingdom chains
S4_SEED_BANNED = ("J06", "J19")                # Kings / Chronicles accession-age conflicts
S1B_UNIT = "次|代|任|位"
SEG_EDGES = (2, 3, 4)
KU_MIN = 12                                    # K-U and K-U2
PILOT_N, K1_MIN_PASS, K1_MIN = 12, 10, 0.80
MAX_ATTEMPTS, MAX_FIX_ROUNDS, PARALLEL = 3, 1, 4
ALPHA, MIN_DELTA, N_BOOT, K3_MAX = 0.05, 0.10, 10000, 0.05
KAY_LAYER_ROWS, KAY_LAYER_STOP_WRONG, KAY_QUESTIONS = 20, 2, 10
CANARY_ARM_CALLS = 30

# ---------------------------------------------------------------- budget (§8)
USD_CAP = 140.0
JOB_CAP_USD = {"gen": 4.0, "fix": 3.0, "audit": 1.5}
PROBE_CAP_USD = 1.0
CLAUDE_VERSION_HO = "2.1.299"                  # HO pin
CLAUDE_VERSION = "2.1.302"                     # re-pin after probe_cli.py passes (F1)

# ---------------------------------------------------------------- base context (§4)
BACKEND_QUERY = "http://localhost:8000/api/v1/query"
PROD_BUILD_ID = "b20261008_e05d3e55"
TOP_K = 5
COLLECT_TIMEOUT_S, COLLECT_RETRIES = 180, 2


def request_body(question: str) -> dict:
    """prod as-is: core top_k 5 plus the event_registry aux lane at its prod default (≤6 sources)."""
    return {"question": question, "top_k": TOP_K, "include_sources": True, "include_context": True,
            "retrieval_only": True}


# ---------------------------------------------------------------- frozen wording (§6.4)
WORDING = {
    "stop": "依事先規則停止（{rule}＝{value}），不構成無效證據；盲集{state}",
    "h1_fail": "王朝年表推導卡在盲集上未達事先登記的門檻（單位 n＝{n}，Δ̄＝{d}，95% CI {ci}），記 null；王朝層結案",
    "h1_negative": "且 G-auto 顯著劣於正典經文窗",
    "h1_sig_small": "顯著但未達事先定的最小效果",
    "h1_only": "結構化年表加程式計算，在王朝年代題上顯著優於同流程的正典經文窗；未證明圖譜操作優於"
               "『同一份層列加 LLM 自己推』，不計為圖譜增益",
    "h1_h2": "regex 可建的王朝鏈上，程式多步走訪與推算，在王朝年代題上顯著優於同流程的正典經文窗與層列平鋪",
    "h1_h2_scope": "只限王朝年代題（S1、S4 窄題型、出題前配額的盲題）",
    "k3": "不談 prod",
}


def frozen_mismatches() -> list[str]:
    """Frozen file / prompt sha256 values that differ from confirm_A.md §0 (empty = all match)."""
    import seeds_a
    bad = []
    files = {"layer_auto.json": LAYER_AUTO, "ref_layer.json": LAYER_REF,
             "cards_common.py": A_DIR.parent / "cards_common.py"}
    for name, p in files.items():
        if not Path(p).is_file() or sha256_file(p) != FROZEN_SHA[name]:
            bad.append(name)
    got = {"system_prompt": sha256_text(cc.SYSTEM_PROMPT), "user_template": sha256_text(cc.USER_TEMPLATE),
           "seed_system": sha256_text(seeds_a.SEED_SYSTEM), "seed_user_template": sha256_text(seeds_a.SEED_USER)}
    bad += [k for k, v in got.items() if v != PROMPT_SHA[k]]
    man = ST0 / "inputs_manifest.json"
    if man.is_file():
        code = read_json(man)["code"]
        bad += [f for f in A0_CODE if f in code and sha256_file(A_DIR / f) != code[f]]
    return bad
