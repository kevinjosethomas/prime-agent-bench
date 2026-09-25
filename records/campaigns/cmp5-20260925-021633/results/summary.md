# Benchmark summary

_Published phases: cmp5; A/A rows calibrate only, never publish; gate: strict result-validity (bench.analysis.validity)._

## compare.cold_start

| product | trials | erase_ms | erase_ok | frame_bursts | input_ready_gap_ms | launch_to_first_paint_ms | launch_to_ready_ms | nproc_settled | pss_settled_mb | pty_bytes | rss_settled_mb | tree_nproc | unconfirmed_attempts | rank | Δ vs TS |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Prime Agent Rust | aa=10 cmp5=10 | 37.6 (n10) | 1 (n10) | 3 (n10) | 2032.0 (n10) | 36.5 (n10) | 2083.9 (n10) | 4 (n10) | 111.5 (n10) | 23864 (n10) | 147.6 (n10) | 4 (n10) | 21 (n10) | — | — |
| Prime Agent TS | aa=10 cmp5=10 | 24.5 (n10) | 1 (n10) | 2 (n10) | 13.1 (n10) | 656.9 (n10) | 669.6 (n10) | 4 (n10) | 395.2 (n10) | 4840 (n10) | 615.6 (n10) | 4 (n10) | 0 (n10) | — | baseline |
| Claude Code | aa=10 cmp5=10 | 13.3 (n10) | 1 (n10) | 2 (n10) | 32.8 (n10) | 239.1 (n10) | 270.6 (n10) | 1 (n10) | 220.9 (n10) | 2269 (n10) | 222.6 (n10) | 1 (n10) | 0 (n10) | — | — |
| Codex CLI | aa=10 cmp5=10 | 7.1 (n10) | 1 (n10) | 3 (n10) | 18.1 (n10) | 276.7 (n10) | 295.4 (n10) | 3 (n10) | 273.4 (n9) | 7027 (n10) | 276.5 (n10) | 3 (n10) | 0 (n10) | — | — |
| Pi Mono | aa=10 cmp5=10 | 7.1 (n10) | 1 (n10) | 2 (n10) | 6.5 (n10) | 252.3 (n10) | 259.1 (n10) | 1 (n10) | 143.3 (n10) | 3879 (n10) | 145.2 (n10) | 1 (n10) | 0 (n10) | — | — |

_Comparability: Prime Agent Rust=qualified, Prime Agent TS=qualified, Claude Code=qualified, Codex CLI=qualified, Pi Mono=qualified_

_Disclosures: Prime Agent TS: probe_quantized=10; Claude Code: probe_quantized=10; Codex CLI: probe_quantized=10; Pi Mono: probe_quantized=10_

Uncalibrated (never ranked):

| product | reason | A/A valid/expected |
|---|---|---|
| Prime Agent Rust | partial A/A calibration (10/20 valid rows) | 10/20 |
| Prime Agent TS | partial A/A calibration (10/20 valid rows) | 10/20 |
| Claude Code | partial A/A calibration (10/20 valid rows) | 10/20 |
| Codex CLI | partial A/A calibration (10/20 valid rows) | 10/20 |
| Pi Mono | partial A/A calibration (10/20 valid rows) | 10/20 |

**Ranks withheld — incomplete_cohort**: expected cohort ['rust', 'ts', 'claude', 'codex', 'pi'] — uncalibrated: claude, codex, pi, rust, ts

## compare.install_disk

| product | trials | download_bytes | installed_bytes | rank | Δ vs TS |
|---|---|---|---|---|---|
| Prime Agent Rust | aa=2 cmp5=10 | 7843159 (n10) | 205867840 (n10) | — | — |
| Prime Agent TS | aa=2 cmp5=10 | 172147733 (n10) | 172147733 (n10) | — | baseline |
| Claude Code | aa=2 cmp5=10 | 27580 (n10) | 474960387 (n10) | — | — |
| Codex CLI | aa=2 cmp5=10 | 4904 (n10) | 386998144 (n10) | — | — |
| Pi Mono | aa=2 cmp5=10 | 0 (n10) | 466087714 (n10) | — | — |

_Comparability: Prime Agent Rust=qualified, Prime Agent TS=qualified, Claude Code=qualified, Codex CLI=qualified, Pi Mono=qualified_

