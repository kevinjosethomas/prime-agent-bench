"""The v4 session-size fixture: one synthetic root marathon session.

A representative structural synthetic session (spec of record:
``session_v4_spec``): real Prime Agent wire schema, marathon-conditioned
row-type/role/stop-reason mixes, measured row-byte distribution, exact
10MiB closure with NO giant padded row (the anti-v3 property: v3 pads one
4.28MB tail row), a small tail sentinel, trailing lifecycle rows, and
invariants enforced at build time. All text is seeded synthetic salad;
ids/git/model values are synthetic; nothing is copied from real sessions.
"""
from __future__ import annotations

import json
import math
import random
import uuid
from pathlib import Path

from bench.adapters.fixtures import session_v4_spec as spec
from bench.adapters.fixtures.corpus_text import _WORDS
from bench.adapters.fixtures.session_size import SENTINEL, SessionSizeFixture

#: manifest identity for the v4 generator
GENERATOR_V4 = "session-size/4"
#: the canonical recorded session cwd (realistic absolute-path shape,
#: host-independent, created at build/trial time so resume semantics hold)
FIXTURE_SESSION_CWD_V4 = "/tmp/prime-agent-bench-session-v4"
#: session start (2026-09-16T00:00:00Z, unix ms); the marathon spans days
T0_MS = 1789516800000
#: the synthetic session identity (uuid-shaped, seeded)
SESSION_ID = str(uuid.uuid5(uuid.NAMESPACE_URL, "prime-agent-bench/session-v4"))
#: synthetic git context (repoUrl/commit/branch shapes, zero real data)
GIT = {"repoUrl": "https://github.com/example-org/synthetic-corpus.git",
       "commit": "9f3a1c70" + "a" * 32, "branch": "main"}
#: synthetic provider/model identity (wire-shaped, not a real route)
PROVIDER = "prime-inference"
MODEL = "synthetic/model-a"
API = "openai-completions"
#: part-size draw parameters (lognormal p50 / sigma; bytes) calibrated to
#: the marathon-conditioned row-byte reference histogram
DRAW = {
    "user_text": (620, 1.10, 13_312),
    "assistant_text": (250, 1.30, 73_728),
    "thinking": (665, 1.15, 100_000),
    "arguments": (340, 1.20, 76_800),
    "toolresult_text": (530, 1.25, 61_000),
    "signature": (110, 0.35, 400),
    "status_summary": (95, 0.55, 600),
    "cm_content": (330, 1.05, 5_000),
}
#: the 2 genuine outlier toolResults (marathon 128-256KB bucket): stdout
#: bytes drawn uniformly in this band
OUTLIER_STDOUT_BYTES = (85_000, 115_000)
#: elastic-closure budget: each elastic row absorbs at most this many
#: extra stdout bytes
ELASTIC_CHUNK_BYTES = 8_000
#: the byte cap for closure rows: the residual spreads across the mid-tail
#: buckets (8-12K) where the reference carries its dense mass, never into
#: a single row (the anti-v3 property)
ELASTIC_ROW_CAP_BYTES = 12_000
#: fraction of plain ipython results with no output at all (real no-print
#: cells persist an empty content text and omit stdout/stderr from
#: details - the measured small-row mass of real sessions)
EMPTY_STDOUT_FRACTION = 0.06
#: fraction of plain ipython results with large accumulated output
#: (5.5-12KB stdout -> 11-24KB rows: the reference's dense 11.5-27K tail)
LARGE_STDOUT_FRACTION = 0.024
#: probe/closure loop bounds
PROBE_SCALE, CLOSURE_MAX_STEPS = 8, 14


def ensure_fixture_cwd_v4(cwd: str = FIXTURE_SESSION_CWD_V4) -> None:
    """Create the recorded session cwd so resume semantics stay honest."""
    Path(cwd).mkdir(parents=True, exist_ok=True)


def _draw(rng: random.Random, kind: str) -> int:
    """A seeded lognormal byte-size draw (p50, sigma, cap) for one payload."""
    p50, sigma, cap = DRAW[kind]
    return max(16, min(cap, int(rng.lognormvariate(math.log(p50), sigma))))


def _salad(rng: random.Random, nbytes: int) -> str:
    """Exact-``nbytes`` ASCII word salad (JSON-escape-free)."""
    if nbytes <= 0:
        return ""
    out = []
    while sum(map(len, out)) + len(out) < nbytes:
        out.append(rng.choice(_WORDS))
    text = " ".join(out)
    return text[:nbytes].rstrip() + "x" * (nbytes - len(text[:nbytes].rstrip()))


def _code(rng: random.Random, nbytes: int, turn: int) -> str:
    """A synthetic ipython code cell of ~nbytes (no real code)."""
    lines = [f"rows = [f(item) for item in pool_{turn % 97}]",
             "print(sorted(rows)[:5])",
             f"total_{turn % 31} = sum(rows)"]
    while sum(map(len, lines)) + len(lines) * 2 < nbytes:
        lines.append(rng.choice([
            f"subset = [r for r in rows if r > {rng.randint(3, 900)}]",
            f"print(len(subset), subset[:{rng.randint(2, 12)}])",
            f"named_{rng.randint(0, 99)} = {{k: v for k, v in zip(rows, rows)}}",
            f"for i, r in enumerate(rows): print(i, round(r, 3))",
        ]))
    return "\n".join(lines)[:nbytes]


