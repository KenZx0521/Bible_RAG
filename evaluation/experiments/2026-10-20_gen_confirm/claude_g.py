"""Headless `claude -p` launches of every agent of the GEN confirmation set (prereg §3.1, §3.5, §5.4, §8.2).

One launcher for both uses: the HO blind writers, fixers and value-blind auditors (tools mode "bt", Opus 5.5,
effort xhigh) and the qset P1/P2 writers (tools mode "none", Opus 5.5 or Sonnet 5.5 per job). Copied from
experiment A's ho_a/claude_a.py and the regnal qset's claude_q.py (originals untouched, neither imported). Blinding
as claude_a: cwd AGENT_CWD (/srv: empty, outside and not above the repo), --system-prompt replaces the default
prompt, --setting-sources local, --strict-mcp-config, --disable-slash-commands, --no-session-persistence, the
parent's CLAUDE* variables removed, the cwd's auto-memory directory must be empty; PWD is set to the cwd (the
parent's would name the repo), OLDPWD and AI_AGENT (it names the parent CLI and session kind) dropped. The
prompts record lists the names (never the values) of the variables the agent got, so probe and runs compare.

Tools modes:
* "bt": only Bash and only `bt ...` (--tools Bash --allowedTools "Bash(bt *)", the other built-ins disallowed)
  behind the bt-guard PreToolUse hook through --settings; <root>/bin/bt runs bt_g.py (v, grep, books).
* "none": --tools "" (StructuredOutput from --json-schema is all that is left), no bt on PATH, the same hook as
  insurance.
The hook is HO's original ho_tools/bt_guard.py run by path from <root>/hookbin/bt-guard after its sha256 check
(hog_common.check_guard); no copy of it exists in this experiment.

CLI pin (§3.1, qset's pin_cli): at probe time ``copy_cli`` copies ~/.local/share/claude/versions/<v> into
CLI_DIR/<v>/claude (versions/ gets cleaned). The source must hash as expected: a version in KNOWN_CLI_SHA256 (the
regnal qset's pin) against that value, any other only against a sha256 the operator passes (probe_g --cli-sha256;
no trust on first use); claude.sha256 and claude.json beside the copy record the sha, its basis (known |
operator) and the source's path, size and mtime. The single pin file PIN_PATH (store cli_pin.json, shared by HO and
qset, frozen in F1) holds the version, the copy's sha256 and path, whether --thinking-display summarized is passed,
the model ids the probe saw answer for opus and sonnet, and the probed (tools mode, model) pairs. Every launch links
the sha-checked copy as <root>/clibin/claude, first on PATH (DISABLE_AUTOUPDATER=1), and checks that `claude`
resolves there and `claude --version` names the pinned version. CliChanged (copy missing or changed, another
version answers) is §3.1's infrastructure stop (重做 probe); CliUnavailable (`--version` gave no answer on
VERSION_TRIES tries) is a transient failure: retry the job, no new probe.

Order of a launch, every refusal (HoError) before anything is written into the run root: the job (a probed
(tools mode, model) pair, effort EFFORT — the probe ran only xhigh, §3.1 —, a known user scope, a plain run id, no
extra record key clashing with RECORD_KEYS); the root (g_common.writable, and under a ledger base of `out_root`);
the run's reservation (ledger_g, taken under the budget lock) with a cap ≥ --max-budget-usd; no earlier transcript
or prompts record; cwd and auto-memory; then the wrappers and the CLI link (through writable), the version check,
the prompts record (RECORD_KEYS: system, user, schema, budget_usd, model, effort, tools_mode, user_scope,
tool_values, pin, env_keys, ...) and the subprocess. user_scope has no default (prereg §3.3: "prompt" when the
user prompt is all template and tool values, "agent" when it embeds agent text). ``run_reserved`` does reserve →
launch and, on any exception before the subprocess started, releases the reservation (ledger_g.release drops it
only when no transcript or prompts record exists) and raises again.

Outcomes: run_error() is claude_a's (failure or model_fallback). model_fallback() — a `model_refusal_fallback`
event, or modelUsage naming another model — is an infrastructure failure (rerun, output unused) and wins over
agent_limit (prereg §2.3: 模型改派 is an infrastructure rerun; A's runs_a counted a fallback that also hit the cap
as an agent limit); agent_limit() — the budget cap, max turns, structured-output retries, or cost at the cap — is
the agent's outcome (counted, never rerun); any other failure (no result event, timeout, CLI start failure, API
error, no structured output) is an infrastructure failure.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import g_common as GC
import hog_common as H
import ledger_g as L
from hog_common import CliChanged, CliUnavailable, HoError, now, read_json, under, write_json

AGENT_CWD = GC.AGENT_CWD
CLAUDE_BIN = "claude"
CLI_VERSIONS_DIR = GC.CLI_VERSIONS_DIR
CLI_DIR = GC.CLI_DIR
PIN_PATH = GC.CLI_PIN
KNOWN_CLI_SHA256 = {"2.1.302": "60d7eb7f12fbb28a52533fe8be5884097403562aa02dc73991a021c7067e29a5"}  # qset's pin
MODELS = {"opus": "claude-opus-5-5", "sonnet": "claude-sonnet-5-5"}   # passed as --model; the probe confirms them
EFFORT = "xhigh"
THINKING_DISPLAY = "summarized"
TOOLS_MODES = ("bt", "none")
PROBED_COMBOS = (("bt", "opus"), ("none", "opus"), ("none", "sonnet"))   # HO; qset P1/P2 (prereg §3.1, §5.4)
USER_SCOPES = ("prompt", "agent")      # prompt: the user prompt is all tool-rendered; agent: it embeds agent text
ALLOWED_TOOLS = ("Bash(bt *)",)
DISALLOWED_TOOLS = ("Read", "Edit", "Write", "MultiEdit", "Glob", "Grep", "LS", "WebFetch", "WebSearch", "Task",
                    "Agent", "NotebookEdit", "NotebookRead", "TodoWrite", "Skill", "ToolSearch", "KillShell",
                    "BashOutput")
DROP_ENV = frozenset({"OLDPWD", "AI_AGENT"})            # besides every CLAUDE* variable
BT_WRAPPER, GUARD_WRAPPER = "bt", "bt-guard"
DEFAULT_TIMEOUT_S = 3600
VERSION_TRIES, VERSION_TIMEOUT_S = GC.CLI_VERSION_TRIES, 60
RECORD_KEYS = frozenset({"run_id", "system", "user", "schema", "argv", "cwd", "budget_usd", "model", "effort",
                         "tools_mode", "user_scope", "tool_values", "pin", "env_keys", "utc"})
LIMIT_SUBTYPES = frozenset({"error_max_budget_usd", "error_max_turns", "error_max_structured_output_retries"})
COST_EPS = 1e-9
_SETUP_LOCK = threading.Lock()          # parallel launches share <root>/clibin, bin and hookbin
_SHA_CACHE: dict[tuple[str, int, int, int], str] = {}


@dataclass(frozen=True)
class CliPin:
    """What every run is pinned to (prereg §3.1): the CLI copy, the thinking flag, model ids, probed pairs."""
    claude_version: str
    cli_sha256: str
    cli_path: str
    thinking_display: bool
    models: Mapping[str, str]
    combos: tuple[tuple[str, str], ...] = PROBED_COMBOS     # (tools mode, model key) pairs the probe passed

    def __post_init__(self) -> None:
        object.__setattr__(self, "combos", tuple(tuple(c) for c in self.combos))

    @property
    def tools_modes(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(mode for mode, _ in self.combos))

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "models": dict(self.models), "combos": [list(c) for c in self.combos]}

    def model(self, key: str) -> str:
        if key not in self.models:
            raise HoError(f"no pinned model id for {key!r} (pin models {sorted(self.models)})")
        return self.models[key]

    def key_of(self, model: str) -> str | None:
        return next((k for k, v in self.models.items() if v == model), None)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "CliPin":
        models, combos = d.get("models"), d.get("combos")
        ok = (isinstance(d.get("claude_version"), str) and isinstance(d.get("cli_sha256"), str)
              and len(d["cli_sha256"]) == 64 and isinstance(d.get("cli_path"), str)
              and isinstance(d.get("thinking_display"), bool) and isinstance(models, Mapping)
              and all(isinstance(k, str) and isinstance(v, str) for k, v in models.items())
              and isinstance(combos, (list, tuple)) and combos
              and all(isinstance(c, (list, tuple)) and len(c) == 2 and c[0] in TOOLS_MODES and c[1] in models
                      for c in combos))
        if not ok:
            raise HoError("cli pin needs claude_version, cli_sha256, cli_path, thinking_display (bool), models "
                          f"(key -> id) and combos: non-empty [tools mode in {TOOLS_MODES}, model key] pairs")
        return cls(d["claude_version"], d["cli_sha256"], d["cli_path"], d["thinking_display"], dict(models),
                   tuple((m, k) for m, k in combos))


@dataclass(frozen=True)
class RunResult:
    run_id: str
    transcript: Path
    returncode: int
    seconds: float
    result: Mapping[str, Any] | None
    error: str | None = None
    usage: Mapping[str, Any] = field(default_factory=dict)
    limit: str | None = None            # the agent limit the run ended on (counted, never rerun)
    fallback: str | None = None         # model_fallback(): an infrastructure failure
    model: str = ""
    tools_mode: str = ""

    @property
    def output(self) -> Mapping[str, Any] | None:
        return None if self.result is None else self.result.get("structured_output")

    @property
    def infra_failure(self) -> bool:
        """A failure that is not the agent's outcome: rerun (up to MAX_INFRA_RETRIES), not counted as an attempt."""
        return self.error is not None and self.limit is None