Uncalibrated (never ranked):

| product | reason | A/A valid/expected |
|---|---|---|
| Prime Agent Rust | partial A/A calibration (2/20 valid rows) | 2/20 |
| Prime Agent TS | partial A/A calibration (2/20 valid rows) | 2/20 |
| Claude Code | partial A/A calibration (2/20 valid rows) | 2/20 |
| Codex CLI | partial A/A calibration (2/20 valid rows) | 2/20 |
| Pi Mono | partial A/A calibration (2/20 valid rows) | 2/20 |

**Ranks withheld — incomplete_cohort**: expected cohort ['rust', 'ts', 'claude', 'codex'] — uncalibrated: claude, codex, rust, ts

## compare.memory_idle_load

| product | trials | launch_to_ready_ms | nproc_settled | pss_settled_mb | rss_settled_mb | tree_nproc | rank | Δ vs TS |
|---|---|---|---|---|---|---|---|---|
| Prime Agent Rust | aa=10 cmp5=10 | 2100.9 (n10) | 4 (n10) | 171.2 (n10) | 207.7 (n10) | 4 (n10) | — | — |
| Prime Agent TS | aa=10 cmp5=10 | 754.7 (n10) | 4 (n10) | 474.8 (n10) | 695.2 (n10) | 4 (n10) | — | baseline |
| Pi Mono | aa=10 cmp5=10 | 274.9 (n10) | 1 (n10) | 191.5 (n10) | 193.3 (n10) | 1 (n10) | — | — |

Status (no trials ran):

- Claude Code: not_comparable — claude has no native session-10mib-v4 fixture: its argv ignores resume_fixture, and spec §F large-session rows require a vendor-native fixture (sentinel + message count equivalence)
- Codex CLI: not_comparable — codex has no native session-10mib-v4 fixture: its argv ignores resume_fixture, and spec §F large-session rows require a vendor-native fixture (sentinel + message count equivalence)

_Comparability: Prime Agent Rust=equivalent, Prime Agent TS=equivalent, Pi Mono=equivalent_

_Disclosures: Prime Agent TS: probe_quantized=10; Pi Mono: probe_quantized=10_

Uncalibrated (never ranked):

| product | reason | A/A valid/expected |
|---|---|---|
| Prime Agent Rust | partial A/A calibration (10/20 valid rows) | 10/20 |
| Prime Agent TS | partial A/A calibration (10/20 valid rows) | 10/20 |
| Pi Mono | partial A/A calibration (10/20 valid rows) | 10/20 |

**Ranks withheld — incomplete_cohort**: expected cohort ['rust', 'ts', 'pi'] — uncalibrated: pi, rust, ts

## compare.msg_send

| product | trials | submit_to_ack_ms | submit_to_settle_ms | rank | Δ vs TS |
|---|---|---|---|---|---|
| Prime Agent Rust | aa=10 cmp5=10 | 37.0 (n10) | 758.4 (n10) | — | — |
| Prime Agent TS | aa=10 cmp5=10 | 2.1 (n10) | 878.4 (n10) | — | baseline |
| Claude Code | aa=10 cmp5=10 | 81.0 (n10) | 713.2 (n10) | — | — |
| Codex CLI | aa=10 cmp5=10 | 0.3 (n10) | 995.9 (n10) | — | — |
| Pi Mono | aa=10 cmp5=10 | 0.7 (n10) | 687.8 (n10) | — | — |

_Comparability: Prime Agent Rust=qualified, Prime Agent TS=qualified, Claude Code=qualified, Codex CLI=qualified, Pi Mono=qualified_

Unstable (never ranked):

| product | reason | detail |
|---|---|---|
| Prime Agent Rust | aa_drift | A/A p50 44.5 vs W1 p50 37.0 (+20.3% drift) |
| Claude Code | aa_spread | A/A spread over threshold — submit_to_ack_ms: a=83.5 b=94.9 (13.7%) |
| Pi Mono | aa_drift | A/A p50 0.9 vs W1 p50 0.7 (+28.6% drift) |
| Pi Mono | aa_spread | A/A spread over threshold — submit_to_ack_ms: a=0.7 b=0.9 (28.6%) |

Uncalibrated (never ranked):