def rng_low(rng: random.Random) -> int:
    return rng.randint(2_000, 9_000)


def _hex(rng: random.Random, n: int) -> str:
    return "".join(rng.choice("0123456789abcdef") for _ in range(n))


def _uuid(rng: random.Random) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"v4:{_hex(rng, 16)}"))


class _Clock:
    """Deterministic wall-clock: monotonic ISO entry stamps + unix ms."""

    def __init__(self):
        self.ms = T0_MS + 1000

    def iso(self) -> str:
        return _Clock.at(self.ms)

    @staticmethod
    def at(ms: int) -> str:
        secs, rem = divmod(ms, 1000)
        import datetime
        base = datetime.datetime.fromtimestamp(secs, datetime.timezone.utc)
        return base.strftime("%Y-%m-%dT%H:%M:%S.") + f"{rem:03d}Z"


def _usage(rng: random.Random, input_tokens: int) -> dict:
    """A synthetic token-usage record (prime-inference zero-cost wire)."""
    output = rng.randint(120, 900)
    cache_read = int(input_tokens * rng.uniform(1.2, 2.2))
    total = input_tokens + output + cache_read
    return {"input": input_tokens, "output": output, "cacheRead": cache_read,
            "cacheWrite": 0, "totalTokens": total,
            "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0,
                     "total": 0}}


