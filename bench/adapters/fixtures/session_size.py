"""S(10MiB): the deterministic session-size fixture.

Exact on-disk bytes per tier (probe-then-pad sizing), sha256 manifest,
visible tail sentinel. The canonical 10MiB fixture backs the scroll,
cold-open, and memory benchmarks.
"""
from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

from bench.adapters.fixtures.corpus import (FIXTURE_SESSION_CWD,
                                            append_tail_sentinel,
                                            ensure_fixture_cwd, generate_rows)
from bench.adapters.fixtures.corpus_text import _WORDS
from bench.core.fixture import Fixture

SENTINEL = "CORPUS-TAIL-9f3a1c70"
#: manifest identity: generator v2 pins the recorded session cwd to the
#: canonical constant (v1 recorded the host's absolute fixtures/work path,
#: so the bytes changed with every sandbox root)
GENERATOR = "session-size/2"


def serialize(rows: list) -> bytes:
    """The JSONL serialization of the corpus rows."""
    return ("\n".join(json.dumps(r) for r in rows) + "\n").encode()


def build_session(size_mib: float, out_path: Path, cwd: str = FIXTURE_SESSION_CWD,
                  seed: int = 1234) -> dict:
    """Write the deterministic session fixture of exactly `size_mib` MiB.

    The recorded session cwd defaults to the canonical constant — never a
    host path — so the bytes (and the golden sha256) are identical on
    every bench root and sandbox. The directory is created so a resumed
    transcript's recorded cwd exists."""
    ensure_fixture_cwd(cwd)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    target = int(round(size_mib * (1 << 20)))
    sentinel = SENTINEL
    rng = random.Random(seed)

    # stage 1: size the turn count from a 64-turn probe (per-turn bytes are
    # uniform enough for one proportional step, then exact pad closes the gap)
    probe = generate_rows(64, cwd, seed=seed)
    per_turn = len(serialize(probe)) / 64.0
    turns = max(64, int(target * 0.90 / per_turn))
    lines = generate_rows(turns, cwd, seed=seed)
    lines = append_tail_sentinel(lines, cwd, sentinel)
    data = serialize(lines)

    # stage 2: pad the sentinel row with safe single-byte chars to the exact
    # target (JSON-escape-free text: word padding then 'x' correction)
    for _ in range(6):
        delta = target - len(data)
        if delta == 0:
            break
        for row in lines:
            content = (row.get("message") or {}).get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                text = part.get("text", "")
                if "PAD_PLACEHOLDER" in text:
                    if delta > 0:
                        words = " ".join(rng.choice(_WORDS) for _ in range(delta // 6 + 2))[:delta]
                        part["text"] = "PAD_PLACEHOLDER " + words + " " + sentinel + " end of corpus."
                    else:
                        part["text"] = "PAD_PLACEHOLDER " + sentinel + " end of corpus."
        if delta < 0:
            # oversized: shrink turns proportionally and rebuild
            turns = max(1, int(turns * (target * 0.88) / len(data)))
            lines = generate_rows(turns, cwd, seed=seed)
            lines = append_tail_sentinel(lines, cwd, sentinel)
        data = serialize(lines)
    # final exact correction with unambiguous 'x'
    delta = target - len(data)
    if delta > 0:
        for row in lines:
            content = (row.get("message") or {}).get("content")
            if isinstance(content, list):
                for part in content:
                    if "PAD_PLACEHOLDER" in part.get("text", ""):
                        part["text"] = ("x" * (delta - 1)) + " " + part["text"]
        data = serialize(lines)

    out_path.write_bytes(data)
    n = 0
    with open(out_path) as f:
        for line in f:
            json.loads(line)
            n += 1
    return {
        "path": str(out_path),
        "generator": GENERATOR,
        "bytes": out_path.stat().st_size,
        "sha256": hashlib.sha256(data).hexdigest(),
        "rows": n,
        "sentinel": sentinel,
        "cwd": cwd,
        "generator_seed": seed,
        "target_mib": size_mib,
    }


class SessionSizeFixture(Fixture):
    """The canonical 10MiB session fixture (registry name session-10mib)."""

    name = "session-10mib"

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.size_mib = float(self.spec.get("size_mib", 10.0))
        self.seed = int(self.spec.get("seed", 1234))
        self.filename = self.spec.get("filename", f"scale-corpus-{self.size_mib:g}mib.jsonl")
        self.manifest_name = self.spec.get("manifest_name", f"manifest-{self.size_mib:g}mib.json")

    def path(self) -> Path:
        """The fixture file path."""
        return self.layout.fixtures / self.filename

    def generate(self, spec: dict) -> Path:
        """Build the fixture deterministically; returns its path."""
        info = build_session(float(spec.get("size_mib", self.size_mib)), self.path(),
                             seed=self.seed)
        (self.layout.fixtures / self.manifest_name).write_text(json.dumps(info, indent=1))
        return self.path()

    def ensure(self) -> dict:
        """Build if missing; returns the manifest record."""
        if not self.path().exists():
            info = build_session(self.size_mib, self.path(), seed=self.seed)
            (self.layout.fixtures / self.manifest_name).write_text(json.dumps(info, indent=1))
            print("fixture built:", info["bytes"], "bytes", info["rows"], "rows")
            return info
        ensure_fixture_cwd()  # the recorded session cwd must exist at trial time too
        return self.manifest()

    def manifest(self) -> dict:
        """The persisted build record (must exist; built by generate/ensure)."""
        return json.loads((self.layout.fixtures / self.manifest_name).read_text())

    def validate(self, expected_sha256: str) -> bool:
        """Re-hash the artifact and compare against the manifest hash."""
        data = self.path().read_bytes()
        return hashlib.sha256(data).hexdigest() == expected_sha256


GENERATOR_COMPACTED = "session-size-compacted/1"
#: the retained-window budget: the compaction boundary row keeps only
#: this many KiB of tail (a real compacted session's live suffix; the
#: captured live row kept ~99KB), so a windowed resume parses the
#: boundary suffix instead of the whole file
DEFAULT_TAIL_KIB = 100


def build_session_compacted(size_mib: float, out_path: Path,
                            cwd: str = FIXTURE_SESSION_CWD, seed: int = 1234,
                            tail_kib: int = DEFAULT_TAIL_KIB) -> dict:
    """Write the deterministic compacted-boundary session fixture.

    Same corpus generator, same seed, same exact-size discipline as
    [`build_session`], plus one byte-plausible ``compaction`` boundary
    row appended at the end (the product writer's row shape:
    ``compact_session.rs`` `compaction_entry_for` — summary,
    firstKeptEntryId, tokensBefore, details, fromHook, usage): the row's
    ``firstKeptEntryId`` pins the retained window to the last
    ``tail_kib`` of turn rows, mirroring a real compacted large session
    (the stock fixture has no compaction row, so a resumed cold open
    must parse every row — the two fixtures isolate the windowed fast
    path from the no-boundary path). The bulk pad row sits in the
    discarded prefix; the visible tail sentinel rides the retained
    tail, so the sentinel proof stays per-trial honest.
    """
    import random

    from bench.adapters.fixtures.corpus_text import _markdown_block, _paragraph, _usage, _ts

    ensure_fixture_cwd(cwd)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    target = int(round(size_mib * (1 << 20)))
    rng = random.Random(seed + 1)

    # stage 1: the same probe sizing and content rows as the stock builder
    probe = generate_rows(64, cwd, seed=seed)
    per_turn = len(serialize(probe)) / 64.0
    turns = max(64, int(target * 0.90 / per_turn))
    lines = generate_rows(turns, cwd, seed=seed)

    counter = [int(lines[-1]["id"], 16)]
    parent = lines[-1]["id"]

    def entry(entry_type, fields, index):
        nonlocal parent
        counter[0] += 1
        record = dict(fields)
        record["type"] = entry_type
        record["id"] = f"{counter[0]:08x}"[:8]
        record["parentId"] = parent
        record["timestamp"] = _ts(index)
        parent = record["id"]
        return record

    # stage 2: the discarded-prefix bulk pad row (plain 'x' run: JSON-escape
    # free, so the exact-size correction is slope-1 linear)
    pad_index = 100000
    pad_row = entry("message", {"message": {
        "role": "assistant",
        "content": [{"type": "thinking", "thinking": "corpus bulk pad"},
                    {"type": "text", "text": "x" * 8}],
        "api": "openai-completions", "provider": "prime-inference", "model": "mock-1",
        "usage": _usage(), "stopReason": "stop", "timestamp": 1789584016603 + turns,
    }}, pad_index)

    # stage 3: the retained tail (~tail_kib of follow-up turn triplets)
    tail = []
    turn = 0
    while sum(len(json.dumps(r)) + 1 for r in tail) < tail_kib * 1024:
        tail.append(entry("message", {"message": {
            "role": "user",
            "content": [{"type": "text", "text": f"please continue with follow-up task {turn}"}],
            "timestamp": 1789584016603 + turns + turn,
        }}, pad_index + 1 + 3 * turn))
        text = (_markdown_block(rng, rng.randint(2, 5)) if turn % 3 == 0
                else f"Handling follow-up {turn}. " + _paragraph(rng, rng.randint(2, 5)))
        tail.append(entry("message", {"message": {
            "role": "assistant",
            "content": [{"type": "thinking", "thinking": f"follow-up {turn}"},
                        {"type": "text", "text": text}],
            "toolCalls": [{"id": f"call_{900000 + turn:06d}", "name": "ipython",
                           "arguments": {"code": f"print({turn})"}}],
            "api": "openai-completions", "provider": "prime-inference", "model": "mock-1",
            "usage": _usage(), "stopReason": "tool_calls",
            "timestamp": 1789584016603 + turns + turn,
        }}, pad_index + 2 + 3 * turn))
        tail.append(entry("message", {"message": {
            "role": "toolResult", "toolCallId": f"call_{900000 + turn:06d}",
            "content": [{"type": "text", "text": f"follow-up result {turn}\n[0, 1, 2]\n"}],
            "isError": False, "timestamp": 1789584016603 + turns + turn,
        }}, pad_index + 3 + 3 * turn))
        turn += 1
    first_kept = tail[0]["id"]

    # stage 4: the retained tail's sentinel pair (the sentinel must render
    # from the retained window, not the discarded prefix)
    tail.append(entry("message", {"message": {
        "role": "user",
        "content": [{"type": "text", "text": "final marker request"}],
        "timestamp": 1789584016603 + turns + turn,
    }}, pad_index + 1000))
    tail.append(entry("message", {"message": {
        "role": "assistant",
        "content": [{"type": "thinking", "thinking": "final marker"},
                    {"type": "text", "text": "PAD_PLACEHOLDER " + SENTINEL + " end of corpus."}],
        "api": "openai-completions", "provider": "prime-inference", "model": "mock-1",
        "usage": _usage(), "stopReason": "stop", "timestamp": 1789584016603 + turns + turn,
    }}, pad_index + 1001))

    # stage 5: the compaction boundary row (the product writer's durable
    # shape; firstKeptEntryId pins the window at the first retained row)
    summary = (
        "## Goal\nContinue the scale-corpus workload: the session ran the "
        "deterministic corpus tasks and is being resumed after compaction.\n\n"
        "## Completed\nThe corpus generator produced the full turn sequence; "
        "earlier turns asked for numbered tasks and received tool-backed "
        "completions.\n\n## State\nNo files were modified. The retained tail "
        "carries the most recent follow-up turns and the tail sentinel."
    )
    compaction = entry("compaction", {
        "summary": summary,
        "firstKeptEntryId": first_kept,
        "tokensBefore": 183742,
        "details": {"readFiles": [], "modifiedFiles": []},
        "fromHook": False,
        "usage": _usage(),
    }, pad_index + 1002)

    rows = lines + [pad_row] + tail + [compaction]

    # stage 6: exact-size correction through the pad row's bulk run
    for _ in range(3):
        data = serialize(rows)
        delta = target - len(data)
        if delta == 0:
            break
        text = pad_row["message"]["content"][1]["text"]
        pad_row["message"]["content"][1]["text"] = text[:max(8, len(text) + delta)] if delta < 0 \
            else text + "x" * delta
    data = serialize(rows)
    if len(data) != target:
        raise ValueError(f"compacted fixture sizing: {len(data)} != {target}")

    out_path.write_bytes(data)
    retained = 0
    for line in data.decode().splitlines(keepends=True):
        if json.loads(line).get("id") == first_kept:
            break
        retained += len(line.encode())
    retained_bytes = len(data) - retained
    n = 0
    with open(out_path) as f:
        for line in f:
            json.loads(line)
            n += 1
    return {
        "path": str(out_path),
        "generator": GENERATOR_COMPACTED,
        "bytes": out_path.stat().st_size,
        "sha256": hashlib.sha256(data).hexdigest(),
        "rows": n,
        "sentinel": SENTINEL,
        "cwd": cwd,
        "generator_seed": seed,
        "target_mib": size_mib,
        "tail_kib": tail_kib,
        "first_kept_entry_id": first_kept,
        "retained_bytes": retained_bytes,
    }


class SessionSizeCompactedFixture(Fixture):
    """The compacted-boundary 10MiB session fixture (session-10mib-compacted).

    The stock fixture carries no compaction row, so a cold resume parses
    the whole file (the no-boundary path); this variant carries one
    byte-plausible compaction boundary whose retained window is the
    small tail — the two fixtures isolate the product's windowed fast
    path from the full-parse path at the same corpus size.
    """

    name = "session-10mib-compacted"

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.size_mib = float(self.spec.get("size_mib", 10.0))
        self.seed = int(self.spec.get("seed", 1234))
        self.tail_kib = int(self.spec.get("tail_kib", DEFAULT_TAIL_KIB))
        self.filename = self.spec.get("filename",
                                      f"scale-corpus-{self.size_mib:g}mib-compacted.jsonl")
        self.manifest_name = self.spec.get("manifest_name",
                                           f"manifest-{self.size_mib:g}mib-compacted.json")

    def path(self) -> Path:
        return self.layout.fixtures / self.filename

    def generate(self, spec: dict) -> Path:
        info = build_session_compacted(float(spec.get("size_mib", self.size_mib)),
                                       self.path(), seed=self.seed,
                                       tail_kib=int(spec.get("tail_kib", self.tail_kib)))
        (self.layout.fixtures / self.manifest_name).write_text(json.dumps(info, indent=1))
        return self.path()

    def ensure(self) -> dict:
        if not self.path().exists():
            self.generate(self.spec)
            return self.manifest()
        ensure_fixture_cwd()
        return self.manifest()

    def manifest(self) -> dict:
        return json.loads((self.layout.fixtures / self.manifest_name).read_text())

    def validate(self, expected_sha256: str) -> bool:
        data = self.path().read_bytes()
        return hashlib.sha256(data).hexdigest() == expected_sha256
