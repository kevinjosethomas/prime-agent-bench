# Benchmark summary

_Published phases: all non-aa phases; A/A rows calibrate only, never publish; gate: strict result-validity (bench.analysis.validity)._

## compare.cpu_idle

| product | trials | erase_ms | erase_ok | idle_cpu_pct | idle_window_s | involuntary_wakes_per_s | launch_to_ready_ms | nproc_end | wakes_per_s | rank | Δ vs TS |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Prime Agent Rust | aa=10 w1=10 | 9178.4 (n10) | 1 (n10) | 0.3 (n10) | 10.0 (n10) | 16.0 (n10) | 274.3 (n10) | 4 (n10) | 36.1 (n10) | — | — |
| Prime Agent TS | aa=10 w1=10 | 61.0 (n10) | 1 (n10) | 5.4 (n10) | 10.0 (n10) | 42.6 (n10) | 568.1 (n10) | 4 (n10) | 98.6 (n10) | — | baseline |
| Claude Code | aa=10 w1=10 | 2828.2 (n10) | 1 (n10) | 1.0 (n10) | 10.0 (n10) | 3.1 (n10) | 329.7 (n10) | 1 (n10) | 17.2 (n10) | — | — |
| Codex CLI | aa=8 w1=9 | 25.2 (n9) | 1 (n9) | 0.0 (n9) | 10.0 (n9) | 0.0 (n9) | 308.7 (n9) | 2 (n9) | 0.0 (n9) | — | — |
| Pi Mono | aa=10 w1=10 | 712.9 (n10) | 1 (n10) | 0.8 (n10) | 10.0 (n10) | 0.9 (n10) | 270.9 (n10) | 1 (n10) | 4.0 (n10) | — | — |

_Comparability: Prime Agent Rust=qualified, Prime Agent TS=qualified, Claude Code=qualified, Codex CLI=qualified, Pi Mono=qualified_

_Disclosures: Prime Agent TS: probe_quantized=10; Codex CLI: probe_quantized=9; Pi Mono: probe_quantized=10_

Excluded from rankings (validity gate):

| product | excluded | reasons |
|---|---|---|
| Codex CLI | 3 | validation_failed=3 |

## compare.memory_idle

| product | trials | erase_ms | erase_ok | launch_to_ready_ms | nproc_settled | pss_settled_mb | rss_settled_mb | tree_nproc | rank | Δ vs TS |
|---|---|---|---|---|---|---|---|---|---|---|
| Prime Agent Rust | aa=10 w1=10 | 9191.2 (n10) | 1 (n10) | 275.9 (n10) | 4 (n10) | 73.7 (n10) | 110.9 (n10) | 4 (n10) | — | — |
| Prime Agent TS | aa=10 w1=10 | 53.2 (n10) | 1 (n10) | 580.2 (n10) | 4 (n10) | 423.6 (n10) | 643.8 (n10) | 4 (n10) | — | baseline |
| Claude Code | aa=10 w1=10 | 2824.0 (n10) | 1 (n10) | 323.3 (n10) | 1 (n10) | 235.8 (n10) | 237.4 (n10) | 1 (n10) | — | — |
| Codex CLI | aa=10 w1=10 | 25.5 (n10) | 1 (n10) | 307.6 (n10) | 2 (n10) | 159.5 (n10) | 161.1 (n10) | 2 (n10) | — | — |
| Pi Mono | aa=10 w1=10 | 710.8 (n10) | 1 (n10) | 245.9 (n10) | 1 (n10) | 143.8 (n10) | 145.7 (n10) | 1 (n10) | — | — |

_Comparability: Prime Agent Rust=qualified, Prime Agent TS=qualified, Claude Code=qualified, Codex CLI=qualified, Pi Mono=qualified_

_Disclosures: Prime Agent TS: probe_quantized=10; Codex CLI: probe_quantized=10; Pi Mono: probe_quantized=10_

_A/A coverage: 2/2 benchmarks calibrated — an A/A table entry is the only noise evidence, its absence is never an OK._
