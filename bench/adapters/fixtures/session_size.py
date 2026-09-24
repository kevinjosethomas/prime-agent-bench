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
#: v3 repairs the harness-digest schema: real TS/Rust session files persist
#: hidden digests with ``display: false`` AND the raw digest in ``details``
#: (TS createHarnessDigestMessage messages.ts:141-153; Rust
#: harness_digest_prompt_row/persist_digest harness_digest.rs:117-145);
#: the v2 rows omitted both keys and the product renderers fall back to
#: visible, so all 131 digest rows rendered as visible custom panels. v2
#: stays available byte-identical: it is the recorded input of historical
#: campaign rows (golden dadaecfcac511e24...) and must never be silently
#: relabeled.
GENERATOR_V3 = "session-size/3"
#: the ``digest_display`` argument generate_rows takes per generator
#: version: None builds the bare v2 digest rows, False persists the hidden
#: product-shape rows (display + details) of v3
DIGEST_DISPLAY: dict[str, bool | None] = {GENERATOR: None, GENERATOR_V3: False}


def serialize(rows: list) -> bytes:
    """The JSONL serialization of the corpus rows."""
    return ("\n".join(json.dumps(r) for r in rows) + "\n").encode()


def build_session(size_mib: float, out_path: Path, cwd: str = FIXTURE_SESSION_CWD,
                  seed: int = 1234, generator: str = GENERATOR) -> dict:
    """Write the deterministic session fixture of exactly `size_mib` MiB.

    The recorded session cwd defaults to the canonical constant — never a
    host path — so the bytes (and the golden sha256) are identical on
    every bench root and sandbox. The directory is created so a resumed
    transcript's recorded cwd exists.

    ``generator`` selects the schema version (GENERATOR or GENERATOR_V3):
    the recorded manifest identity and the harness-digest row schema.
    The sizing probe always measures the base schema, so every version
    derives the SAME turn count and row shape for a size target (the
    10MiB corpus stays 7391 rows); the extra v3 display/details bytes
    are absorbed by the sentinel pad."""
    ensure_fixture_cwd(cwd)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    target = int(round(size_mib * (1 << 20)))
    sentinel = SENTINEL
    rng = random.Random(seed)
    digest_display = DIGEST_DISPLAY[generator]

    # stage 1: size the turn count from a 64-turn probe (per-turn bytes are
    # uniform enough for one proportional step, then exact pad closes the gap)
    probe = generate_rows(64, cwd, seed=seed)
    per_turn = len(serialize(probe)) / 64.0
    turns = max(64, int(target * 0.90 / per_turn))
    lines = generate_rows(turns, cwd, seed=seed, digest_display=digest_display)
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
            lines = generate_rows(turns, cwd, seed=seed, digest_display=digest_display)
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
        "generator": generator,
        "bytes": out_path.stat().st_size,
        "sha256": hashlib.sha256(data).hexdigest(),
        "rows": n,
        "sentinel": sentinel,
        "cwd": cwd,
        "generator_seed": seed,
        "target_mib": size_mib,
    }


class SessionSizeFixture(Fixture):
    """The canonical 10MiB session fixture, generator v2 (registry name
    session-10mib): the recorded input of all historical campaign rows —
    kept byte-identical (golden sha256 dadaecfcac511e24...); its digest
    rows omit ``display`` and render visible in the products."""

    name = "session-10mib"
    generator = GENERATOR
    filename_suffix = ""

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.size_mib = float(self.spec.get("size_mib", 10.0))
        self.seed = int(self.spec.get("seed", 1234))
        self.filename = self.spec.get(
            "filename", f"scale-corpus-{self.size_mib:g}mib{self.filename_suffix}.jsonl")
        self.manifest_name = self.spec.get(
            "manifest_name", f"manifest-{self.size_mib:g}mib{self.filename_suffix}.json")

    def path(self) -> Path:
        """The fixture file path."""
        return self.layout.fixtures / self.filename

    def generate(self, spec: dict) -> Path:
        """Build the fixture deterministically; returns its path."""
        info = build_session(float(spec.get("size_mib", self.size_mib)), self.path(),
                             seed=self.seed, generator=self.generator)
        (self.layout.fixtures / self.manifest_name).write_text(json.dumps(info, indent=1))
        return self.path()

    def ensure(self) -> dict:
        """Build if missing; returns the manifest record."""
        if not self.path().exists():
            info = build_session(self.size_mib, self.path(), seed=self.seed,
                                 generator=self.generator)
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


class SessionSizeV3Fixture(SessionSizeFixture):
    """The display-corrected 10MiB session fixture (registry name
    session-10mib-v3): the v3 schema — every harness_digest row persists
    ``display: false`` plus the raw digest in ``details`` exactly like
    real TS/Rust session files, so the digests render hidden. Same
    corpus shape as v2 (same turn count, same 7391 rows, same
    first-user text, same tail sentinel); new output file and manifest
    so v2 historical rows keep referring to their own immutable
    golden."""

    name = "session-10mib-v3"
    generator = GENERATOR_V3
    filename_suffix = "-v3"