| product | reason | A/A valid/expected |
|---|---|---|
| Prime Agent Rust | partial A/A calibration (10/20 valid rows) | 10/20 |
| Prime Agent TS | partial A/A calibration (10/20 valid rows) | 10/20 |
| Claude Code | partial A/A calibration (10/20 valid rows) | 10/20 |
| Codex CLI | partial A/A calibration (10/20 valid rows) | 10/20 |
| Pi Mono | partial A/A calibration (10/20 valid rows) | 10/20 |

**Ranks withheld — incomplete_cohort**: expected cohort ['rust', 'ts', 'claude', 'codex', 'pi'] — uncalibrated: claude, codex, pi, rust, ts; unstable: claude, pi, rust

## compare.scroll_typing

| product | trials | launch_to_ready_ms | nproc_10mib | pss_10mib_mb | pty_bytes | rss_10mib_mb | scroll_pgup_ms_p50 | scroll_pgup_ms_p95 | typing_ms_p50 | typing_ms_p95 | typing_ok | typing_scrolled_ms_p50 | typing_scrolled_ms_p95 | wheel_bursts | wheel_bytes | rank | Δ vs TS |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Prime Agent Rust | aa=10 cmp5=10 | 2099.1 (n10) | 4 (n10) | 167.7 (n10) | 209103 (n10) | 204.4 (n10) | 9.6 (n10) | 14.1 (n10) | 1.1 (n10) | 1.2 (n10) | 1 (n10) | 0.3 (n10) | 0.3 (n10) | 1 (n10) | 146715 (n10) | — | — |
| Prime Agent TS | aa=10 cmp5=10 | 737.6 (n10) | 4 (n10) | 493.2 (n10) | 42706 (n10) | 713.6 (n10) | 9.0 (n10) | 10.1 (n10) | 3.1 (n10) | 4.9 (n10) | 1 (n10) | 3.4 (n10) | 4.3 (n10) | 0 (n10) | 0 (n10) | — | baseline |
| Pi Mono | aa=10 cmp5=10 | 269.1 (n10) | 1 (n10) | 177.5 (n10) | 911665 (n10) | 179.4 (n10) | — | — | 3.2 (n10) | 4.6 (n10) | 1 (n10) | 4.0 (n10) | 5.2 (n10) | 1 (n10) | 11 (n10) | — | — |

Status (no trials ran):

- Claude Code: not_comparable — claude has no native session-10mib-v4 fixture: its argv ignores resume_fixture, and spec §F large-session rows require a vendor-native fixture (sentinel + message count equivalence)
- Codex CLI: not_comparable — codex has no native session-10mib-v4 fixture: its argv ignores resume_fixture, and spec §F large-session rows require a vendor-native fixture (sentinel + message count equivalence)

_Comparability: Prime Agent Rust=equivalent, Prime Agent TS=equivalent, Pi Mono=equivalent_

_Disclosures: Prime Agent TS: probe_quantized=10; Pi Mono: probe_quantized=10_

Unstable (never ranked):

| product | reason | detail |
|---|---|---|
| Prime Agent TS | aa_drift | A/A p50 3.5 vs W1 p50 3.1 (+12.9% drift) |
| Pi Mono | aa_drift | A/A p50 3.6 vs W1 p50 3.2 (+12.5% drift) |

Uncalibrated (never ranked):

| product | reason | A/A valid/expected |
|---|---|---|
| Prime Agent Rust | partial A/A calibration (10/20 valid rows) | 10/20 |
| Prime Agent TS | partial A/A calibration (10/20 valid rows) | 10/20 |
| Pi Mono | partial A/A calibration (10/20 valid rows) | 10/20 |

**Ranks withheld — incomplete_cohort**: expected cohort ['rust', 'ts', 'pi'] — uncalibrated: pi, rust, ts; unstable: pi, ts

## compare.warm_start

