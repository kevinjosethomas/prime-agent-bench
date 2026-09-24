#!/usr/bin/env python3
"""compare.install_disk: downloaded artifact bytes + installed footprint bytes.

One-shot per product (artifact accounting, not a timed benchmark). The
kernel venv under ~/.prime/agent is runtime state, not install footprint,
and is excluded. Node itself is shared infrastructure (recorded, not
charged per product).
"""
import json
import subprocess
import sys
from pathlib import Path

HOME = Path.home()
RESULTS = HOME / "bench" / "results"


def du(path) -> int:
    if isinstance(path, str):
        path = Path(path)
    if not path.exists():
        return 0
    out = subprocess.run(["du", "-sb", str(path)], capture_output=True, text=True)
    return int(out.stdout.split()[0])


def npm_pack(pkg: str, version: str, dest: Path) -> int:
    dest.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["npm", "pack", f"{pkg}@{version}", "--pack-destination", str(dest)],
                       capture_output=True, text=True, cwd=str(dest))
    tarballs = list(dest.glob("*.tgz"))
    return max((t.stat().st_size for t in tarballs), default=0)


def main():
    out = {}
    tmp = HOME / "bench" / "fixtures" / "npm-pack"
    # rust: from-source build (no official linux release binary exists yet)
    out["rust"] = {
        "installed_bytes": du(HOME / "bench/repos/prime-agent-rust/target/release/prime-agent"),
        "download_bytes": 7843159,  # git archive of origin/rust (source distribution)
        "note": "from-source cargo --release build; source archive bytes as download",
    }
    # ts: official compiled beta
    out["ts"] = {
        "installed_bytes": du(HOME / ".local/share/prime-agent"),
        "download_bytes": du(HOME / ".local/share/prime-agent"),  # single-binary install ~= download
        "note": "official 0.9.5-beta.2043.1 compiled binary via install.sh",
    }
    out["claude"] = {
        "installed_bytes": du("/usr/lib/node_modules/@anthropic-ai"),
        "download_bytes": npm_pack("@anthropic-ai/claude-code", "2.1.281", tmp / "claude"),
    }
    out["codex"] = {
        "installed_bytes": du("/usr/lib/node_modules/@openai"),
        "download_bytes": npm_pack("@openai/codex", "0.156.1", tmp / "codex"),
    }
    pi_pkg = json.loads((HOME / "bench/repos/pi-mono/packages/coding-agent/package.json").read_text())
    pi_tree = 0
    for sub in ("node_modules", "packages"):
        pi_tree += du(HOME / "bench/repos/pi-mono" / sub)
    out["pi"] = {
        "installed_bytes": pi_tree,
        "download_bytes": npm_pack(pi_pkg.get("name", "pi"), pi_pkg.get("version", "latest"), tmp / "pi"),
        "note": f"built from source (repo {pi_pkg.get('name')}@{pi_pkg.get('version')}); pack may 404 if unpublished",
    }
    out["_node_runtime"] = {"bytes": du("/usr/lib/node_modules/npm") + du("/usr/bin/node"),
                           "note": "shared infra, not charged per product"}
    (RESULTS / "install_disk.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