class _Rows:
    """Deterministic row construction on the verified product wire."""

    def __init__(self, seed: int, cwd: str):
        self.rng = random.Random(seed)
        self.cwd = cwd
        self.clock = _Clock()
        self.ids: set[str] = set()
        self.parent = None
        self.last_assistant_id = None
        self.user_count = 0
        self.rows: list[dict] = []
        self.rows_bytes: list[int] = []

    def _id(self) -> str:
        while True:
            candidate = _hex(self.rng, 8)
            if candidate not in self.ids:
                self.ids.add(candidate)
                return candidate

    def _base(self, row_type: str, payload: dict | None = None) -> dict:
        row_id = self._id()
        row = {"type": row_type, "id": row_id, "parentId": self.parent,
               "timestamp": self.clock.iso()}
        if payload:
            row.update(payload)
        self.parent = row_id
        return row

    def add(self, row_type: str, payload: dict | None = None,
            advance_ms: int = 2_500) -> dict:
        row = self._base(row_type, payload)
        self.rows.append(row)
        self.rows_bytes.append(0)  # measured at serialize time
        self.clock.ms += self.rng.randint(20, max(21, advance_ms))
        return row

    # -- session-scope lifecycle ------------------------------------------
    def header(self) -> None:
        stamp = _Clock.at(T0_MS)
        self.rows.append({"type": "session", "version": 3, "id": SESSION_ID,
                          "timestamp": stamp, "cwd": self.cwd,
                          "rlmDepth": 0, "git": dict(GIT)})
        self.rows_bytes.append(0)

    def model_change(self, model: str = MODEL) -> dict:
        return self.add("model_change", {"provider": PROVIDER, "modelId": model})

    def thinking_level_change(self) -> dict:
        return self.add("thinking_level_change", {"thinkingLevel": "off"})

    def service_tier_change(self) -> dict:
        return self.add("service_tier_change", {"serviceTier": "default"})

    def session_info(self) -> dict:
        return self.add("session_info", {"name": "marathon corpus run"})

    def git_state(self) -> dict:
        return self.add("git_state", {"git": dict(GIT)})

    def session_state(self, status: str = "active") -> dict:
        return self.add("session_state", {"state": {"status": status}})

    def agent_status(self, task_state: str) -> dict:
        summary = _salad(self.rng, _draw(self.rng, "status_summary"))
        return self.add("agent_status", {"status": {
            "summary": summary, "taskState": task_state,
            "basedOnMessageCount": len(self.rows)}})

    # -- conversation rows -------------------------------------------------
    def user(self, text: str = None, advance_ms: int = 180_000) -> dict:
        n = _draw(self.rng, "user_text") if text is None else 0
        content = [{"type": "text", "text": text if text is not None
                    else _salad(self.rng, n)}]
        ms = self.clock.ms
        row = self._base("message", {"message": {
            "role": "user", "content": content, "timestamp": ms}})
        self.rows.append(row)
        self.rows_bytes.append(0)
        self.clock.ms += self.rng.randint(20, max(21, advance_ms))
        self.user_count += 1
        if self.user_count % 8 == 0:  # the marathon spans days
            self.clock.ms += self.rng.randint(2 * 3_600_000, 6 * 3_600_000)
        return row

    def assistant(self, turn: int, stop: str, input_tokens: int,
                  calls: list | None = None) -> dict:
        rng = self.rng
        content = []
        if stop != "aborted":
            content.append({"type": "thinking",
                            "thinking": _salad(rng, _draw(rng, "thinking")),
                            "thinkingSignature": _hex(rng, _draw(rng, "signature"))})
        if stop in ("stop", "aborted", "error"):
            content.append({"type": "text",
                            "text": _salad(rng, _draw(rng, "assistant_text"))})
        for name, args in (calls or []):
            content.append({"type": "toolCall", "id": _uuid(rng),
                            "name": name, "arguments": args})
        message = {"role": "assistant", "content": content, "api": API,
                   "provider": PROVIDER, "model": MODEL}
        if rng.random() < 0.5:
            message["responseId"] = "resp_" + _hex(rng, 16)
        message["usage"] = _usage(rng, input_tokens)
        message["stopReason"] = stop
        if stop == "error":
            message["errorMessage"] = "synthetic provider error " + _hex(rng, 8)
        message["timestamp"] = self.clock.ms
        row = self._base("message", {"message": message})
        self.rows.append(row)
        self.rows_bytes.append(0)
        self.last_assistant_id = row["id"]
        self.clock.ms += self.rng.randint(40, 60_000)
        return row

    def tool_result(self, call_id: str, stdout: str, is_error: bool = False,
                    tool_name: str = "ipython") -> dict:
        rng = self.rng
        duration = int(min(spec.TOOL_DURATION_MS["max"],
                          rng.lognormvariate(3.66, 2.6) * 1000)) // 10 * 10
        details = {"durationMs": duration,
                   "status": "error" if is_error else "ok"}
        if tool_name == "ipython":
            details["kernelRestarted"] = False
        if is_error:
            details["error"] = {"ename": "SyntheticError",
                                "evalue": _salad(rng, 60),
                                "traceback": ["Traceback (synthetic):",
                                              _salad(rng, 120)]}
            details["errorEname"] = "SyntheticError"
        elif tool_name == "ipython" and stdout:
            details["stdout"] = stdout
            details["stderr"] = ""
        else:
            details["exitCode"] = 0
        message = {"role": "toolResult", "toolCallId": call_id,
                   "toolName": tool_name,
                   "content": [{"type": "text", "text": stdout}],
                   "details": details, "isError": is_error,
                   "timestamp": self.clock.ms}
        row = self._base("message", {"message": message})
        self.rows.append(row)
        self.rows_bytes.append(0)
        self.clock.ms += self.rng.randint(20, 4_000)
        return row

    def stdout(self) -> str:
        return _salad(self.rng, _draw(self.rng, "toolresult_text"))

    def sentinel_turn(self) -> dict:
        """The final small assistant reply carrying the tail sentinel."""
        message = {"role": "assistant",
                   "content": [{"type": "text",
                                "text": f"All work complete. {SENTINEL} end of corpus."}],
                   "api": API, "provider": PROVIDER, "model": MODEL,
                   "usage": _usage(self.rng, rng_low(self.rng)),
                   "stopReason": "stop", "timestamp": self.clock.ms}
        row = self._base("message", {"message": message})
        self.rows.append(row)
        self.rows_bytes.append(0)
        self.last_assistant_id = row["id"]
        self.clock.ms += self.rng.randint(20, 2_000)
        return row


    # -- custom_message rows (synthetic content; marathon type mix) ------
    def _custom_message(self, custom_type: str, content: str, display: bool,
                        details: dict | None = None) -> dict:
        payload = {"customType": custom_type, "content": content,
                   "display": display}
        if details is not None:
            payload["details"] = details
        return self.add("custom_message", payload, advance_ms=1_500)

    def heartbeat_prompt(self, run: int) -> dict:
        prompt = _salad(self.rng, self.rng.randint(250, 450))
        return self._custom_message(
            "heartbeat_prompt",
            f"[heartbeat: */20 * * * * * run#{run}]\n\n{prompt}", True,
            {"jobId": _uuid(self.rng), "schedule": "*/20 * * * * *",
             "status": "active", "runCount": run,
             "nextRunAt": self.clock.iso(),
             "lastRunAt": self.clock.iso()})

    def agent_message(self) -> dict:
        content = _salad(self.rng, self.rng.randint(320, 480))
        return self._custom_message(
            "agent_message", content, True,
            {"from": {"activeSessionId": _hex(self.rng, 12),
                      "runtimeKind": "subagent",
                      "sessionId": _uuid(self.rng)},
             "fromRelationship": "child",
             "id": "agentmsg_" + _hex(self.rng, 12), "message": content,
             "target": {"activeSessionId": _hex(self.rng, 12),
                        "runtimeKind": "top-level",
                        "sessionId": SESSION_ID}})

    def harness_digest(self) -> dict:
        digest = _salad(self.rng,
                        self.rng.randint(*spec.MARATHON_HARNESS_DIGEST_BYTES))
        return self._custom_message(
            "harness_digest", f"[harness-digest] {digest}", False,
            {"digest": digest, "stateFingerprint": _hex(self.rng, 64)})

    def async_bash_completion(self) -> dict:
        pid = self.rng.randint(20_000, 90_000)
        command = f"git -C synth-{self.rng.randint(1, 999)} log --oneline -20"
        return self._custom_message(
            "async_bash_completion",
            f"[bash-done pid:{pid} exit:0] {command}", True,
            {"pid": pid, "command": command, "exitCode": 0})

    def goal_context(self) -> dict:
        return self._custom_message(
            "goal_context",
            "[goal: continuation]\n\n" + _salad(self.rng, self.rng.randint(300, 600)),
            True, {"goalId": _uuid(self.rng), "kind": "continuation",
                   "objective": _salad(self.rng, 80)})

    def refinement_notice(self) -> dict:
        return self._custom_message(
            "refinement_notice", _salad(self.rng, self.rng.randint(200, 450)),
            True, {"refinementId": _uuid(self.rng), "kind": "notice"})

    def refinement_outcome(self) -> dict:
        return self._custom_message(
            "refinement_outcome", _salad(self.rng, self.rng.randint(200, 450)),
            True, {"refinementId": _uuid(self.rng), "outcome": "applied"})

    def rlm_child_terminal_notice(self, name: str) -> dict:
        return self._custom_message(
            "rlm_child_terminal_notice",
            f"child {name} completed: " + _salad(self.rng, 90),
            True, {"childId": _uuid(self.rng), "name": name,
                   "status": "completed"})

    def rlm_child_failure(self, name: str) -> dict:
        return self._custom_message(
            "rlm_child_failure", f"child {name} failed: " + _salad(self.rng, 120),
            True, {"childId": _uuid(self.rng), "name": name, "status": "error"})

    def ipython_state(self) -> dict:
        return self._custom_message(
            "ipython_state", "kernel state snapshot: " + _salad(self.rng, 120),
            False, {"variables": self.rng.randint(4, 120),
                    "imports": self.rng.randint(2, 30)})

    def ipython_state_restored(self) -> dict:
        return self._custom_message(
            "ipython_state_restored",
            "kernel state restored from checkpoint " + _hex(self.rng, 12), True,
            {"checkpointId": _uuid(self.rng)})

    def update_restart(self) -> dict:
        old, new = f"0.9.{self.rng.randint(1, 9)}", f"0.9.{self.rng.randint(10, 20)}"
        return self._custom_message(
            "update_restart", f"agent updated: {old} -> {new}; restart pending",
            True, {"from": old, "to": new})

    def worker_recovery(self) -> dict:
        return self._custom_message(
            "worker_recovery", "worker recovered after crash", True,
            {"workerId": _hex(self.rng, 12)})

    def provider_retry_outcome(self) -> dict:
        return self._custom_message(
            "provider_retry_outcome",
            f"Recovered after {self.rng.randint(2, 5)} retries: "
            + _salad(self.rng, 60), True,
            {"success": True, "attempts": self.rng.randint(2, 5),
             "finalError": _salad(self.rng, 50)})

    def slash(self) -> dict:
        return self._custom_message(
            "slash", "/model synthetic/model-a", True, {"command": "/model"})

    # -- custom (cloud/sandbox lifecycle), compaction, child usage -------
    def custom(self) -> dict:
        return self.add("custom", {"customType": "cloud.sandbox.lifecycle",
                                   "data": {"cloudSessionId": _uuid(self.rng),
                                            "generation": self.rng.randint(1, 9),
                                            "sandboxId": _hex(self.rng, 24)}})

    def compaction(self) -> dict:
        summary = _salad(self.rng,
                         self.rng.randint(*spec.MARATHON_COMPACTION_SUMMARY_BYTES))
        read = [f"src/synthetic/mod_{i}.py" for i in
                range(self.rng.randint(3, 6))]
        modified = [f"src/synthetic/mod_{i}.py" for i in
                    range(self.rng.randint(0, 3))]
        return self.add("compaction", {
            "summary": summary, "firstKeptEntryId": None,
            "tokensBefore": self.rng.randint(*spec.MARATHON_COMPACTION_TOKENS_BEFORE),
            "details": {"readFiles": read, "modifiedFiles": modified},
            "harnessDigest": _salad(self.rng,
                                   self.rng.randint(*spec.MARATHON_COMPACTION_DIGEST_BYTES))},
            advance_ms=30_000)

    def child_usage(self) -> dict:
        def cost(usage):
            rate = 0.00000012
            usage["cost"] = {"input": usage["input"] * rate,
                             "output": usage["output"] * rate,
                             "cacheRead": 0, "cacheWrite": 0,
                             "total": (usage["input"] + usage["output"]) * rate}
            return usage
        child = cost(_usage(self.rng, self.rng.randint(5_000, 30_000)))
        aggregate = cost(_usage(self.rng, self.rng.randint(40_000, 120_000)))
        return self.add("child_usage_attributed", {
            "targetId": None, "childUsage": child, "aggregateUsage": aggregate,
            "origin": "spawn_task"})


