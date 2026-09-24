"""S(10MiB): the deterministic session-size fixture.

Exact on-disk bytes per tier (probe-then-pad sizing), sha256 manifest,
visible tail sentinel. Fixture v3 (session-10mib-v3: product-parity
harness_digest rows, display:false + details.digest) backs the scroll,
cold-open, and memory benchmarks; v2 (session-10mib) stays registered
byte-identical for historical reproducibility.
"""
from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

from bench.adapters.fixtures.corpus import (append_tail_sentinel, generate_rows)
from bench.adapters.fixtures.corpus_text import _WORDS
from bench.core.fixture import Fixture

SENTINEL = "CORPUS-TAIL-9f3a1c70"


def serialize(rows: list) -> bytes:
    """The JSONL serialization of the corpus rows."""
    return ("\n".join(json.dumps(r) for r in rows) + "\n").encode()


def build_session(size_mib: float, out_path: Path, cwd: str, seed: int = 1234,
                   digest_display: bool | None = None) -> dict:
    """Write the deterministic session fixture of exactly `size_mib` MiB.

    ``digest_display=None`` builds the v2 corpus (harness_digest rows carry
    no visibility fields); ``digest_display=False`` builds v3 (rows mirror
    the persisted product shape: display false + details.digest)."""
    target = int(round(size_mib * (1 << 20)))
    sentinel = SENTINEL
    rng = random.Random(seed)

    # stage 1: size the turn count from a 64-turn probe (per-turn bytes are
    # uniform enough for one proportional step, then exact pad closes the gap)
    probe = generate_rows(64, cwd, seed=seed, digest_display=digest_display)
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
        "bytes": out_path.stat().st_size,
        "sha256": hashlib.sha256(data).hexdigest(),
        "rows": n,
        "sentinel": sentinel,
        "generator_seed": seed,
        "target_mib": size_mib,
        "fixture_version": 3 if digest_display is not None else 2,
    }


class SessionSizeFixture(Fixture):
    """The canonical 10MiB session fixture (registry name session-10mib).

    Fixture v2: the harness_digest rows carry no visibility fields (kept
    byte-identical for historical reproducibility). The v3 corpus is the
    registry sibling session-10mib-v3 (product-parity digest rows).
    """

    name = "session-10mib"
    digest_display: bool | None = None  # None = v2 rows (no visibility fields)

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.size_mib = float(self.spec.get("size_mib", 10.0))
        self.seed = int(self.spec.get("seed", 1234))
        default_suffix = "" if self.digest_display is None else "-v3"
        self.filename = self.spec.get("filename",
                                      f"scale-corpus-{self.size_mib:g}mib{default_suffix}.jsonl")
        self.manifest_name = self.spec.get("manifest_name",
                                           f"manifest-{self.size_mib:g}mib{default_suffix}.json")

    def path(self) -> Path:
        """The fixture file path."""
        return self.layout.fixtures / self.filename

    def _build(self, size_mib: float) -> dict:
        info = build_session(size_mib, self.path(),
                             cwd=str(self.layout.fixtures / "work"), seed=self.seed,
                             digest_display=self.digest_display)
        (self.layout.fixtures / self.manifest_name).write_text(json.dumps(info, indent=1))
        print("fixture built:", self.name, info["bytes"], "bytes", info["rows"], "rows")
        return info

    def generate(self, spec: dict) -> Path:
        """Build the fixture deterministically; returns its path."""
        self._build(float(spec.get("size_mib", self.size_mib)))
        return self.path()

    def ensure(self) -> dict:
        """Build if missing; verify + regenerate if the artifact mutated.

        A resumed session APPENDS rows to the resumed file in place, so a
        shared fixture can silently grow (audit: +27 rows over 9 resumes).
        The generator is deterministic, so a mismatch regenerates the exact
        artifact instead of benchmarking a mutated corpus.
        """
        if not self.path().exists():
            return self._build(self.size_mib)
        info = self.manifest()
        if not self.validate(info.get("sha256")):
            print(f"fixture {self.name}: on-disk bytes differ from the manifest "
                  "(in-place resume appends mutate the shared artifact) — regenerating")
            return self._build(self.size_mib)
        return info

    def manifest(self) -> dict:
        """The persisted build record (must exist; built by generate/ensure)."""
        return json.loads((self.layout.fixtures / self.manifest_name).read_text())

    def validate(self, expected_sha256: str) -> bool:
        """Re-hash the artifact and compare against the manifest hash."""
        data = self.path().read_bytes()
        return hashlib.sha256(data).hexdigest() == expected_sha256


class SessionSizeV3Fixture(SessionSizeFixture):
    """Fixture v3 (registry name session-10mib-v3): the harness_digest rows
    mirror what both real products persist — ``display: false`` + the raw
    digest in ``details`` — so replay renders no digest panels, exactly
    like a real session (v2 replayed 131 panels a real session never
    shows). Same size, seed, and byte-exactness; its own golden sha."""

    name = "session-10mib-v3"
    digest_display = False