| product | trials | erase_ms | erase_ok | frame_bursts | input_ready_gap_ms | launch_to_first_paint_ms | launch_to_ready_ms | nproc_settled | pss_settled_mb | pty_bytes | rss_settled_mb | tree_nproc | unconfirmed_attempts | rank | Δ vs TS |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Prime Agent Rust | aa=10 cmp5=10 | 34.0 (n10) | 1 (n10) | 4 (n10) | 2032.3 (n10) | 8.6 (n10) | 2041.1 (n10) | 1 (n10) | 31.9 (n10) | 23864 (n10) | 42.4 (n10) | 1 (n10) | 21 (n10) | — | — |
| Prime Agent TS | aa=10 cmp5=10 | 25.1 (n10) | 1 (n10) | 2 (n10) | 12.9 (n10) | 535.9 (n10) | 548.4 (n10) | 1 (n10) | 131.2 (n10) | 4840 (n10) | 203.9 (n10) | 1 (n10) | 0 (n10) | — | baseline |
| Claude Code | aa=10 cmp5=10 | 13.4 (n10) | 1 (n10) | 2 (n10) | 32.4 (n10) | 240.4 (n10) | 272.8 (n10) | 1 (n10) | 220.8 (n10) | 2269 (n10) | 222.5 (n10) | 1 (n10) | 0 (n10) | — | — |
| Codex CLI | aa=10 cmp5=10 | 7.5 (n10) | 1 (n10) | 3 (n10) | 19.9 (n10) | 275.8 (n10) | 295.5 (n10) | 3 (n10) | 261.5 (n10) | 6989 (n10) | 264.7 (n10) | 3 (n10) | 0 (n10) | — | — |
| Pi Mono | aa=10 cmp5=10 | 7.1 (n10) | 1 (n10) | 2 (n10) | 6.5 (n10) | 173.4 (n10) | 179.9 (n10) | 1 (n10) | 127.1 (n10) | 3879 (n10) | 128.9 (n10) | 1 (n10) | 0 (n10) | — | — |

_Comparability: Prime Agent Rust=qualified, Prime Agent TS=qualified, Claude Code=qualified, Codex CLI=qualified, Pi Mono=qualified_

_Disclosures: Prime Agent TS: probe_quantized=10; Claude Code: probe_quantized=10; Codex CLI: probe_quantized=10; Pi Mono: probe_quantized=10_

Uncalibrated (never ranked):

| product | reason | A/A valid/expected |
|---|---|---|
| Prime Agent Rust | partial A/A calibration (10/20 valid rows) | 10/20 |
| Prime Agent TS | partial A/A calibration (10/20 valid rows) | 10/20 |
| Claude Code | partial A/A calibration (10/20 valid rows) | 10/20 |
| Codex CLI | partial A/A calibration (10/20 valid rows) | 10/20 |
| Pi Mono | partial A/A calibration (10/20 valid rows) | 10/20 |

**Ranks withheld — incomplete_cohort**: expected cohort ['rust', 'ts', 'claude', 'codex', 'pi'] — uncalibrated: claude, codex, pi, rust, ts

## daemon.boot

| product | trials | create_ok | hello_ok | spawn_to_accept_ms | spawn_to_first_create_ms | spawn_to_hello_ms | rank | Δ vs TS |
|---|---|---|---|---|---|---|---|---|
| Prime Agent Rust | aa=10 cmp5=10 | 1 (n10) | 1 (n10) | 51.1 (n10) | 236.9 (n10) | 51.3 (n10) | — | — |
| Prime Agent TS | aa=10 cmp5=10 | 1 (n10) | 1 (n10) | 113.2 (n10) | 405.0 (n10) | 115.0 (n10) | — | baseline |

Status (no trials ran):

- Claude Code: not_applicable — benchmark applies to ['rust', 'ts'] only
- Codex CLI: not_applicable — benchmark applies to ['rust', 'ts'] only
- Pi Mono: not_applicable — benchmark applies to ['rust', 'ts'] only

_Comparability: Prime Agent Rust=qualified, Prime Agent TS=qualified_

Unstable (never ranked):

| product | reason | detail |
|---|---|---|
| Prime Agent Rust | aa_drift | A/A p50 46.1 vs W1 p50 51.1 (+10.8% drift) |
| Prime Agent Rust | aa_spread | A/A spread over threshold — spawn_to_accept_ms: a=51.0 b=46.0 (10.9%) |

Uncalibrated (never ranked):

| product | reason | A/A valid/expected |
|---|---|---|
| Prime Agent Rust | partial A/A calibration (10/20 valid rows) | 10/20 |
| Prime Agent TS | partial A/A calibration (10/20 valid rows) | 10/20 |