# -- composition (one deterministic pass; parents/timestamps in order) ----------

def _plan_counts(n_rows: int) -> dict:
    """Exact integer row counts realizing the marathon mix at ``n_rows``."""
    counts = {k: int(round(s * n_rows))
              for k, s in spec.MARATHON_ROW_TYPE_MIX.items()}
    counts.update({"session": 1, "session_info": 1, "git_state": 1,
                   "thinking_level_change": 1, "service_tier_change": 1,
                   "model_change": spec.MARATHON_MODEL_CHANGE_ROWS,
                   "compaction": max(1, round(n_rows / 687))})
    return counts


def _custom_message_types(count: int, rng: random.Random) -> list:
    """The custom_message type list (marathon mix, largest-remainder)."""
    weights = {}
    measured = sum(spec.MARATHON_CUSTOM_MESSAGE_COUNTS.values())
    measured_share = 1 - sum(spec.MARATHON_CUSTOM_MESSAGE_REMAINDER.values())
    for kind, cnt in spec.MARATHON_CUSTOM_MESSAGE_COUNTS.items():
        weights[kind] = cnt / measured * measured_share
    weights.update(spec.MARATHON_CUSTOM_MESSAGE_REMAINDER)
    weights.pop("harness_digest")  # digests are fixed-count
    raw = {k: count * w for k, w in weights.items()}
    plan = {k: int(v) for k, v in raw.items()}
    order = sorted(raw, key=lambda k: (-(raw[k] - plan[k]), k))
    for k in order[:count - sum(plan.values())]:
        plan[k] += 1
    digest_rows = max(1, round(count / 85))
    plan["harness_digest"] = min(spec.MARATHON_HARNESS_DIGEST_ROWS, digest_rows) if count < 340 else spec.MARATHON_HARNESS_DIGEST_ROWS
    types = [k for k, n in plan.items() for _ in range(n)]
    rng.shuffle(types)
    return types


