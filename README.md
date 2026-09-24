# prime-agent-bench

The cross-product benchmark harness for Prime Agent — Rust vs TypeScript vs Claude Code vs Codex CLI vs Pi Mono.

## What it measures

| Benchmark | What |
|---|---|
| `compare.cold_start` | Launch → typed echo accepted (interactive-ready) |
| `compare.warm_start` | Same with pre-warmed daemon |
| `compare.msg_send` | Keystroke → server submit-ack |
| `compare.scroll_typing` | Scroll + typing latency on a 10MiB session |
| `compare.memory_idle_load` | Process-tree RSS after cold start + loaded session |
| `compare.install_disk` | Download + clean install bytes |
| `daemon.boot` | Supervisor spawn → handshake → first client (RT only) |
| `session.cold_open[10MiB]` | Cold open of the 10MiB fixture → interactive (RT only) |
| `kernel.*` | CPython kernel benchmarks (RT only) |

## Methodology

- Raw-PTY driver (pyte screen emulation, monotonic clock, sub-ms floor)
- Sequential isolation — one product benchmarking at a time, never concurrent
- ABBA ordering across products (alternating trial order to cancel drift)
- A/A calibration (same product measured twice → noise floor must be <10%)
- N=10 trials per product per benchmark, p50/p95/p99 reported
- Per-trial process sweep (kills all daemon/worker/kernel processes between trials)
- Load gate before every trial (wait for compile-free, load <0.6)
- Per-trial loadavg + RSS + PTY-bytes recorded as clean-environment proof

## Setup

```bash
# On a fresh Ubuntu 22.04 node:
sudo apt install -y git curl python3 python3-venv tmux jq rsync
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - && sudo apt install -y nodejs
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Install products (see products.py for the exact per-product setup)
# Authenticate each product (claude login, codex auth, prime-agent login)

# Run the suite:
bash wave_chain.sh
```

## Architecture

```
products.py     Product adapters (install/launch/settle/act/observe per product)
benchmarks.py   Scenario definitions (cold_start, warm_start, etc.)
ptybench.py     Raw-PTY driver (screen emulation, echo detection, sub-ms timing)
fixtures.py     Deterministic session generators (exact bytes + sha256 manifest)
runner.py       Trial orchestrator (sequential isolation, ABBA, load gates)
analyze.py      Stats, bootstrap CIs, product rankings, A/A validation
bench_mock.py   Offline mock provider (OpenAI/Anthropic-compatible, port 8788)
kernel_bench.py Kernel P0 benchmarks (cold start, cell exec, state snapshot)
kernel_raw.py   Raw rlm.repl substrate probe (bridge-overhead isolation)
```

Adding a new product: add a product adapter in `products.py`.
Adding a new benchmark: add a scenario module in `benchmarks.py`.