**Ranks withheld — incomplete_cohort**: expected cohort ['rust', 'ts'] — uncalibrated: rust, ts; unstable: rust

## session.agent_view_roundtrip

| product | trials | agents_chrome_ms | agents_to_tail_ms | chat_ready_after_ms | chat_to_agents_ms | launch_to_ready_ms | nproc_10mib | pss_10mib_mb | pty_bytes | roundtrip_ok | rss_10mib_mb | rank | Δ vs TS |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Prime Agent Rust | aa=10 cmp5=10 | 119.0 (n10) | 22866.9 (n10) | 22869.7 (n10) | 119.8 (n10) | 21408.9 (n10) | 4 (n10) | 661.3 (n10) | 76721 (n10) | 1 (n10) | 698.3 (n10) | — | — |
| Prime Agent TS | aa=10 cmp5=10 | 66.3 (n10) | 1799.8 (n10) | 1808.1 (n10) | 67.1 (n10) | 786.2 (n10) | 5 (n10) | 1058.8 (n10) | 24671 (n10) | 1 (n10) | 1385.3 (n10) | — | baseline |

Status (no trials ran):

- Claude Code: not_applicable — session.* benchmarks resume the Prime session fixture; BENCHMARK_SUITE_SPEC section A scopes them to Prime Agent Rust/TS
- Codex CLI: not_applicable — session.* benchmarks resume the Prime session fixture; BENCHMARK_SUITE_SPEC section A scopes them to Prime Agent Rust/TS
- Pi Mono: not_applicable — session.* benchmarks resume the Prime session fixture; BENCHMARK_SUITE_SPEC section A scopes them to Prime Agent Rust/TS

_Comparability: Prime Agent Rust=equivalent, Prime Agent TS=equivalent_

Uncalibrated (never ranked):

| product | reason | A/A valid/expected |
|---|---|---|
| Prime Agent Rust | partial A/A calibration (10/20 valid rows) | 10/20 |
| Prime Agent TS | partial A/A calibration (10/20 valid rows) | 10/20 |

**Ranks withheld — incomplete_cohort**: expected cohort ['rust', 'ts'] — uncalibrated: rust, ts

## session.cold_open_10mib

| product | trials | frame_bursts | input_ready_gap_ms | launch_to_complete_ms | launch_to_first_paint_ms | launch_to_ready_ms | launch_to_sentinel_ms | nproc_10mib | pss_10mib_mb | pty_bytes | rss_10mib_mb | rank | Δ vs TS |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Prime Agent Rust | aa=10 cmp5=10 | 3 (n10) | 2038.0 (n10) | 2078.4 (n10) | 37.5 (n10) | 2075.5 (n10) | 2078.4 (n10) | 4 (n10) | 170.0 (n10) | 35539 (n10) | 206.2 (n10) | — | — |
| Prime Agent TS | aa=10 cmp5=10 | 2 (n10) | 13.1 (n10) | 891.1 (n10) | 719.9 (n10) | 734.5 (n10) | 891.1 (n10) | 4 (n10) | 472.1 (n10) | 9006 (n10) | 692.5 (n10) | — | baseline |

Status (no trials ran):

- Claude Code: not_applicable — session.* benchmarks resume the Prime session fixture; BENCHMARK_SUITE_SPEC §A scopes them to Prime Agent Rust/TS
- Codex CLI: not_applicable — session.* benchmarks resume the Prime session fixture; BENCHMARK_SUITE_SPEC §A scopes them to Prime Agent Rust/TS
- Pi Mono: not_applicable — session.* benchmarks resume the Prime session fixture; BENCHMARK_SUITE_SPEC §A scopes them to Prime Agent Rust/TS

_Comparability: Prime Agent Rust=equivalent, Prime Agent TS=equivalent_

_Disclosures: Prime Agent TS: probe_quantized=10_

Uncalibrated (never ranked):

| product | reason | A/A valid/expected |
|---|---|---|
| Prime Agent Rust | partial A/A calibration (10/20 valid rows) | 10/20 |
| Prime Agent TS | partial A/A calibration (10/20 valid rows) | 10/20 |