# ---------------------------------------------------------------- CLI copy and pin
def file_sha(path: Path | str) -> str:
    """sha256 of a (large) file, cached per inode, size and mtime."""
    st = Path(path).stat()
    key = (str(Path(path).resolve()), st.st_ino, st.st_size, st.st_mtime_ns)
    if key not in _SHA_CACHE:
        _SHA_CACHE[key] = H.sha256_file(path)
    return _SHA_CACHE[key]


def sha_basis(version: str) -> str:
    """'known' when the version's sha256 is pinned here (the qset's), else 'operator' (passed at probe time)."""
    return "known" if version in KNOWN_CLI_SHA256 else "operator"


def _expected_sha(version: str, expected_sha256: str | None) -> str:
    exp = None if expected_sha256 is None else expected_sha256.strip().lower()
    if exp is not None and not re.fullmatch(r"[0-9a-f]{64}", exp):
        raise HoError(f"CLI {version}: expected sha256 {expected_sha256!r} is not 64 hex digits")
    known = KNOWN_CLI_SHA256.get(version)
    if known is not None and exp not in (None, known):
        raise HoError(f"CLI {version}: the expected sha256 {exp[:12]} is not its known sha256 {known[:12]}")
    if known is None and exp is None:
        raise HoError(f"CLI {version}: no known sha256; pass the expected one (probe_g.py run --cli-sha256)")
    return known or exp


