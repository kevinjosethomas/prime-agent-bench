"""TREE(n, active, depth): a deterministic subagent session tree.

Generates a session tree like a real fan-out would leave on disk: a root
session plus n nested subagent session files across `depth` levels under
.rlm/sessions/, `active` of them mid-flight (no final tool result).
Manifest-hashed for byte reproducibility.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from bench.adapters.fixtures.corpus import (FIXTURE_SESSION_CWD,
                                            ensure_fixture_cwd, generate_rows)
from bench.core.fixture import Fixture

#: manifest identity: generator v2 pins the recorded session cwd (v1
#: recorded the host's absolute fixtures/work path)
GENERATOR = "subagent-tree/2"


def _row(entry_type: str, fields: dict, entry_id: str, parent: str | None,
         index: int) -> dict:
    """One session row (chain-linked, deterministic timestamp)."""
    record = dict(fields)
    record["type"] = entry_type
    record["id"] = entry_id
    record["parentId"] = parent
    record["timestamp"] = "2026-09-16T19:%02d:%02d.%03dZ" % (index % 60, (index * 7) % 60, index % 1000)
    return record


def _subagent_rows(node_id: str, level: int, index: int, active: bool, cwd: str) -> list:
    """One subagent session file's rows (mid-flight if active)."""
    rows = [{
        "type": "session",
        "id": node_id,
        "version": 3,
        "timestamp": "2026-09-16T19:00:00.000Z",
        "cwd": cwd,
        "rlmDepth": level,
    }]
    task = _row("message",
                {"message": {"role": "user",
                             "content": [{"type": "text", "text": f"subtask {index} at depth {level}"}],
                             "timestamp": 1789584016603}},
                f"{node_id}u1", None, 1)
    rows.append(task)
    assistant = _row("message",
                     {"message": {"role": "assistant",
                                  "content": [{"type": "thinking", "thinking": f"subtask {index}"},
                                              {"type": "text", "text": f"Working on subtask {index}."}],
                                  "toolCalls": [{"id": f"call_{node_id}", "name": "ipython",
                                                 "arguments": {"code": f"print('sub-{index}-{level}')"}}],
                                  "api": "openai-completions", "provider": "prime-inference",
                                  "model": "mock-1", "usage": {"input": 10, "output": 2, "cacheRead": 0,
                                                               "cacheWrite": 0, "totalTokens": 12,
                                                               "cost": {"total": 0.0}},
                                  "stopReason": "tool_calls", "timestamp": 1789584016603}},
                     f"{node_id}a1", task["id"], 2)
    rows.append(assistant)
    if not active:
        rows.append(_row("message",
                          {"message": {"role": "toolResult", "toolCallId": f"call_{node_id}",
                                       "content": [{"type": "text", "text": f"sub-{index}-{level}\n"}],
                                       "isError": False, "timestamp": 1789584016603}},
                          f"{node_id}t1", assistant["id"], 3))
    return rows


def level_counts(n: int, depth: int) -> list[int]:
    """Distribute n subagents across depth levels (deterministic)."""
    base, extra = divmod(n, depth)
    return [base + (1 if i < extra else 0) for i in range(depth)]


def write_tree(out_dir: Path, n: int, active: int, depth: int, seed: int,
               cwd: str = FIXTURE_SESSION_CWD) -> dict:
    """Write the session tree; returns its manifest.

    The recorded session cwd defaults to the canonical constant — never a
    host path — so the tree hash is identical on every bench root."""
    ensure_fixture_cwd(cwd)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    root_id = "tree-root"
    counts = level_counts(n, depth)
    # root session (a small deterministic corpus)
    root_rows = generate_rows(2, cwd, seed=seed, big_markdown=False)
    root_rows[0]["id"] = root_id
    (out_dir / "root.jsonl").write_text(
        "\n".join(json.dumps(r) for r in root_rows) + "\n")
    files = {"root.jsonl": (out_dir / "root.jsonl").read_bytes()}
    # (level, index) -> (id, parent_dir)
    prev_level = [(root_id, out_dir)]
    active_left = active
    counter = 0
    for level in range(1, depth + 1):
        parents = prev_level
        this_level = []
        for i in range(counts[level - 1]):
            counter += 1
            node_id = f"s{level:02d}{i:03d}{seed & 0xff:02x}"
            parent_id, parent_dir = parents[i % len(parents)]
            is_active = active_left > 0 and i < active_left
            if is_active:
                active_left -= 1
            rows = _subagent_rows(node_id, level, i, not is_active, cwd)
            child_dir = parent_dir / ".rlm" / "sessions" / parent_id / f"sub-{i:03d}"
            child_dir.mkdir(parents=True, exist_ok=True)
            child_path = child_dir / f"{node_id}.jsonl"
            child_path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
            rel = child_path.relative_to(out_dir).as_posix()
            files[rel] = child_path.read_bytes()
            this_level.append((node_id, child_dir))
        prev_level = this_level or prev_level
    manifest = {
        "generator": GENERATOR,
        "spec": {"n": n, "active": active, "depth": depth, "seed": seed, "cwd": cwd},
        "files": {rel: {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
                  for rel, data in sorted(files.items())},
        "total_bytes": sum(len(d) for d in files.values()),
    }
    manifest["tree_sha256"] = hashlib.sha256(
        json.dumps(manifest["files"], sort_keys=True).encode()).hexdigest()
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1))
    return manifest


class SubagentTreeFixture(Fixture):
    """The deterministic subagent session tree (registry name subagent-tree)."""

    name = "subagent-tree"

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.n = int(self.spec.get("n", 24))
        self.active = int(self.spec.get("active", 3))
        self.depth = int(self.spec.get("depth", 2))
        self.seed = int(self.spec.get("seed", 1234))

    def path(self) -> Path:
        """The fixture tree directory."""
        return self.layout.fixtures / f"subagent-tree-n{self.n}"

    def generate(self, spec: dict) -> Path:
        """Build the tree deterministically; returns its path."""
        write_tree(self.path(), n=int(spec.get("n", self.n)), active=int(spec.get("active", self.active)),
                   depth=int(spec.get("depth", self.depth)), seed=self.seed)
        return self.path()

    def ensure(self) -> dict:
        """Build if missing or stale; returns the manifest record."""
        current = {"n": self.n, "active": self.active, "depth": self.depth,
                   "seed": self.seed, "cwd": FIXTURE_SESSION_CWD}
        manifest_path = self.path() / "manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text())
            if (manifest.get("spec") == current
                    and manifest.get("tree_sha256") == self._tree_hash()):
                return manifest
        self.generate(current)
        return self.manifest()

    def manifest(self) -> dict:
        """The persisted build record."""
        return json.loads((self.path() / "manifest.json").read_text())

    def _tree_hash(self) -> str:
        """The current on-disk tree hash (empty string if missing)."""
        manifest_path = self.path() / "manifest.json"
        if not manifest_path.exists():
            return ""
        files = {}
        for p in sorted(self.path().rglob("*.jsonl")):
            rel = p.relative_to(self.path()).as_posix()
            files[rel] = {"sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                          "bytes": p.stat().st_size}
        return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()

    def validate(self, expected_sha256: str) -> bool:
        """Re-hash the tree and compare against the manifest hash."""
        return self._tree_hash() == expected_sha256
