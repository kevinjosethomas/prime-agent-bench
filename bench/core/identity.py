"""Harness run identity: every trial row names the code that measured it.

Provenance gates (audit F7/F8/F9): a canonical tree once mixed rows from
two deployed bundle versions in one trials file, and referenced runs
whose data was absent. Every row therefore carries:

- ``run``: the campaign run label (the orchestrator's run_id, or the
  sequential default timestamp) plus the per-benchmark uuid ``run_id``
  that groups one benchmark's trials from one launch;
- ``harness``: the revision identity of the harness code that produced
  the row — the deployed ``harness-identity.json`` when running from a
  sandbox bundle, else the local git revision (``unknown`` outside a
  repository), plus the deploy bundle sha256 when one exists.

The analysis layer surfaces mixed-identity results trees instead of
silently aggregating them.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import time
from pathlib import Path

from bench.core.config import REPO_ROOT

IDENTITY_FILE = "harness-identity.json"


def harness_identity(repo_root: Path = REPO_ROOT) -> dict:
    """The harness revision identity for this execution root.

    Deployed bundles carry no git tree: the orchestrator writes
    ``harness-identity.json`` next to the harness at deploy time and it is
    authoritative there. Locally, the git revision + dirty flag are.
    """
    deployed = Path(repo_root) / IDENTITY_FILE
    if deployed.exists():
        try:
            return json.loads(deployed.read_text())
        except (OSError, ValueError):
            pass
    identity = {"git_rev": "unknown", "dirty": False}
    try:
        rev = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_root,
                             capture_output=True, text=True, timeout=10)
        if rev.returncode == 0:
            identity["git_rev"] = rev.stdout.strip()
        status = subprocess.run(["git", "status", "--porcelain"], cwd=repo_root,
                                capture_output=True, text=True, timeout=10)
        identity["dirty"] = bool(status.stdout.strip()) if status.returncode == 0 else True
    except (OSError, subprocess.TimeoutExpired):
        pass
    return identity


def file_sha256(path: Path) -> str:
    """The sha256 of a file (deploy bundle integrity)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def bundle_identity(repo_root: Path, bundle_path: Path) -> dict:
    """The deploy-bundle identity: source revision + bundle sha256."""
    identity = harness_identity(repo_root)
    identity["bundle_sha256"] = file_sha256(bundle_path)
    return identity


def load_deployed_identity(repo_root: Path = REPO_ROOT) -> dict | None:
    """The deployed harness-identity.json, when this tree is a bundle."""
    deployed = Path(repo_root) / IDENTITY_FILE
    if not deployed.exists():
        return None
    try:
        return json.loads(deployed.read_text())
    except (OSError, ValueError):
        return None


def default_run_label() -> str:
    """The wall-clock campaign label used when no explicit one is given."""
    return time.strftime("%Y%m%d-%H%M%S")