def copy_cli(version: str, versions_dir: Path = CLI_VERSIONS_DIR, cli_dir: Path = CLI_DIR,
             expected_sha256: str | None = None) -> tuple[Path, str]:
    """versions/<version> copied to <cli_dir>/<version>/claude with claude.sha256 and claude.json beside it;
    (copy, sha256). The source must hash as expected (_expected_sha); an existing copy is kept when it hashes so."""
    if not re.fullmatch(r"[0-9]+(\.[0-9]+){1,3}", version):
        raise HoError(f"CLI version {version!r} is not a plain version")
    src = Path(versions_dir) / version
    if not src.is_file():
        raise HoError(f"CLI {version}: no executable in {versions_dir}")
    want = _expected_sha(version, expected_sha256)
    dst = H.writable(Path(cli_dir) / version / CLAUDE_BIN)
    st, sha = src.stat(), H.sha256_file(src)
    if sha != want:
        raise HoError(f"CLI {version}: sha256 {sha[:12]} is not the expected {want[:12]}")
    with _SETUP_LOCK:
        if dst.is_file() and H.sha256_file(dst) != sha:
            raise HoError(f"CLI copy {dst} exists with another sha256; refusing to overwrite it")
        if not dst.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_name(dst.name + ".tmp")
            shutil.copyfile(src, tmp)
            tmp.chmod(0o755)
            if H.sha256_file(tmp) != sha:
                tmp.unlink()
                raise HoError(f"CLI {version}: the copy does not hash like its source")
            tmp.replace(dst)
        H.writable(dst.with_name(CLAUDE_BIN + ".sha256")).write_text(f"{sha}  {CLAUDE_BIN}\n", encoding="utf-8")
        mtime = datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(timespec="seconds")
        write_json(dst.with_name(CLAUDE_BIN + ".json"),
                   {"version": version, "sha256": sha, "sha_basis": sha_basis(version), "source": str(src),
                    "source_size": st.st_size, "source_mtime_utc": mtime, "copied_utc": now()})
    return dst, sha