def _distribute(total: int, buckets: int) -> list:
    """Near-equal deterministic split of ``total`` into ``buckets`` parts."""
    base, extra = divmod(total, max(1, buckets))
    return [base + (1 if i < extra else 0) for i in range(max(1, buckets))]


def _compose(seed: int, cwd: str, n_rows: int) -> tuple:
    """The full v4 row list in final order (one pass, no post-merge).

    Returns (rows, elastic): elastic is the list of plain toolResult row
    indexes (in final order) eligible for exact-size closure padding.
    """
    rows = _Rows(seed, cwd)
    rng = rows.rng
    counts = _plan_counts(n_rows)
    n_msg = counts["message"]
    n_cycles = max(2, round(n_msg * spec.MARATHON_ROLE_MIX["user"]))
    n_asst_total = max(8, round(n_msg * spec.MARATHON_ROLE_MIX["assistant"]))
    n_tool = max(8, round(n_msg * spec.MARATHON_ROLE_MIX["toolResult"]))
    n_tooluse = round(n_asst_total * spec.MARATHON_STOP_REASON_MIX["toolUse"])
    n_stop = round(n_asst_total * spec.MARATHON_STOP_REASON_MIX["stop"])
    n_err = max(1, round(n_asst_total * spec.MARATHON_STOP_REASON_MIX["error"]))
    n_abort = max(0, n_asst_total - n_tooluse - n_stop - n_err)
    kinds = (["toolUse"] * n_tooluse + ["stop"] * n_stop
             + ["error"] * n_err + ["aborted"] * n_abort)
    rng.shuffle(kinds)
    stops = [i for i, k in enumerate(kinds) if k == "stop"]
    if stops and kinds[-1] != "stop":  # the final row is the sentinel stop
        kinds[stops[-1]], kinds[-1] = kinds[-1], kinds[stops[-1]]
    n_iserr = max(1, round(n_tool * spec.MARATHON_IS_ERROR_SHARE))
    n_big = max(1, round(n_rows / 2050))
    result_kinds = (["ok"] * (n_tool - n_iserr - n_big)
                    + ["error"] * n_iserr + ["big"] * n_big)
    rng.shuffle(result_kinds)
    two_call = max(0, n_tool - n_tooluse)
    bash_at = {n_tooluse // 4, 3 * n_tooluse // 4}

    rows.header()
    rows.session_info()
    rows.model_change()
    rows.thinking_level_change()
    rows.service_tier_change()
    rows.git_state()

    cm_types = _custom_message_types(counts["custom_message"], rng)
    wakes = [t for t in cm_types if t in ("heartbeat_prompt", "agent_message")]
    overlay_kinds = ([t for t in cm_types
                      if t not in ("heartbeat_prompt", "agent_message")]
                     + ["custom"] * counts["custom"]
                     + ["agent_status"] * (counts["agent_status"] - 1)
                     + ["session_state"] * (counts["session_state"] - 1)
                     + ["child_usage_attributed"] * counts["child_usage_attributed"]
                     + ["compaction"] * counts["compaction"]
                     + ["model_change"] * (spec.MARATHON_MODEL_CHANGE_ROWS - 1))
    rng.shuffle(overlay_kinds)

    # per-cycle shares (the final cycle only carries the sentinel turn)
    n_cycles_main = n_cycles - 1
    asst_units = _distribute(n_asst_total - 1, n_cycles_main)
    wake_units = _distribute(len(wakes), n_cycles_main)
    overlay_units = _distribute(len(overlay_kinds), n_cycles_main)
    token_step = max(1, 1_400_000 // max(1, n_asst_total))
    tooluse_seen = emitted = 0
    elastic = []

    def emit_overlay(kind: str) -> None:
        if kind == "custom":
            rows.custom()
        elif kind == "agent_status":
            rows.agent_status(rng.choice(["needs_input", "completed", "error"]))
        elif kind == "session_state":
            rows.session_state("active")
        elif kind == "compaction":
            c = rows.compaction()
            c["firstKeptEntryId"] = rows.rows[len(rows.rows) - 2]["id"]
        elif kind == "child_usage_attributed":
            if rows.last_assistant_id:
                u = rows.child_usage()
                u["targetId"] = rows.last_assistant_id
        elif kind == "model_change":
            rows.model_change("synthetic/model-b")
        else:
            if kind == "rlm_child_terminal_notice":
                rows.rlm_child_terminal_notice(f"synth-worker-{rng.randint(1, 40)}")
            elif kind == "rlm_child_failure":
                rows.rlm_child_failure(f"synth-worker-{rng.randint(1, 40)}")
            else:
                getattr(rows, kind)()

    for cycle in range(n_cycles_main):
        rows.user()
        cycle_asst = kinds[emitted:emitted + asst_units[cycle]]
        cycle_wakes = wakes[:wake_units[cycle]]
        del wakes[:wake_units[cycle]]
        cycle_overlays = overlay_kinds[:overlay_units[cycle]]
        del overlay_kinds[:overlay_units[cycle]]
        wake_i = overlay_i = 0
        for j, kind in enumerate(cycle_asst):
            tokens = 20_000 + emitted * token_step // 2 + rng.randint(0, 8_000)
            if kind != "toolUse":
                rows.assistant(cycle, kind, tokens)
            else:
                n_calls = 2 if two_call > 0 else 1
                two_call = max(0, two_call - 1)
                calls = []
                for c in range(n_calls):
                    if tooluse_seen in bash_at and c == 0:
                        calls.append(("bash", {"command": _salad(rng, rng.randint(80, 250))}))
                    else:
                        calls.append(("ipython", {"code": _code(rng, _draw(rng, "arguments"), tooluse_seen)}))
                row = rows.assistant(cycle, "toolUse", tokens, calls)
                for part in [q for q in row["message"]["content"] if q["type"] == "toolCall"]:
                    rkind = result_kinds.pop(0) if result_kinds else "ok"
                    stdout = (_salad(rng, rng.randint(*OUTLIER_STDOUT_BYTES))
                              if rkind == "big" else rows.stdout())
                    if rkind == "ok" and part["name"] == "ipython":
                        if rng.random() < EMPTY_STDOUT_FRACTION:
                            stdout = ""
                        elif rng.random() < LARGE_STDOUT_FRACTION:
                            stdout = _salad(rng, rng.randint(6_500, 13000))
                    result = rows.tool_result(part["id"], stdout,
                                               is_error=(rkind == "error"),
                                               tool_name=part["name"])
                    if rkind == "ok" and part["name"] == "ipython":
                        elastic.append(len(rows.rows) - 1)
                tooluse_seen += 1
            emitted += 1
            if wake_i < len(cycle_wakes) and j % 3 == 2:
                t = cycle_wakes[wake_i]
                rows.heartbeat_prompt(cycle) if t == "heartbeat_prompt" else rows.agent_message()
                wake_i += 1
            if overlay_i < len(cycle_overlays) and j % 2 == 1:
                emit_overlay(cycle_overlays[overlay_i])
                overlay_i += 1
        for t in cycle_wakes[wake_i:]:
            rows.heartbeat_prompt(cycle) if t == "heartbeat_prompt" else rows.agent_message()
        for kind in cycle_overlays[overlay_i:]:
            emit_overlay(kind)

    # the sentinel turn: small final user request + small assistant reply
    rows.user(text="final marker request")
    rows.sentinel_turn()
    rows.agent_status("completed")
    rows.session_state("active")
    return rows.rows, elastic


# -- serialization, exact-size closure, invariants, build ----------------------

def _serialize(rows: list) -> tuple:
    """JSONL bytes plus per-row byte sizes (line + newline)."""
    lines = [json.dumps(row) for row in rows]
    data = ("\n".join(lines) + "\n").encode()
    return data, [len(line) + 1 for line in lines]


def _elastic_close(rows: list, sizes: list, elastic: list, target: int,
                   seed: int) -> None:
    """Close the exact byte gap with NO giant row: spread the residual
    stdout bytes across the last plain toolResult rows, each row staying
    under the marathon p99 row cap (the documented representative tier).
    Every appended stdout byte lands twice on the wire (content text +
    details.stdout, the real product duplication)."""
    rng = random.Random(seed ^ 0xC105E)
    delta = target - sum(sizes)
    for i in reversed(elastic):
        if delta <= 1:
            break
        row = rows[i]
        if row["message"].get("details", {}).get("stdout") is None:
            continue  # empty-output cells stay empty (real no-print rows)
        room = ELASTIC_ROW_CAP_BYTES - sizes[i]
        take = min(delta // 2, ELASTIC_CHUNK_BYTES // 2, max(0, room // 2))
        if take <= 0:
            continue
        extra = " " + _salad(rng, take - 1)
        part = row["message"]["content"][0]
        part["text"] = part["text"] + extra
        row["message"]["details"]["stdout"] += extra
        sizes[i] += 2 * len(extra)
        delta -= 2 * len(extra)
    if delta == 1:  # exact single byte: extend one existing "" stderr
        for i in reversed(elastic):
            if rows[i]["message"]["details"].get("stderr") == "":
                rows[i]["message"]["details"]["stderr"] = "x"
                delta -= 1
                break
    if delta != 0:
        raise AssertionError(f"elastic closure left delta {delta}")


def _row_stats(rows: list, sizes: list) -> dict:
    """The realized structural distribution (manifest evidence + gates)."""
    types: dict = {}
    roles: dict = {}
    stops: dict = {}
    calls = results = errors = 0
    user_turns = 0
    for row, size in zip(rows, sizes):
        types[row["type"]] = types.get(row["type"], 0) + 1
        if row["type"] != "message":
            continue
        message = row["message"]
        roles[message["role"]] = roles.get(message["role"], 0) + 1
        if message["role"] == "assistant":
            stops[message["stopReason"]] = stops.get(message["stopReason"], 0) + 1
            calls += sum(1 for p in message["content"] if p["type"] == "toolCall")
        elif message["role"] == "toolResult":
            results += 1
            errors += 1 if message["isError"] else 0
        elif message["role"] == "user":
            user_turns += 1
    total = len(rows)
    top = sorted(sizes, reverse=True)[:max(1, total // 1000)]
    return {
        "rows": total,
        "row_type_counts": types,
        "role_counts": roles,
        "stop_reason_counts": stops,
        "toolcalls": calls, "tool_results": results,
        "is_error_results": errors, "user_turns": user_turns,
        "row_bytes": {q: int(spec.quantile(sizes, f))
                      for q, f in (("p50", .50), ("p75", .75),
                                   ("p90", .90), ("p99", .99))},
        "max_row_bytes": max(sizes),
        "ks_distance_marathon": round(spec.ks_distance(sizes), 4),
        "top_001pct_byte_share": round(sum(top) / sum(sizes), 4),
        "compactions": types.get("compaction", 0),
        "harness_digest_rows": 0,
    }


def _check_invariants(rows: list, data: bytes, sizes: list, target: int,
                      size_mib: float, stats: dict) -> None:
    """Fail loudly on any structural violation (robust generator
    invariants; the test suite re-derives the same gates from the file)."""
    if len(data) != target:
        raise AssertionError(f"size {len(data)} != target {target}")
    lines = data.decode().split("\n")
    if lines[-1] != "" or len(lines) - 1 != len(rows):
        raise AssertionError("trailing newline / row count mismatch")
    parsed = [json.loads(line) for line in lines[:-1]]
    if parsed[0]["type"] != "session" or not all(r["id"] for r in parsed):
        raise AssertionError("header/ids malformed")
    if sum(1 for r in parsed if r["type"] == "session") != 1:
        raise AssertionError("not exactly one session header")
    seen: set = set()
    previous = None
    last_ts = None
    calls, results = {}, {}
    for row in parsed:
        if row["type"] != "session":
            if row["parentId"] != previous:
                raise AssertionError(f"parent chain broken at {row['id']}")
            previous = row["id"]
        if row["id"] in seen:
            raise AssertionError(f"duplicate id {row['id']}")
        seen.add(row["id"])
        if last_ts is not None and row["timestamp"] <= last_ts:
            raise AssertionError("timestamps not strictly increasing")
        last_ts = row["timestamp"]
        if row["type"] == "message":
            if row["message"]["role"] == "assistant":
                for part in row["message"]["content"]:
                    if part["type"] == "toolCall":
                        calls[part["id"]] = row
            elif row["message"]["role"] == "toolResult":
                results[row["message"]["toolCallId"]] = row
    if set(calls) != set(results):
        raise AssertionError("toolcall/toolResult pairing violated")
    order = {cid: parsed.index(row) for cid, row in calls.items()}
    for cid, row in results.items():
        if parsed.index(row) < order[cid]:
            raise AssertionError(f"result precedes call {cid}")
    # row-size tiers (the measured marathon tiers: p99 21,291 with a real
    # lognormal tail through the 23-128K buckets, then the documented
    # 128-256K outlier bucket, then NOTHING up to the ~1.05MB ceiling row
    # this sample size does not need)
    big = 0
    for size, row in zip(sizes, parsed):
        if size > spec.CAP_OUTLIER_ROW_BYTES:
            raise AssertionError(f"row exceeds outlier cap: {size}")
        if row["type"] == "compaction" and size > 26_000:
            raise AssertionError("compaction row too big")
        if size > 128 * 1024:
            big += 1
    if big != spec.MARATHON_OUTLIER_ROWS_128K_256K:
        raise AssertionError(f"expected 2 outlier-tier rows, found {big}")
    # sentinel: small, in the last assistant text, file ends non-message
    last_asst = [r for r in parsed
                 if r["type"] == "message"
                 and r["message"]["role"] == "assistant"][-1]
    asst_size = sizes[parsed.index(last_asst)]
    texts = [p["text"] for p in last_asst["message"]["content"] if p["type"] == "text"]
    if SENTINEL not in "".join(texts) or asst_size > spec.SENTINEL_ROW_MAX_BYTES:
        raise AssertionError("tail sentinel missing or too big")
    if parsed[-1]["type"] == "message":
        raise AssertionError("file ends on a message row")
    if len(rows) >= 1000:
        _check_distribution(stats, size_mib)


def _check_distribution(stats: dict, size_mib: float) -> None:
    """The distribution gates vs the marathon spec of record."""
    total = stats["rows"]
    mix = {k: v / total for k, v in stats["row_type_counts"].items()}
    l1 = sum(abs(mix.get(k, 0) - s)
             for k, s in spec.MARATHON_ROW_TYPE_MIX.items())
    l1 += sum(abs(mix.get(k, 0) - 0) for k in mix if k not in spec.MARATHON_ROW_TYPE_MIX)
    if l1 > spec.MIX_L1_MAX:
        raise AssertionError(f"row-type mix L1 {l1:.4f} > {spec.MIX_L1_MAX}")
    messages = sum(stats["role_counts"].values())
    for role, share in spec.MARATHON_ROLE_MIX.items():
        if abs(stats["role_counts"].get(role, 0) / messages - share) > spec.ROLE_SHARE_TOL:
            raise AssertionError(f"role mix off: {role}")
    if stats["ks_distance_marathon"] > spec.KS_D_MAX:
        raise AssertionError(f"KS D {stats['ks_distance_marathon']} > {spec.KS_D_MAX}")
    if stats["top_001pct_byte_share"] > spec.TOP_P001_BYTE_SHARE_MAX:
        raise AssertionError("top-0.1% rows carry too many bytes")
    if stats["is_error_results"] < 1 or stats["is_error_results"] / stats["tool_results"] > 0.01:
        raise AssertionError("isError share out of band")
    if not (spec.MARATHON_COMPACTIONS_10MIB_BAND[0] <= stats["compactions"]
            <= spec.MARATHON_COMPACTIONS_10MIB_BAND[1] * 2):
        raise AssertionError("compaction count out of band")
    for q, tol in spec.QUANTILE_LOG2_TOL.items():
        realized = stats["row_bytes"][q]
        anchor = spec.MARATHON_ROW_BYTES[q]
        import math as _m
        if abs(_m.log2(realized) - _m.log2(anchor)) > tol:
            raise AssertionError(f"row-byte {q} drift: {realized} vs {anchor}")
    if abs(size_mib - 10.0) < 1e-9:
        if not (spec.ROW_COUNT_BAND_10MIB[0] <= total <= spec.ROW_COUNT_BAND_10MIB[1]):
            raise AssertionError(f"row count {total} outside the 10MiB band")


def build_session_v4(size_mib: float, out_path: Path,
                     cwd: str = FIXTURE_SESSION_CWD_V4, seed: int = 1234,
                     generator: str = GENERATOR_V4) -> dict:
    """Write the representative synthetic session of exactly ``size_mib``
    MiB (10MiB default tier) and return its manifest record.

    Deterministic: same ``seed`` and ``size_mib`` produce byte-identical
    output from any host path (the recorded cwd is the canonical constant,
    never a host path; the directory is created so resume holds). The
    canonical fixture seed is 1234 (the sizing loop is calibrated for it;
    arbitrary seeds are not a supported surface)."""
    ensure_fixture_cwd_v4(cwd)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    target = int(round(size_mib * (1 << 20)))
    n_rows = max(16, int(spec.MARATHON_ROWS_PER_10MIB * size_mib / 10.0))
    rows = elastic = sizes = data = None
    for _ in range(CLOSURE_MAX_STEPS):
        rows, elastic = _compose(seed, cwd, n_rows)
        data, sizes = _serialize(rows)
        delta = target - len(data)
        avg = len(data) / max(1, len(rows))
        # damped proportional steps: composition cost per row varies with
        # the seeded realization, so both directions undershoot deliberately
        if delta < 0:
            n_rows = max(16, n_rows - max(1, int(-delta / avg * 1.2)))
            continue
        if delta > avg * 80:
            n_rows = max(16, n_rows + max(1, int(delta / avg * 0.85)))
            continue
        _elastic_close(rows, sizes, elastic, target, seed)
        data, sizes = _serialize(rows)
        break
    else:
        raise AssertionError("sizing loop did not converge")
    stats = _row_stats(rows, sizes)
    stats["harness_digest_rows"] = sum(
        1 for r in rows if r["type"] == "custom_message"
        and r.get("customType") == "harness_digest")
    _check_invariants(rows, data, sizes, target, size_mib, stats)
    out_path.write_bytes(data)
    n_rows_final = sum(1 for _ in open(out_path, "rb"))
    return {
        "path": str(out_path), "generator": generator,
        "bytes": len(data), "rows": n_rows_final, "seed": seed,
        "sentinel": SENTINEL, "cwd": cwd, "target_mib": size_mib,
        "sha256": __import__("hashlib").sha256(data).hexdigest(),
        "distribution": stats,
    }


class SessionSizeV4Fixture(SessionSizeFixture):
    """The representative 10MiB session fixture (registry name
    session-10mib-v4): the marathon-conditioned structural synthetic
    corpus behind the representative benchmarks. v2 stays the recorded
    input of historical rows; v3 stays the pathological stress corpus."""

    name = "session-10mib-v4"
    generator = GENERATOR_V4
    filename_suffix = "-v4"

    def generate(self, build_spec: dict) -> Path:
        info = build_session_v4(
            float(build_spec.get("size_mib", self.size_mib)), self.path(),
            cwd=FIXTURE_SESSION_CWD_V4, seed=self.seed)
        (self.layout.fixtures / self.manifest_name).write_text(json.dumps(info, indent=1))
        return self.path()

    def ensure(self) -> dict:
        if not self.path().exists():
            info = build_session_v4(self.size_mib, self.path(),
                                    cwd=FIXTURE_SESSION_CWD_V4, seed=self.seed)
            (self.layout.fixtures / self.manifest_name).write_text(json.dumps(info, indent=1))
            print("fixture built:", info["bytes"], "bytes", info["rows"], "rows")
            return info
        ensure_fixture_cwd_v4()
        return self.manifest()
