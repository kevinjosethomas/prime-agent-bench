# prime-agent-bench

The cross-product benchmark harness for Prime Agent — Rust vs TypeScript vs
Claude Code vs Codex CLI vs Pi Mono. One modular codebase: products,
benchmarks, harness drivers, fixtures, and analyzers are pluggable adapters
discovered from the package structure.

## What it measures

| Benchmark | What |
|---|---|
| `compare.cold_start` | Launch -> typed echo accepted (interactive-ready); first paint recorded separately |
| `compare.warm_start` | Same with pre-warmed daemon |
| `compare.msg_send` | Keystroke -> server submit-ack |
| `compare.scroll_typing` | Scroll + typing latency on a 10MiB session |
| `compare.memory_idle_load` | Process-tree RSS after cold start + loaded session |
| `compare.install_disk` | Download + clean install bytes |
| `daemon.boot` | Supervisor spawn -> handshake -> first client (RT only) |
| `session.cold_open_10mib` | Cold open of the 10MiB fixture -> interactive; ranked boundary = the later of tail sentinel and typed echo (RT only) |
| `session.agent_view_roundtrip` | Chat -> agents view -> same session chat, per leg (RT only) |
| `kernel.*` | CPython kernel benchmarks (RT only) |

## Methodology

- Raw-PTY driver (pyte screen emulation, monotonic clock, sub-ms floor); tmux
  driver as the proven alternative (interchangeable `HarnessDriver`)
- Sequential isolation — one product benchmarking at a time, never concurrent
- ABBA ordering across products (alternating trial order to cancel drift)
- A/A calibration (same product measured twice -> noise floor must be <10%)
- Rank policy: `aa.required=false` (default) is validation-only — the analysis
  reports stats, marks and denominators but NEVER emits ranks; a publishable
  campaign declares `aa.required=true` + explicit `aa.expected_products` (the
  eligible cohort; `aa.trials` mirrors `--aa-trials`) and a benchmark ranks
  only when every expected product is present, A/A-calibrated and
  spread/drift-stable — any gap withholds the whole benchmark
- N=10 trials per product per benchmark, p50/p95/p99 with bootstrap CIs
- Per-trial process sweep (kills all daemon/worker/kernel processes between
  trials), load gate before every trial, per-trial loadavg + RSS + PTY bytes
- Deterministic fixtures with sha256 manifests (the 10MiB corpus is byte-exact
  and pinned in the test suite); `session-10mib` is the historical v2 golden
  (digest rows without `display`, which products render visible), and
  `session-10mib-v3` is the display-corrected corpus — every harness_digest
  row persisted `display: false` plus the raw digest in `details`, exactly
  like real TS/Rust session files (same 7391-row shape, its own golden sha);
  `session.cold_open_10mib`, `compare.memory_idle_load` and
  `compare.scroll_typing` run on `session-10mib-v3`, while
  `session.agent_view_roundtrip` keeps the v2 corpus
- Startup honesty (audit F13): first paint and interactive-ready are
  distinct metrics (`launch_to_first_paint_ms` vs `launch_to_ready_ms`) —
  never blended. Readiness is probed at a fine grid with the harness's own
  quantization disclosed per row (`record["probe"]["quantized_ms"]`,
  `input_buffered`); onboarding dialogs that surface mid-probe (a
  settle/template-state artifact) are auto-dismissed, excluded from the
  gap, and disclosed per row. The old ~2s probe floor was two 1.0s
  harness waits for absent dialog markers, not product latency.
- Provenance (audit F7/F8/F9): every row carries `run` — the campaign
  label plus the harness revision that measured it (deploy-bundle
  sha256 in sandbox runs); `bench analyze --phase w1` fixes the
  published denominator, per-phase p50s label every pool, mixed-identity
  trees are flagged, `versions.json` carries a `_meta` provenance stamp,
  and the parallel-run manifest is written incrementally with
  timestamped reference-calibration records.