def cli_source(pin_or_path: CliPin | Path | str) -> dict[str, Any]:
    """claude.json beside a copy (copy_cli's record of the sha basis and the source); {} when absent."""
    exe = Path(pin_or_path.cli_path if isinstance(pin_or_path, CliPin) else pin_or_path)
    meta = exe.with_name(CLAUDE_BIN + ".json")
    return dict(read_json(meta)) if meta.is_file() else {}


def load_pin(path: Path = PIN_PATH) -> CliPin:
    """The single pin file (store cli_pin.json), written by `probe_g.py pin`; refuse without it."""
    if not Path(path).is_file():
        raise HoError(f"{Path(path).name} missing: run the CLI probe (probe_g.py run) and pin a passing verdict")
    return CliPin.from_dict(read_json(path))


def write_pin(pin: CliPin, path: Path = PIN_PATH, **record: Any) -> Path:
    return write_json(path, {**pin.as_dict(), "written_utc": now(), **record})


def check_cli(pin: CliPin) -> Path:
    """The pinned copy exists and hashes as pinned (else CliChanged: an infrastructure stop)."""
    exe = Path(pin.cli_path)
    if not exe.is_file() or file_sha(exe) != pin.cli_sha256:
        raise CliChanged(f"CLI {pin.claude_version}: the pinned copy is missing or not sha {pin.cli_sha256[:12]}")
    return exe


def pin_cli(root: Path, pin: CliPin) -> Path:
    """<root>/clibin/claude -> the sha-checked pinned copy; returns <root>/clibin."""
    exe = check_cli(pin)
    link = H.writable(Path(root) / "clibin") / CLAUDE_BIN      # the directory entry is written, not the target
    with _SETUP_LOCK:
        link.parent.mkdir(parents=True, exist_ok=True)
        if link.is_symlink() and Path(os.readlink(link)) != exe:
            link.unlink()
        if not link.is_symlink():
            if link.exists():
                raise HoError(f"{link} exists and is not a link")
            link.symlink_to(exe)
    return link.parent


# ---------------------------------------------------------------- wrappers, environment, argv
def _wrapper(target: Path, args: str = '"$@"', stderr: str = "") -> str:
    return f"#!/bin/sh\nexport PYTHONDONTWRITEBYTECODE=1\nexec {sys.executable} -B {target} {args}{stderr}\n"