**Ranks withheld — incomplete_cohort**: expected cohort ['rust', 'ts'] — uncalibrated: rust, ts

## A/A calibration

| pair | p50 a | p50 b | spread | valid |
|---|---|---|---|---|
| session.cold_open_10mib/rust | 2101.8 | 2103.0 | 0.1% | YES |
| session.cold_open_10mib/ts | 915.5 | 913.6 | 0.2% | YES |
| compare.scroll_typing/rust | 1.2 | 1.1 | 9.1% | YES |
| compare.scroll_typing/ts | 3.7 | 3.5 | 5.7% | YES |
| compare.scroll_typing/pi | 3.6 | 3.9 | 8.3% | YES |
| daemon.boot/rust | 51.0 | 46.0 | 10.9% | NO |
| daemon.boot/ts | 114.0 | 117.5 | 3.1% | YES |
| session.agent_view_roundtrip/rust | 119.4 | 120.2 | 0.7% | YES |
| session.agent_view_roundtrip/rust/agents_to_tail_ms | 23080.0 | 23144.9 | 0.3% | YES |
| session.agent_view_roundtrip/rust/chat_ready_after_ms | 23083.0 | 23148.0 | 0.3% | YES |
| session.agent_view_roundtrip/ts | 69.2 | 66.7 | 3.7% | YES |
| session.agent_view_roundtrip/ts/agents_to_tail_ms | 1830.4 | 1877.5 | 2.6% | YES |
| session.agent_view_roundtrip/ts/chat_ready_after_ms | 1837.3 | 1883.2 | 2.5% | YES |
| compare.msg_send/rust | 44.5 | 44.8 | 0.7% | YES |
| compare.msg_send/rust/submit_to_settle_ms | 767.5 | 775.0 | 1.0% | YES |
| compare.msg_send/ts | 2.3 | 2.5 | 8.7% | YES |
| compare.msg_send/ts/submit_to_settle_ms | 926.3 | 900.2 | 2.9% | YES |
| compare.msg_send/claude | 83.5 | 94.9 | 13.7% | NO |
| compare.msg_send/claude/submit_to_settle_ms | 712.2 | 715.2 | 0.4% | YES |
| compare.msg_send/codex | 0.3 | 0.3 | 0.0% | YES |
| compare.msg_send/codex/submit_to_settle_ms | 1041.7 | 1021.0 | 2.0% | YES |
| compare.msg_send/pi | 0.7 | 0.9 | 28.6% | NO |
| compare.msg_send/pi/submit_to_settle_ms | 689.8 | 690.1 | 0.0% | YES |
| compare.install_disk/rust | 205867840 | 205867840 | 0.0% | YES |
| compare.install_disk/ts | 172147733 | 172147733 | 0.0% | YES |
| compare.install_disk/claude | 474960387 | 474960387 | 0.0% | YES |
| compare.install_disk/codex | 386998144 | 386998144 | 0.0% | YES |
| compare.install_disk/pi | 466087714 | 466087714 | 0.0% | YES |
| compare.warm_start/rust | 2053.3 | 2048.0 | 0.3% | YES |
| compare.warm_start/ts | 540.1 | 548.7 | 1.6% | YES |
| compare.warm_start/claude | 275.0 | 291.2 | 5.9% | YES |
| compare.warm_start/codex | 295.4 | 293.7 | 0.6% | YES |
| compare.warm_start/pi | 189.9 | 187.7 | 1.2% | YES |
| compare.memory_idle_load/rust | 207.6 | 205.2 | 1.2% | YES |
| compare.memory_idle_load/ts | 694.8 | 696.6 | 0.3% | YES |
| compare.memory_idle_load/pi | 193.8 | 196.4 | 1.3% | YES |
| compare.cold_start/rust | 2080.7 | 2096.0 | 0.7% | YES |
| compare.cold_start/ts | 701.9 | 732.5 | 4.4% | YES |
| compare.cold_start/claude | 274.1 | 296.2 | 8.1% | YES |
| compare.cold_start/codex | 298.2 | 294.3 | 1.3% | YES |
| compare.cold_start/pi | 250.3 | 253.8 | 1.4% | YES |

_A/A coverage: 9/9 benchmarks calibrated — an A/A table entry is the only noise evidence, its absence is never an OK._
