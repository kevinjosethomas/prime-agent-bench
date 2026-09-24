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

echo "[bootstrap] DONE"