def _write_exe(path: Path, text: str) -> None:
    path = H.writable(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file() or path.read_text(encoding="utf-8") != text:
        path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


def write_wrappers(root: Path, tools_mode: str) -> dict[str, str]:
    """<root>/hookbin/bt-guard (HO's original guard, sha checked) and, in mode bt, <root>/bin/bt (bt_g.py)."""
    _mode(tools_mode)
    H.check_guard()
    content = {GUARD_WRAPPER: _wrapper(H.BT_GUARD, args="")}
    if tools_mode == "bt":
        content[BT_WRAPPER] = _wrapper(H.HERE / "bt_g.py", stderr=" 2>/dev/null")
    with _SETUP_LOCK:
        _write_exe(Path(root) / "hookbin" / GUARD_WRAPPER, content[GUARD_WRAPPER])
        if tools_mode == "bt":
            _write_exe(Path(root) / "bin" / BT_WRAPPER, content[BT_WRAPPER])
    return content


def child_env(root: Path, tools_mode: str, cwd: Path = AGENT_CWD,
              base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Parent env without CLAUDE*, OLDPWD and AI_AGENT; <root>/clibin, <root>/hookbin and (mode bt) <root>/bin first
    on PATH."""
    _mode(tools_mode)
    base = os.environ if base is None else base
    env = {k: v for k, v in base.items() if not k.upper().startswith("CLAUDE") and k not in DROP_ENV}
    dirs = [Path(root) / "clibin", Path(root) / "hookbin"] + ([Path(root) / "bin"] if tools_mode == "bt" else [])
    env["PATH"] = ":".join([*map(str, dirs), base.get("PATH", "/usr/bin:/bin")])
    env.update(PYTHONDONTWRITEBYTECODE="1", DISABLE_AUTOUPDATER="1", PWD=str(cwd))
    return env


def _mode(tools_mode: str) -> str:
    if tools_mode not in TOOLS_MODES:
        raise HoError(f"tools mode {tools_mode!r} is not one of {TOOLS_MODES}")
    return tools_mode


def claude_version(root: Path, tools_mode: str = "none") -> str:
    """`claude --version` as the launch would run it (PATH of child_env), refusing a claude not in <root>/clibin;
    up to VERSION_TRIES tries, CliUnavailable when none gave an answer."""
    env = child_env(root, tools_mode, Path(root))
    found = shutil.which(CLAUDE_BIN, path=env["PATH"])
    if found is None or Path(found).parent.resolve() != (Path(root) / "clibin").resolve():
        raise HoError(f"`{CLAUDE_BIN}` resolves to {found}, not {Path(root) / 'clibin'}")
    why = []
    for _ in range(VERSION_TRIES):
        try:
            run = subprocess.run([CLAUDE_BIN, "--version"], capture_output=True, text=True, timeout=VERSION_TIMEOUT_S,
                                 stdin=subprocess.DEVNULL, env=env)
        except (OSError, subprocess.TimeoutExpired) as err:
            why.append(type(err).__name__)
            continue
        if run.returncode == 0 and run.stdout.strip():
            return run.stdout.strip()
        why.append(f"exit {run.returncode}")
    raise CliUnavailable(f"`{CLAUDE_BIN} --version` gave no answer in {VERSION_TRIES} tries ({', '.join(why)})")


def check_claude_version(root: Path, expected: str, tools_mode: str = "none") -> str:
    found = claude_version(root, tools_mode)
    if found.split()[:1] != [expected]:
        raise CliChanged(f"claude --version is {found!r}; pinned {expected}")
    return found


def guard_settings() -> str:
    hook = {"type": "command", "command": GUARD_WRAPPER}
    return json.dumps({"hooks": {"PreToolUse": [{"matcher": "*", "hooks": [hook]}]}})


def build_argv(system_prompt: str, user_prompt: str, schema: Mapping[str, Any], budget_usd: float, model: str,
               effort: str, thinking_display: bool, tools_mode: str) -> list[str]:
    _mode(tools_mode)
    thinking = ["--thinking-display", THINKING_DISPLAY] if thinking_display else []
    tools = ["--tools", ""] if tools_mode == "none" else ["--tools", "Bash", "--allowedTools", *ALLOWED_TOOLS]
    return [CLAUDE_BIN, "-p", user_prompt, "--model", model, "--effort", effort, *thinking,
            "--system-prompt", system_prompt, *tools, "--disallowedTools", *DISALLOWED_TOOLS,
            "--permission-mode", "dontAsk", "--setting-sources", "local", "--settings", guard_settings(),
            "--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence",
            "--output-format", "stream-json", "--verbose", "--json-schema", json.dumps(schema, ensure_ascii=False),
            "--max-budget-usd", f"{budget_usd:g}"]


# ---------------------------------------------------------------- cwd and memory
def check_cwd(cwd: Path) -> Path:
    """The agent cwd must exist, be a directory outside (and not above) the repo, and be empty."""
    cwd = Path(cwd)
    if not cwd.is_dir():
        raise HoError(f"agent cwd {cwd} is not a directory")
    if under(cwd, GC.REPO) or under(GC.REPO, cwd):
        raise HoError(f"agent cwd {cwd} must be outside (and not above) the repo")
    if any(cwd.iterdir()):
        raise HoError(f"agent cwd {cwd} is not empty")
    return cwd


def memory_dir(cwd: Path, home: Path | None = None) -> Path:
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(Path(cwd)))
    return (Path.home() if home is None else Path(home)) / ".claude" / "projects" / slug / "memory"


def check_memory_dir(cwd: Path, home: Path | None = None) -> Path:
    mem = memory_dir(cwd, home)
    if mem.is_dir() and any(mem.iterdir()):
        raise HoError(f"auto-memory {mem} is not empty; the agent would load it")
    return mem


# ---------------------------------------------------------------- events
def read_events(path: Path) -> list[dict[str, Any]]:
    """stream-json lines; a torn line (cut mid-JSON or mid-character) is dropped, undecodable bytes are replaced
    (so the text still reaches the transcript rules)."""
    out = []
    for line in Path(path).read_bytes().decode("utf-8", errors="replace").splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict):
            out.append(e)
    return out


def result_event(events: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    return next((e for e in reversed(events) if e.get("type") == "result"), None)


def init_event(events: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    return next((e for e in events if e.get("type") == "system" and e.get("subtype") == "init"), None)


def usage_of(result: Mapping[str, Any] | None, events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    calls = sum(1 for e in events if e.get("type") == "assistant"
                for c in (e.get("message") or {}).get("content") or [] if isinstance(c, dict)
                and c.get("type") == "tool_use")
    u = (result or {}).get("usage") or {}
    out = {k: u.get(k) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens",
                                 "output_tokens")}
    out.update({"thinking_tokens": (u.get("output_tokens_details") or {}).get("thinking_tokens"),
                "total_cost_usd": (result or {}).get("total_cost_usd"), "num_turns": (result or {}).get("num_turns"),
                "duration_ms": (result or {}).get("duration_ms"), "tool_calls": calls,
                "models": sorted(((result or {}).get("modelUsage") or {}))})
    return out


def failure(rc: int, result: Mapping[str, Any] | None) -> str | None:
    if result is None:
        return f"no result event (exit {rc})"
    if result.get("subtype") != "success" or result.get("is_error"):
        return f"result {result.get('subtype')!r} is_error={result.get('is_error')}"
    if not isinstance(result.get("structured_output"), dict):
        return "no structured output"
    return None


def model_fallback(events: Sequence[Mapping[str, Any]], result: Mapping[str, Any] | None, model: str) -> str | None:
    """Why the run was not answered by ``model`` alone (the CLI's refusal fallback); None when it was."""
    ev = next((e for e in events if e.get("type") == "system" and e.get("subtype") == "model_refusal_fallback"), None)
    if ev is not None:
        return f"model fallback {ev.get('original_model')} → {ev.get('fallback_model')} ({ev.get('trigger')})"
    other = sorted(set(((result or {}).get("modelUsage") or {})) - {model})
    return f"modelUsage names other models {other}" if other else None


def run_error(rc: int, result: Mapping[str, Any] | None, events: Sequence[Mapping[str, Any]],
              model: str) -> str | None:
    """claude_a.run_error with the job's model: the failure, else the model fallback; None for a clean run."""
    return failure(rc, result) or model_fallback(events, result, model)


def agent_limit(result: Mapping[str, Any] | None, budget_usd: float) -> str | None:
    """Why a failed run ended on an agent limit (counted, never rerun); None for an infrastructure failure."""
    if result is None:
        return None
    if result.get("subtype") in LIMIT_SUBTYPES:
        return str(result["subtype"])
    cost = result.get("total_cost_usd")
    if isinstance(cost, (int, float)) and cost >= budget_usd - COST_EPS:
        return f"total_cost_usd {cost:g} ≥ cap {budget_usd:g}"
    return None


def outcome(rc: int, result: Mapping[str, Any] | None, events: Sequence[Mapping[str, Any]], model: str,
            budget_usd: float, start_error: str | None = None) -> tuple[str | None, str | None, str | None]:
    """(error, limit, fallback) of one finished run; a fallback is never an agent limit (prereg §2.3)."""
    fallback = model_fallback(events, result, model)
    error = start_error or run_error(rc, result, events, model)
    limit = agent_limit(result, budget_usd) if error and not fallback and not start_error else None
    return error, limit, fallback


# ---------------------------------------------------------------- launch
def check_job(pin: CliPin, model: str, tools_mode: str, effort: str, user_scope: str, run_id: str,
              extra_record: Mapping[str, Any] | None) -> None:
    """The job's own refusals (pure): a probed (tools mode, model) pair, the probed effort, scope, id, record."""
    _mode(tools_mode)
    key = pin.key_of(model)
    if key is None:
        raise HoError(f"model {model!r} is not a pinned id ({sorted(pin.models.values())})")
    if (tools_mode, key) not in pin.combos:
        raise HoError(f"({tools_mode}, {key}) was not probed (pin {[list(c) for c in pin.combos]})")
    if effort != EFFORT:
        raise HoError(f"effort {effort!r} was not probed (prereg §3.1: {EFFORT})")
    if user_scope not in USER_SCOPES:
        raise HoError(f"user scope {user_scope!r} is not one of {USER_SCOPES}")
    if not (isinstance(run_id, str) and L.RUN_ID.fullmatch(run_id)):
        raise HoError(f"run id {run_id!r} is not a plain id")
    clash = sorted(set(extra_record or {}) & RECORD_KEYS)
    if clash:
        raise HoError(f"extra record keys {clash} would overwrite the launch record")


def check_root(root: Path, out_root: Path | str = GC.OUT_ROOT) -> str:
    """The run root may be written (g_common.writable) and lies under a ledger base of `out_root`; its kind."""
    H.writable(root)
    return L.Ledger(out_root).kind_of(root)


def check_reserve(root: Path, run_id: str, budget_usd: float) -> Path:
    path = Path(root) / "reserve" / f"{run_id}.json"
    b = L.budget_of(path) if path.is_file() else None
    if b is None or b + COST_EPS < budget_usd:
        raise HoError(f"run {run_id}: no ledger reservation of ≥ {budget_usd:g} USD (ledger_g.reserve first)")
    return path


def launch(root: Path, run_id: str, system_prompt: str, user_prompt: str, schema: Mapping[str, Any],
           budget_usd: float, model: str, pin: CliPin, *, user_scope: str, tools_mode: str = "bt",
           effort: str = EFFORT, cwd: Path = AGENT_CWD, timeout_s: int = DEFAULT_TIMEOUT_S,
           tool_values: Mapping[str, str] | None = None, extra_record: Mapping[str, Any] | None = None,
           home: Path | None = None, out_root: Path | str = GC.OUT_ROOT) -> RunResult:
    """Run one agent under <root> (transcripts/, prompts/). Raises HoError (CliChanged, CliUnavailable) before
    starting, and before writing anything into the root, when anything a launch depends on is wrong; never raises
    on an agent or CLI failure (RunResult.error / limit / fallback)."""
    root = Path(root)
    check_job(pin, model, tools_mode, effort, user_scope, run_id, extra_record)
    check_root(root, out_root)
    check_reserve(root, run_id, budget_usd)
    tdir, pdir = root / "transcripts", root / "prompts"
    transcript = tdir / f"{run_id}.jsonl"
    if transcript.exists() or (pdir / f"{run_id}.json").exists():
        raise HoError(f"run id {run_id} already has a transcript or prompts record")
    check_cwd(cwd)
    check_memory_dir(cwd, home)
    write_wrappers(root, tools_mode)
    pin_cli(root, pin)
    check_claude_version(root, pin.claude_version, tools_mode)
    env = child_env(root, tools_mode, cwd)
    argv = build_argv(system_prompt, user_prompt, schema, budget_usd, model, effort, pin.thinking_display, tools_mode)
    shown = [a if a not in (system_prompt, user_prompt) else "<prompt>" for a in argv]
    record = {"run_id": run_id, "system": system_prompt, "user": user_prompt, "schema": dict(schema), "argv": shown,
              "cwd": str(cwd), "budget_usd": budget_usd, "model": model, "effort": effort, "tools_mode": tools_mode,
              "user_scope": user_scope, "tool_values": dict(tool_values or {}), "pin": pin.as_dict(),
              "env_keys": sorted(env), "utc": now()}
    write_json(pdir / f"{run_id}.json", {**record, **(extra_record or {})})
    H.writable(transcript).parent.mkdir(parents=True, exist_ok=True)
    start, rc, err = time.monotonic(), -1, None
    with open(transcript, "w", encoding="utf-8") as out, \
            open(tdir / f"{run_id}.stderr.log", "w", encoding="utf-8") as errf:
        try:
            rc = subprocess.run(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=errf, text=True,
                                timeout=timeout_s).returncode
        except subprocess.TimeoutExpired:
            err = f"timeout after {timeout_s}s"
        except OSError as exc:
            err = f"cannot start {CLAUDE_BIN}: {exc}"
    seconds = round(time.monotonic() - start, 1)
    events = read_events(transcript)
    result = result_event(events)
    error, limit, fallback = outcome(rc, result, events, model, budget_usd, err)
    return RunResult(run_id, transcript, rc, seconds, result, error, usage_of(result, events), limit, fallback,
                     model, tools_mode)


def run_reserved(kind: str, root: Path, run_id: str, system_prompt: str, user_prompt: str,
                 schema: Mapping[str, Any], budget_usd: float, model: str, pin: CliPin, *, user_scope: str,
                 out_root: Path | str = GC.OUT_ROOT, **kw: Any) -> RunResult:
    """ledger_g.reserve (atomic budget check; BudgetRefused before anything) → launch. Any exception out of the
    launch releases the reservation when nothing ran (no transcript, no prompts record) and is raised again."""
    ledger = L.Ledger(out_root)
    ledger.reserve(kind, root, run_id, budget_usd)
    try:
        return launch(root, run_id, system_prompt, user_prompt, schema, budget_usd, model, pin,
                      user_scope=user_scope, out_root=out_root, **kw)
    except BaseException:
        ledger.release(root, run_id)
        raise
