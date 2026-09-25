# Benchmark summary

_Published phases: all non-aa phases; A/A rows calibrate only, never publish; gate: strict result-validity (bench.analysis.validity)._

## compare.memory_idle_load

| product | trials | launch_to_ready_ms | nproc_settled | pss_settled_mb | rss_settled_mb | tree_nproc | rank | Δ vs TS |
|---|---|---|---|---|---|---|---|---|
| Prime Agent Rust | aa=10 cmp2=10 | 2098.7 (n10) | 4 (n10) | 159.5 (n10) | 195.0 (n10) | 4 (n10) | — | — |
| Prime Agent TS | aa=10 cmp2=10 | 736.4 (n10) | 4 (n10) | 464.4 (n10) | 685.0 (n10) | 4 (n10) | — | baseline |
| Pi Mono | aa=10 cmp2=10 | 264.4 (n10) | 1 (n10) | 198.3 (n10) | 200.3 (n10) | 1 (n10) | — | — |

_Comparability: Prime Agent Rust=equivalent, Prime Agent TS=equivalent, Pi Mono=equivalent_

_Disclosures: Prime Agent TS: probe_quantized=10; Pi Mono: probe_quantized=10_

**Ranks withheld — validation_only**: aa.required=false: validation-only analysis — ranks are never emitted

## compare.msg_send

| product | trials | submit_to_ack_ms | submit_to_settle_ms | rank | Δ vs TS |
|---|---|---|---|---|---|
| Prime Agent Rust | aa=10 cmp2=10 | 47.0 (n10) | 769.8 (n10) | — | — |
| Prime Agent TS | aa=10 cmp2=10 | 2.5 (n10) | 934.6 (n10) | — | baseline |
| Claude Code | aa=10 cmp2=10 | 85.3 (n10) | 738.0 (n10) | — | — |

_Comparability: Prime Agent Rust=qualified, Prime Agent TS=qualified, Claude Code=qualified_

Unstable (never ranked):

| product | reason | detail |
|---|---|---|
| Prime Agent TS | aa_drift | A/A p50 2.1 vs published p50 2.5 (+19.0% drift) |
| Claude Code | aa_drift | A/A p50 69.2 vs published p50 85.3 (+23.3% drift) |

**Ranks withheld — validation_only**: aa.required=false: validation-only analysis — ranks are never emitted

## compare.scroll_typing

| product | trials | launch_to_ready_ms | nproc_10mib | pss_10mib_mb | pty_bytes | rss_10mib_mb | scroll_pgup_ms_p50 | scroll_pgup_ms_p95 | typing_ms_p50 | typing_ms_p95 | typing_ok | typing_scrolled_ms_p50 | typing_scrolled_ms_p95 | wheel_bursts | wheel_bytes | rank | Δ vs TS |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Prime Agent Rust | aa=10 cmp2=10 | 2099.0 (n10) | 4 (n10) | 156.4 (n10) | 209103 (n10) | 192.9 (n10) | 9.3 (n10) | 14.0 (n10) | 1.1 (n10) | 1.3 (n10) | 1 (n10) | 0.3 (n10) | 0.3 (n10) | 1 (n10) | 146715 (n10) | — | — |
| Prime Agent TS | aa=10 cmp2=10 | 747.1 (n10) | 4 (n10) | 484.0 (n10) | 42736 (n10) | 704.5 (n10) | 8.9 (n10) | 10.0 (n10) | 3.1 (n10) | 5.3 (n10) | 1 (n10) | 3.0 (n10) | 3.4 (n10) | 0 (n10) | 0 (n10) | — | baseline |
| Pi Mono | aa=10 cmp2=10 | 262.6 (n10) | 1 (n10) | 178.1 (n10) | 914780 (n10) | 180.1 (n10) | — | — | 2.9 (n10) | 3.8 (n10) | 1 (n10) | 4.2 (n10) | 5.4 (n10) | 1 (n10) | 11 (n10) | — | — |

_Comparability: Prime Agent Rust=equivalent, Prime Agent TS=equivalent, Pi Mono=equivalent_

_Disclosures: Prime Agent TS: probe_quantized=10; Pi Mono: probe_quantized=10_

Unstable (never ranked):

| product | reason | detail |
|---|---|---|
| Prime Agent TS | aa_spread | A/A spread over threshold — typing_ms_p50: a=3.1 b=3.5 (12.9%) |

**Ranks withheld — validation_only**: aa.required=false: validation-only analysis — ranks are never emitted

## compare.warm_start

| product | trials | erase_ms | erase_ok | frame_bursts | input_ready_gap_ms | launch_to_first_paint_ms | launch_to_ready_ms | nproc_settled | pss_settled_mb | pty_bytes | rss_settled_mb | tree_nproc | unconfirmed_attempts | rank | Δ vs TS |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Prime Agent Rust | aa=10 cmp2=10 | 35.1 (n10) | 1 (n10) | 4 (n10) | 2031.8 (n10) | 8.9 (n10) | 2040.8 (n10) | 1 (n10) | 31.9 (n10) | 23864 (n10) | 42.0 (n10) | 1 (n10) | 21 (n10) | — | — |
| Prime Agent TS | aa=10 cmp2=10 | 24.3 (n10) | 1 (n10) | 3 (n10) | 14.5 (n10) | 566.7 (n10) | 581.1 (n10) | 1 (n10) | 134.1 (n10) | 4840 (n10) | 206.8 (n10) | 1 (n10) | 0 (n10) | — | baseline |

_Comparability: Prime Agent Rust=qualified, Prime Agent TS=qualified_

_Disclosures: Prime Agent TS: probe_quantized=10_

**Ranks withheld — validation_only**: aa.required=false: validation-only analysis — ranks are never emitted

## A/A calibration

| pair | p50 a | p50 b | spread | valid |
|---|---|---|---|---|
| compare.memory_idle_load/rust | 198.1 | 195.7 | 1.2% | YES |
| compare.memory_idle_load/ts | 685.5 | 686.6 | 0.2% | YES |
| compare.memory_idle_load/pi | 200.4 | 200.6 | 0.1% | YES |
| compare.msg_send/rust | 48.5 | 46.8 | 3.6% | YES |
| compare.msg_send/rust/submit_to_settle_ms | 768.3 | 780.4 | 1.6% | YES |
| compare.msg_send/ts | 2.1 | 2.1 | 0.0% | YES |
| compare.msg_send/ts/submit_to_settle_ms | 925.8 | 943.5 | 1.9% | YES |
| compare.msg_send/claude | 69.2 | 71.7 | 3.6% | YES |
| compare.msg_send/claude/submit_to_settle_ms | 758.1 | 759.1 | 0.1% | YES |
| compare.scroll_typing/rust | 1.1 | 1.2 | 9.1% | YES |
| compare.scroll_typing/ts | 3.1 | 3.5 | 12.9% | NO |
| compare.scroll_typing/pi | 2.9 | 3.0 | 3.4% | YES |
| compare.warm_start/rust | 2040.0 | 2038.8 | 0.1% | YES |
| compare.warm_start/ts | 562.1 | 573.4 | 2.0% | YES |

_A/A coverage: 4/4 benchmarks calibrated — an A/A table entry is the only noise evidence, its absence is never an OK._