- Strict result-validity gate: only completed valid trials enter stats/rankings/
  deltas (probe-deadline artifacts, auth-error settle — Codex 401 — and
  real-API-regime rows, unsupported product/benchmark combinations, unconfirmed
  fixtures, failed / missing / vacuous validation (validated=true without a
  validation block — kernel.* and daemon.boot stay unrankable until their
  benchmarks record completion evidence), incomplete measurements, debug rows
  are excluded with reported counts + reasons; engine status rows (products
  that ran no trials) are reported as status, not exclusions; A/A calibration rows never mix into published
  stats, per-phase trial counts label every denominator, and a product with a
  failing A/A noise floor (primary + declared aa_metrics, e.g. msg_send's
  settle, whenever published) or an A/A-to-wave drift (aa.drift_threshold_pct)
  is marked unstable and never ranked

## Architecture

```
bench/
  core/        The ABCs: ProductAdapter, Benchmark, HarnessDriver/Session,
               Fixture, Analyzer + registry, config, env, measurement,
               process accounting
  adapters/
    <harness>/    One harness per FOLDER, verifiers style: <name>/ with
                  adapter.py, product.yaml, README.md - the complete
                  harness config (rust/ ts/ claude/ codex/ pi/)
    benchmarks/   One generic scenario per file: cold_start, msg_send, ...
    terminals/    pty (timing-grade), tmux (capture-poll alternative)
    fixtures/     session-10mib corpus, subagent-tree
  drivers/      mock provider, raw kernel probe, explore tool,
               wave_chain (per-sandbox entry point), warm_kernels,
               vendor (tarball builder), sandbox (setup/run/destroy),
               diagnose (evidence bundles), compare, orchestrator/
  analysis/    stats, rankings, aggregate, A/A validation, output (json,
               markdown, notion payload)
  trials.py    The ABBA trial engine (JSONL per trial)
  gates.py     Load gates (block trials until the node is idle)
  runner.py    The sequential suite runner (gold standard)
  cli.py       bench run | settle | versions | vendor | sandbox | diagnose |
               compare | explore | install-disk | analyze | list |
               noop-control | fixtures | orchestrator
configs/
  default.yaml         Trial counts, timeouts, load gates, thresholds,
                       the kernel toolchain (vendor toolchain)
  parallel.yaml        Sandbox specs, reference thresholds, retry policies
tests/        registry, fixtures (byte-exact goldens), analysis, orchestrator
```

Adding a harness = one folder under `bench/adapters/<name>/` carrying its
`adapter.py`, its complete `product.yaml` (binary, auth sources, install,
first-run dialogs, msg routing, vendor payload), and a `README.md`.
Benchmark scenarios, fixtures, and terminal drivers stay one file each in
their kind packages: the registry auto-discovers every adapter subclass;
there is no registration file to maintain. The kind package names are
reserved — a harness folder must not be named `benchmarks/`, `fixtures/`,
or `terminals/`.

## Setup - one node, or one command per sandbox

The harness controller needs a node with the authenticated products (the
proven benchmark node setup). Every NEW sandbox is then one command:

```bash
# controller deps (fresh Ubuntu 22.04):
sudo apt install -y git curl python3 python3-venv tmux jq rsync
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
# + the prime CLI/SDK when provisioning Prime VM sandboxes

# build the vendor payload from the product configs (binaries + auth +
# toolchain, laid out for the sandbox's HOME=/root):
bench vendor --products rust,ts,claude,codex,pi   # -> vendor/products.tar.gz
# secret-free payload (drops every declared auth_sources entry; a
# .secret-free marker rides in the tarball and the build manifest records
# the redaction — for shipping/sharing, never the default bundle):
bench vendor --no-secrets --products rust,ts,claude,codex,pi
# privacy caveat: secret-free drops DECLARED auth only — the payload still
# ships the whole declared toolchain breadth (the ~/.local/share/uv tree
# may carry caches); trim the vendor/toolchain lists before shipping it.

# ONE command: provision + deploy + bootstrap + warm kernels + verify every
# product's interactive state; prints a readiness report:
bench sandbox setup mybox --products rust,ts,claude,codex,pi

# run trials inside it (setup and run share the product configs; safe to
# invoke blind: load-gated, sequential, process-swept):
bench run --benchmarks compare.cold_start --products rust --trials 10 --sandbox mybox

# teardown:
bench sandbox destroy mybox
```

`bench sandbox setup` also takes `--backend local` (isolated bench roots on
one machine, no cloud spend) and per-name spec overrides under `sandboxes:`
in `configs/parallel.yaml`. The readiness report carries each product's
version + binary sha256, the kernel-venv state (rust/ts), and the settle
result (the configured first-run dialog walk).

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
+ `bootstrap`), the payload in `vendor/products.tar.gz` (`bench vendor
build`). Use `--keep-sandboxes` to keep them for debugging. Prefer
parallel mode for iteration and CI gates; re-run anything surprising
sequentially before publishing it.

## The improvement loop

The harness is the substrate for a continuous improve-benchmark-compare
loop over prime-agent-rust. One iteration:

1. **Bump the rust binary** on the node (build + copy to
   `~/bench/repos/prime-agent-rust/target/release/prime-agent`), update
   the `revision:` pin in `bench/adapters/rust/product.yaml`, and
   `bench vendor --products rust` so sandbox setups carry the new
   binary.
2. **Set up a fresh sandbox**: `bench sandbox setup rust-<rev> --products
   rust` - the readiness report already proves the new binary (version +
   sha256 + settle OK).
3. **Run**: `bench run --benchmarks compare.cold_start,compare.warm_start
   --products rust --trials 10 --sandbox rust-<rev>`. A/A calibration runs
   first (never skippable by default), trials are load-gated,
   sequential-within-sandbox, process-swept; `versions.json` lands with the
   results.
4. **Compare**: `bench compare <previous-run> <new-run>` - per-benchmark
   p50 deltas with bootstrap-CI separation plus both runs' version
   evidence, so a delta is attributable, never blind.
5. **Auto-research**: analyze the per-trial JSONL (`bench analyze`); the
   strongest signal for the next change wins. Repeat.

Why runs stay comparable across the loop: every result set carries
`versions.json` (binary SHAs + product versions) and the A/A noise floor;
parallel runs add the per-sandbox reference normalization (the canonical
CPU loop, >5% outliers replaced). What the A/A pass catches is measured
noise: an environment too unstable for cross-product claims, or a
product whose pass-to-pass drift exceeds the gate. What it cannot catch
is a systematic error shared by both halves — the audit's 120s
sentinel-deadline artifact passed its A/A with every row equally
censored. A regression that escapes A/A is unverified, not disproven:
the validity gate (per-row validation evidence, fixture confirmation,
probe-quantization disclosure, run-identity provenance) is what makes a
row trustworthy; A/A only bounds the noise around it.

When a settle fails anywhere in the loop, `bench diagnose <product>`
reproduces it and writes the evidence bundle (screen-at-end, raw output
tail, answered dialogs, mock request log, settle records) that used to
take an hour of manual probing.

Not part of any product. Benchmark harness only.
