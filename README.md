# prime-agent-bench

The cross-product benchmark harness for Prime Agent — Rust vs TypeScript vs
Claude Code vs Codex CLI vs Pi Mono. One modular codebase: products,
benchmarks, harness drivers, fixtures, and analyzers are pluggable adapters
discovered from the package structure.

## What it measures

| Benchmark | What |
|---|---|
| `compare.cold_start` | Launch -> typed echo accepted (interactive-ready) |
| `compare.warm_start` | Same with pre-warmed daemon |
| `compare.msg_send` | Keystroke -> server submit-ack |
| `compare.scroll_typing` | Scroll + typing latency on a 10MiB session |
| `compare.memory_idle_load` | Process-tree RSS after cold start + loaded session |
| `compare.install_disk` | Download + clean install bytes |
| `daemon.boot` | Supervisor spawn -> handshake -> first client (RT only) |
| `session.cold_open_10mib` | Cold open of the 10MiB fixture -> interactive (RT only) |
| `kernel.*` | CPython kernel benchmarks (RT only) |

## Methodology

- Raw-PTY driver (pyte screen emulation, monotonic clock, sub-ms floor); tmux
  driver as the proven alternative (interchangeable `HarnessDriver`)
- Sequential isolation — one product benchmarking at a time, never concurrent
- ABBA ordering across products (alternating trial order to cancel drift)
- A/A calibration (same product measured twice -> noise floor must be <10%)
- N=10 trials per product per benchmark, p50/p95/p99 with bootstrap CIs
- Per-trial process sweep (kills all daemon/worker/kernel processes between
  trials), load gate before every trial, per-trial loadavg + RSS + PTY bytes
- Deterministic fixtures with sha256 manifests (the 10MiB corpus is byte-exact
  and pinned in the test suite)

## Architecture

```
bench/
  core/        The ABCs: ProductAdapter, Benchmark, HarnessDriver/Session,
               Fixture, Analyzer + registry, config, env, measurement,
               process accounting
  adapters/
    products/     One product per file: rust, ts, claude, codex, pi
    benchmarks/   One scenario per file: cold_start, warm_start, msg_send, ...
    harnesses/    pty (timing-grade), tmux (capture-poll alternative)
    fixtures/     session-10mib corpus, subagent-tree
  drivers/      mock provider, raw kernel probe, explore tool,
               wave_chain (per-sandbox entry point), orchestrator/
  analysis/    stats, rankings, aggregate, A/A validation, output (json,
               markdown, notion payload)
  trials.py    The ABBA trial engine (JSONL per trial)
  gates.py     Load gates (block trials until the node is idle)
  runner.py    The sequential suite runner (gold standard)
  cli.py       bench run | settle | explore | install-disk | analyze | list |
               noop-control | fixtures | orchestrator
configs/
  default.yaml         Trial counts, timeouts, load gates, thresholds
  products/*.yaml      Per-product install/auth/version pinning
  parallel.yaml        Sandbox specs, reference thresholds, retry policies
tests/        registry, fixtures (byte-exact goldens), analysis, orchestrator
```

Adding a product = one file under `bench/adapters/products/`. Same for
benchmarks, harness drivers, and fixtures: the registry auto-discovers every
adapter subclass; there is no registration file to maintain.

## Setup

```bash
# On a fresh Ubuntu 22.04 node:
sudo apt install -y git curl python3 python3-venv tmux jq rsync
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - && sudo apt install -y nodejs
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Install products (see configs/products/*.yaml for the exact pinning)
# Authenticate each product (claude login, codex auth, prime-agent login)
```

## Usage

```bash
bench list                                          # registry inventory
bench settle --products rust,ts,claude,codex,pi      # build home templates
bench run --benchmarks compare.cold_start --products rust,ts,claude,codex,pi --trials 10 --phase w1
bench analyze                                        # summary.json/md/notion.json
bench install-disk                                   # one-shot footprint accounting
bench noop-control --rounds 30                       # harness floor
bench explore claude --seconds 20                     # onboarding explorer
python -m bench.drivers.wave_chain --benchmarks compare.warm_start --aa   # one wave chain
```

Every command takes `--config <yaml>` to override `configs/default.yaml`.

## Sequential vs parallel mode

**Sequential (the default, gold standard).** `bench run` executes one
benchmark after another on one node with load gates between every trial.
Cross-product numbers are comparable by construction — same machine, same
environment, ABBA-ordered. Published numbers come from this mode.

**Parallel (iteration mode).** `bench orchestrator` provisions N Prime VM
sandboxes — one per benchmark type — and each sandbox runs ALL products
sequentially inside it (cross-product fairness holds on identical
hardware), giving a 4-5x wall-clock speedup for the compare wave set.
Before any trial, every sandbox runs the canonical reference benchmark
(a fixed CPU-bound loop) and the orchestrator flags any sandbox deviating
more than 5% from the median — replacing it (default, bounded budget) or
recording a normalization factor. Each sandbox also runs its own A/A pass
first, so the noise floor is validated per sandbox, and failed sandboxes
are re-provisioned and re-run automatically.

```bash
bench orchestrator --benchmarks compare.cold_start,compare.warm_start,compare.msg_send \
                   --products rust,ts,claude,codex,pi --trials 10
bench orchestrator --benchmarks compare.cold_start --backend local --dry-run  # plan only
```

Sandbox images need the full node setup (products installed and
authenticated); the recipe lives in `parallel.yaml` (`sandbox_defaults.image`
+ `bootstrap`). Use `--keep-sandboxes` to keep them for debugging. Prefer
parallel mode for iteration and CI gates; re-run anything surprising
sequentially before publishing it.

Not part of any product. Benchmark harness only.
