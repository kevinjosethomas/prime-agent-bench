"""Per-trial fixture staging: the shared golden never meets ``--resume``.

The incident class this module exists to prevent (2026-09-24, the live
Rust+TS cold_open wave): scenarios passed the SHARED golden fixture path
into ``product.launch(resume_fixture=...)``; the resumed product appends
live session events to the file it resumed IN PLACE, so the shared golden
mutated mid-wave (7391 rows sha dadaec... -> 7418 rows sha 8c717...).
Every later trial silently measured against drifted bytes while its row
re-stated the golden manifest hash — nothing per-row verified the bytes
actually loaded, so ranking never refused.

Contract:
- The golden source is verified against its manifest sha256 on EVERY
  staging call, BEFORE any trial work (setup included): a polluted
  golden fails the row (FixtureSourceError) and is never overwritten
  here. The reset is explicit and outside trials — never from inside
  one — and stays the fixture owner's operation.
- The clone is a byte-exact copy staged INSIDE the product's isolated
  trial session dir — never a hardlink (an in-place append through a
  hardlink mutates the source inode) — written atomically (temp file +
  os.replace) so a product or a diagnostic never observes a torn file.
- The clone is re-hashed after the copy and must equal the golden hash:
  the row carries the ACTUAL loaded-bytes proof, not the manifest claim.
- Post-trial the clone is re-hashed again (clone_post_evidence): a
  resumed session legitimately appends to the file it resumed, so a
  changed post hash is recorded as EVIDENCE of the product's in-place
  append, never a validation failure. The pre hash is the load proof.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path


class FixtureSourceError(RuntimeError):
    """The golden fixture source failed its manifest verification."""


def sha256_bytes(data: bytes) -> str:
    """The sha256 of one byte blob."""
    return hashlib.sha256(data).hexdigest()


def count_rows(data: bytes) -> int:
    """The JSONL row count of one blob (trailing-newline safe)."""
    if not data:
        return 0
    return data.count(b"\n")


def stage_trial_fixture(golden: Path, dest: Path, manifest_sha256: str) -> dict:
    """Verify the golden against its manifest and stage the per-trial
    clone; returns the pre-launch clone evidence block
    ``{path, sha256, bytes, rows}``.

    Raises FixtureSourceError when the golden is unreadable or polluted
    (never overwrites anything: the row fails, the source stays as-is for
    the explicit out-of-trial reset)."""
    golden = Path(golden)
    try:
        data = golden.read_bytes()
    except OSError as e:
        raise FixtureSourceError(
            f"golden fixture source unreadable: {golden} ({e})") from e
    golden_sha = sha256_bytes(data)
    if golden_sha != manifest_sha256:
        raise FixtureSourceError(
            f"golden fixture source failed manifest verification: {golden} "
            f"is sha256={golden_sha} ({count_rows(data)} rows), manifest says "
            f"sha256={manifest_sha256} — the shared source is polluted or "
            "stale; reset it explicitly outside trials (bench fixtures "
            "--reset), never measure against a drifted source")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f"{dest.name}.stage-{os.getpid()}.tmp")
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, dest)
    except OSError as e:
        tmp.unlink(missing_ok=True)
        raise FixtureSourceError(f"staging clone {dest} failed: {e}") from e
    staged = Path(dest).read_bytes()
    staged_sha = sha256_bytes(staged)
    if staged_sha != golden_sha:
        # defense in depth: the copy must be byte-exact before any launch
        Path(dest).unlink(missing_ok=True)
        raise FixtureSourceError(
            f"staged clone {dest} is sha256={staged_sha}, golden is "
            f"{golden_sha}: refusing to launch a torn copy")
    return {"path": str(dest), "sha256": staged_sha,
            "bytes": len(staged), "rows": count_rows(staged)}


def clone_post_evidence(clone_path: Path) -> dict:
    """Post-trial clone state (expected drift evidence, not a failure).

    The resumed product appends live session events to the clone in
    place, so post values legitimately differ from the staged ones; the
    block records what actually happened to the loaded file. An
    unreadable clone (e.g. the trial home swept) records the error."""
    try:
        data = Path(clone_path).read_bytes()
    except OSError as e:
        return {"post_sha256": None, "post_bytes": None, "post_rows": None,
                "post_error": str(e)[:200]}
    return {"post_sha256": sha256_bytes(data), "post_bytes": len(data),
            "post_rows": count_rows(data)}
