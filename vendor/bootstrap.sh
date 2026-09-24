#!/bin/bash
# Vendor bootstrap for Prime VM sandboxes: apt deps + node 22 + products + auth
# + warm kernel venvs. Ships in the harness bundle (vendor/).
# Layout targets (HOME=/root): /root/bench/repos (rust binary, pi-mono),
# /root/.local/share/prime-agent (TS), /root/.local/{bin/uv,share/uv/python}
# (the kernel toolchain), /usr/lib/node_modules (claude, codex),
# /usr/bin/{claude,codex} symlinks, /root/.{codex,claude,claude.json,prime}.
set -e
VDIR="$(cd "$(dirname "$0")" && pwd)"
export DEBIAN_FRONTEND=noninteractive

echo "[bootstrap] apt deps"
apt-get update -qq
apt-get install -qq -y git curl ca-certificates jq rsync tmux file xz-utils

echo "[bootstrap] node 22 (nodesource)"
curl -fsSL https://deb.nodesource.com/setup_22.x | bash - >/dev/null
apt-get install -qq -y nodejs

echo "[bootstrap] untar products"
tar -xzf "$VDIR/products.tar.gz" -C /

echo "[bootstrap] version checks"
RUST=/root/bench/repos/prime-agent-rust/target/release/prime-agent
TS=/root/.local/share/prime-agent/bin/prime-agent
PI=/root/bench/repos/pi-mono/packages/coding-agent/dist/bundle/cli.js
"$RUST" --version
"$TS" --version
claude --version
codex --version
node "$PI" --version

echo "[bootstrap] warm kernel venvs (rust, ts)"
# uv + the shipped cpython-3.11 (matches the benchmark node's kernel venvs)
export HOME=/root
UV=/root/.local/bin/uv
PY=/root/.local/share/uv/python/cpython-3.11.16-linux-x86_64-gnu/bin/python3.11
test -x "$UV" || { echo "uv missing"; exit 1; }
test -x "$PY" || { echo "cpython-3.11 missing"; exit 1; }
REL=$(ls -d /root/.local/share/prime-agent/releases/*-linux-x64-* | head -1)
EXTRAS="requests httpx pyyaml tomli python-dotenv pandas numpy scipy beautifulsoup4 lxml pydantic tyro dill"
for prod in rust ts; do
  VENV=/root/bench-root/global/$prod/kernel-venv
  "$UV" venv -q --python "$PY" "$VENV"
  "$UV" pip install -q --python "$VENV/bin/python" "$REL/prime-agent-runtime" $EXTRAS
  "$VENV/bin/python" -c "import rlm.repl, dill, pandas, numpy, scipy, bs4, lxml, pydantic, tyro, requests, httpx, yaml, tomli, dotenv; print('kernel-venv', '$prod', 'OK')"
  mkdir -p /root/bench-root/global/$prod/uv-cache /root/bench-root/global/$prod/xdg-cache
done
for prod in claude codex pi; do
  mkdir -p /root/bench-root/global/$prod/kernel-venv /root/bench-root/global/$prod/uv-cache /root/bench-root/global/$prod/xdg-cache
done
echo "[bootstrap] DONE"
