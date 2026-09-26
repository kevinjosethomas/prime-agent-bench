#!/bin/bash
# Vendor bootstrap for Prime VM sandboxes: apt deps + node 22 + products + auth.
# Ships in the harness bundle (vendor/). argv 1 = the product list to verify
# (csv, default rust,ts,claude,codex,pi).
# Layout targets (HOME=/root): /root/bench/repos (rust binary, pi-mono),
# /root/.local/share/prime-agent (TS), /root/.local/{bin/uv,share/uv}
# (the kernel toolchain), /usr/lib/node_modules (claude, codex),
# /usr/bin/{claude,codex} symlinks, /root/.{codex,claude,claude.json,prime}.
set -e
VDIR="$(cd "$(dirname "$0")" && pwd)"
PRODUCTS="${1:-rust,ts,claude,codex,pi}"
export DEBIAN_FRONTEND=noninteractive

echo "[bootstrap] apt deps"
apt-get update -qq
apt-get install -qq -y git curl ca-certificates jq rsync tmux file xz-utils bubblewrap

echo "[bootstrap] node 22 (nodesource)"
curl -fsSL https://deb.nodesource.com/setup_22.x | bash - >/dev/null
apt-get install -qq -y nodejs

if [ -f "$VDIR/products.tar.gz" ]; then
    echo "[bootstrap] untar products ($PRODUCTS)"
    tar -xzf "$VDIR/products.tar.gz" -C /
    if [ -f /.secret-free ]; then
        echo "[bootstrap] WARNING: secret-free vendor payload (built with 'bench vendor --no-secrets'): binaries shipped, credentials dropped — run the products' auth walk (or bench settle) before any benchmark"
    fi
else
    echo "[bootstrap] WARNING: no vendor/products.tar.gz (build it with 'bench vendor --products ...'); assuming the image already carries the products"
fi

echo "[bootstrap] version checks ($PRODUCTS)"
RUST=/root/bench/repos/prime-agent-rust/target/release/prime-agent
TS=/root/.local/share/prime-agent/bin/prime-agent
PI=/root/bench/repos/pi-mono/packages/coding-agent/dist/bundle/cli.js
case ",$PRODUCTS," in
    *,rust,*) "$RUST" --version ;;
    *,ts,*) "$TS" --version ;;
    *,claude,*) claude --version ;;
    *,codex,*) codex --version ;;
    *,pi,*) node "$PI" --version ;;
esac

echo "[bootstrap] DONE"
