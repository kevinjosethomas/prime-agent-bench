# Benchmark summary

_Published phases: cmp5b; A/A rows calibrate only, never publish; gate: strict result-validity (bench.analysis.validity)._

## compare.cold_start

| product | trials | erase_ms | erase_ok | frame_bursts | input_ready_gap_ms | launch_to_first_paint_ms | launch_to_ready_ms | nproc_settled | pss_settled_mb | pty_bytes | rss_settled_mb | tree_nproc | unconfirmed_attempts | rank | Δ vs TS |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Prime Agent Rust | aa=20 cmp5b=10 | 37.5 (n10) | 1 (n10) | 3 (n10) | 2032.2 (n10) | 35.3 (n10) | 2068.1 (n10) | 4 (n10) | 111.1 (n10) | 23867 (n10) | 147.7 (n10) | 4 (n10) | 21 (n10) | 5 | +199% |
| Prime Agent TS | aa=20 cmp5b=10 | 23.8 (n10) | 1 (n10) | 2 (n10) | 13.1 (n10) | 677.9 (n10) | 691.1 (n10) | 4 (n10) | 394.9 (n10) | 4840 (n10) | 615.1 (n10) | 4 (n10) | 0 (n10) | 4 | +0% |
| Claude Code | aa=20 cmp5b=10 | 13.2 (n10) | 1 (n10) | 2 (n10) | 30.8 (n10) | 246.1 (n10) | 277.2 (n10) | 1 (n10) | 220.6 (n10) | 2270 (n10) | 222.3 (n10) | 1 (n10) | 0 (n10) | 2 | -60% |
| Codex CLI | aa=20 cmp5b=10 | 7.1 (n10) | 1 (n10) | 3 (n10) | 19.1 (n10) | 277.0 (n10) | 295.9 (n10) | 3 (n10) | 267.1 (n10) | 7062 (n10) | 270.3 (n10) | 3 (n10) | 0 (n10) | 3 | -57% |
| Pi Mono | aa=20 cmp5b=10 | 7.2 (n10) | 1 (n10) | 2 (n10) | 6.6 (n10) | 238.8 (n10) | 245.2 (n10) | 1 (n10) | 145.3 (n10) | 3881 (n10) | 147.2 (n10) | 1 (n10) | 0 (n10) | 1 | -64% |

_Comparability: Prime Agent Rust=qualified, Prime Agent TS=qualified, Claude Code=qualified, Codex CLI=qualified, Pi Mono=qualified_

_Disclosures: Prime Agent TS: probe_quantized=10; Claude Code: probe_quantized=10; Codex CLI: probe_quantized=10; Pi Mono: probe_quantized=10_

## compare.install_disk

| product | trials | download_bytes | installed_bytes | rank | Δ vs TS |
|---|---|---|---|---|---|
| Prime Agent Rust | aa=20 cmp5b=10 | 7843159 (n10) | 205867840 (n10) | 2 | +20% |
| Prime Agent TS | aa=20 cmp5b=10 | 172147733 (n10) | 172147733 (n10) | 1 | +0% |
| Claude Code | aa=20 cmp5b=10 | 27580 (n10) | 474960387 (n10) | 4 | +176% |
| Codex CLI | aa=20 cmp5b=10 | 4904 (n10) | 386998144 (n10) | 3 | +125% |
| Pi Mono | aa=20 cmp5b=10 | 0 (n10) | 466087714 (n10) | — | — |

_Comparability: Prime Agent Rust=qualified, Prime Agent TS=qualified, Claude Code=qualified, Codex CLI=qualified, Pi Mono=qualified_

## compare.memory_idle_load

| product | trials | launch_to_ready_ms | nproc_settled | pss_settled_mb | rss_settled_mb | tree_nproc | rank | Δ vs TS |
|---|---|---|---|---|---|---|---|---|
| Prime Agent Rust | aa=20 cmp5b=10 | 2075.1 (n10) | 4 (n10) | 168.7 (n10) | 205.2 (n10) | 4 (n10) | 2 | -70% |
| Prime Agent TS | aa=20 cmp5b=10 | 723.8 (n10) | 4 (n10) | 472.9 (n10) | 693.1 (n10) | 4 (n10) | 3 | +0% |
| Pi Mono | aa=20 cmp5b=10 | 270.2 (n10) | 1 (n10) | 192.3 (n10) | 194.2 (n10) | 1 (n10) | 1 | -72% |

Status (no trials ran):

- Claude Code: not_comparable — claude has no native session-10mib-v4 fixture: its argv ignores resume_fixture, and spec §F large-session rows require a vendor-native fixture (sentinel + message count equivalence)
- Codex CLI: not_comparable — codex has no native session-10mib-v4 fixture: its argv ignores resume_fixture, and spec §F large-session rows require a vendor-native fixture (sentinel + message count equivalence)

_Comparability: Prime Agent Rust=equivalent, Prime Agent TS=equivalent, Pi Mono=equivalent_

_Disclosures: Prime Agent TS: probe_quantized=10; Pi Mono: probe_quantized=10_

## compare.msg_send

| product | trials | submit_to_ack_ms | submit_to_settle_ms | rank | Δ vs TS |
|---|---|---|---|---|---|
| Prime Agent Rust | aa=20 cmp5b=10 | 33.7 (n10) | 747.0 (n10) | — | — |
| Prime Agent TS | aa=20 cmp5b=10 | 2.1 (n10) | 856.0 (n10) | — | baseline |
| Claude Code | aa=20 cmp5b=10 | 53.7 (n10) | 720.0 (n10) | — | — |
| Codex CLI | aa=20 cmp5b=10 | 0.3 (n10) | 969.7 (n10) | — | — |
| Pi Mono | aa=20 cmp5b=10 | 0.7 (n10) | 687.2 (n10) | — | — |

_Comparability: Prime Agent Rust=qualified, Prime Agent TS=qualified, Claude Code=qualified, Codex CLI=qualified, Pi Mono=qualified_

Unstable (never ranked):

| product | reason | detail |
|---|---|---|
| Prime Agent Rust | aa_spread | A/A spread over threshold — submit_to_ack_ms: a=38.2 b=33.0 (15.8%) |
| Prime Agent TS | aa_drift | A/A p50 2.6 vs W1 p50 2.1 (+23.8% drift) |
| Claude Code | aa_drift | A/A p50 80.3 vs W1 p50 53.7 (+49.5% drift) |
| Claude Code | aa_spread | A/A spread over threshold — submit_to_ack_ms: a=57.9 b=82.1 (41.8%) |
| Codex CLI | aa_drift | A/A p50 0.4 vs W1 p50 0.3 (+33.3% drift) |
| Codex CLI | aa_spread | A/A spread over threshold — submit_to_ack_ms: a=0.4 b=0.3 (33.3%) |

**Ranks withheld — incomplete_cohort**: expected cohort ['rust', 'ts', 'claude', 'codex', 'pi'] — unstable: claude, codex, rust, ts

## compare.scroll_typing

| product | trials | launch_to_ready_ms | nproc_10mib | pss_10mib_mb | pty_bytes | rss_10mib_mb | scroll_pgup_ms_p50 | scroll_pgup_ms_p95 | typing_ms_p50 | typing_ms_p95 | typing_ok | typing_scrolled_ms_p50 | typing_scrolled_ms_p95 | wheel_bursts | wheel_bytes | rank | Δ vs TS |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Prime Agent Rust | aa=20 cmp5b=10 | 2073.1 (n10) | 4 (n10) | 165.4 (n10) | 209104 (n10) | 202.4 (n10) | 9.2 (n10) | 13.4 (n10) | 1.1 (n10) | 1.3 (n10) | 1 (n10) | 0.2 (n10) | 0.3 (n10) | 1 (n10) | 146715 (n10) | — | — |
| Prime Agent TS | aa=20 cmp5b=10 | 698.4 (n10) | 4 (n10) | 492.8 (n10) | 42736 (n10) | 713.1 (n10) | 8.1 (n10) | 8.9 (n10) | 3.0 (n10) | 4.8 (n10) | 1 (n10) | 3.0 (n10) | 3.7 (n10) | 0 (n10) | 0 (n10) | — | baseline |
| Pi Mono | aa=20 cmp5b=10 | 269.6 (n10) | 1 (n10) | 176.9 (n10) | 911665 (n10) | 178.8 (n10) | — | — | 3.3 (n10) | 4.7 (n10) | 1 (n10) | 3.8 (n10) | 5.6 (n10) | 1 (n10) | 11 (n10) | — | — |

Status (no trials ran):

- Claude Code: not_comparable — claude has no native session-10mib-v4 fixture: its argv ignores resume_fixture, and spec §F large-session rows require a vendor-native fixture (sentinel + message count equivalence)
- Codex CLI: not_comparable — codex has no native session-10mib-v4 fixture: its argv ignores resume_fixture, and spec §F large-session rows require a vendor-native fixture (sentinel + message count equivalence)

_Comparability: Prime Agent Rust=equivalent, Prime Agent TS=equivalent, Pi Mono=equivalent_

_Disclosures: Prime Agent TS: probe_quantized=8; Pi Mono: probe_quantized=10_

Unstable (never ranked):

| product | reason | detail |
|---|---|---|
| Pi Mono | aa_drift | A/A p50 3.8 vs W1 p50 3.3 (+15.2% drift) |
| Pi Mono | aa_spread | A/A spread over threshold — typing_ms_p50: a=3.3 b=3.8 (15.2%) |

**Ranks withheld — incomplete_cohort**: expected cohort ['rust', 'ts', 'pi'] — unstable: pi

## compare.warm_start

| product | trials | erase_ms | erase_ok | frame_bursts | input_ready_gap_ms | launch_to_first_paint_ms | launch_to_ready_ms | nproc_settled | pss_settled_mb | pty_bytes | rss_settled_mb | tree_nproc | unconfirmed_attempts | rank | Δ vs TS |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Prime Agent Rust | aa=20 cmp5b=10 | 37.5 (n10) | 1 (n10) | 4 (n10) | 2036.6 (n10) | 9.3 (n10) | 2045.4 (n10) | 1 (n10) | 32.1 (n10) | 23867 (n10) | 42.6 (n10) | 1 (n10) | 21 (n10) | 5 | +268% |
| Prime Agent TS | aa=20 cmp5b=10 | 24.3 (n10) | 1 (n10) | 2 (n10) | 13.9 (n10) | 541.9 (n10) | 555.2 (n10) | 1 (n10) | 133.1 (n10) | 4840 (n10) | 205.7 (n10) | 1 (n10) | 0 (n10) | 4 | +0% |
| Claude Code | aa=20 cmp5b=10 | 13.4 (n10) | 1 (n10) | 2 (n10) | 33.1 (n10) | 244.7 (n10) | 278.4 (n10) | 1 (n10) | 221.1 (n10) | 2270 (n10) | 222.8 (n10) | 1 (n10) | 0 (n10) | 2 | -50% |
| Codex CLI | aa=20 cmp5b=10 | 7.0 (n10) | 1 (n10) | 3 (n10) | 18.8 (n10) | 275.4 (n10) | 294.7 (n10) | 3 (n10) | 269.3 (n10) | 7103 (n10) | 278.8 (n10) | 3 (n10) | 0 (n10) | 3 | -47% |
| Pi Mono | aa=20 cmp5b=10 | 7.1 (n10) | 1 (n10) | 2 (n10) | 6.6 (n10) | 177.2 (n10) | 183.9 (n10) | 1 (n10) | 127.2 (n10) | 3881 (n10) | 129.1 (n10) | 1 (n10) | 0 (n10) | 1 | -67% |

_Comparability: Prime Agent Rust=qualified, Prime Agent TS=qualified, Claude Code=qualified, Codex CLI=qualified, Pi Mono=qualified_

_Disclosures: Prime Agent TS: probe_quantized=10; Claude Code: probe_quantized=10; Codex CLI: probe_quantized=10; Pi Mono: probe_quantized=10_

## daemon.boot

| product | trials | create_ok | hello_ok | spawn_to_accept_ms | spawn_to_first_create_ms | spawn_to_hello_ms | rank | Δ vs TS |
|---|---|---|---|---|---|---|---|---|
| Prime Agent Rust | aa=20 cmp5b=10 | 1 (n10) | 1 (n10) | 46.2 (n10) | 229.7 (n10) | 46.3 (n10) | — | — |
| Prime Agent TS | aa=20 cmp5b=10 | 1 (n10) | 1 (n10) | 122.8 (n10) | 420.8 (n10) | 125.7 (n10) | — | baseline |

Status (no trials ran):

- Claude Code: not_applicable — benchmark applies to ['rust', 'ts'] only
- Codex CLI: not_applicable — benchmark applies to ['rust', 'ts'] only
- Pi Mono: not_applicable — benchmark applies to ['rust', 'ts'] only

_Comparability: Prime Agent Rust=qualified, Prime Agent TS=qualified_

Unstable (never ranked):

| product | reason | detail |
|---|---|---|
| Prime Agent Rust | aa_drift | A/A p50 51.0 vs W1 p50 46.2 (+10.4% drift) |
| Prime Agent Rust | aa_spread | A/A spread over threshold — spawn_to_accept_ms: a=51.0 b=46.0 (10.9%) |

**Ranks withheld — incomplete_cohort**: expected cohort ['rust', 'ts'] — unstable: rust

## session.agent_view_roundtrip

| product | trials | agents_chrome_ms | agents_to_tail_ms | chat_ready_after_ms | chat_to_agents_ms | launch_to_ready_ms | nproc_10mib | pss_10mib_mb | pty_bytes | roundtrip_ok | rss_10mib_mb | rank | Δ vs TS |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Prime Agent Rust | aa=20 cmp5b=10 | 118.4 (n10) | 22729.6 (n10) | 22732.6 (n10) | 119.2 (n10) | 21340.3 (n10) | 4 (n10) | 660.5 (n10) | 76767 (n10) | 1 (n10) | 696.8 (n10) | 2 | +79% |
| Prime Agent TS | aa=20 cmp5b=10 | 65.9 (n10) | 1791.7 (n10) | 1797.9 (n10) | 66.7 (n10) | 756.0 (n10) | 5 (n10) | 1014.4 (n10) | 24671 (n10) | 1 (n10) | 1340.9 (n10) | 1 | +0% |

Status (no trials ran):

- Claude Code: not_applicable — session.* benchmarks resume the Prime session fixture; BENCHMARK_SUITE_SPEC section A scopes them to Prime Agent Rust/TS
- Codex CLI: not_applicable — session.* benchmarks resume the Prime session fixture; BENCHMARK_SUITE_SPEC section A scopes them to Prime Agent Rust/TS
- Pi Mono: not_applicable — session.* benchmarks resume the Prime session fixture; BENCHMARK_SUITE_SPEC section A scopes them to Prime Agent Rust/TS

_Comparability: Prime Agent Rust=equivalent, Prime Agent TS=equivalent_

## session.cold_open_10mib

| product | trials | frame_bursts | input_ready_gap_ms | launch_to_complete_ms | launch_to_first_paint_ms | launch_to_ready_ms | launch_to_sentinel_ms | nproc_10mib | pss_10mib_mb | pty_bytes | rss_10mib_mb | rank | Δ vs TS |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Prime Agent Rust | aa=20 cmp5b=10 | 3 (n10) | 2038.7 (n10) | 2077.7 (n10) | 35.5 (n10) | 2074.9 (n10) | 2077.7 (n10) | 4 (n10) | 167.4 (n10) | 35540 (n10) | 203.5 (n10) | 2 | +137% |
| Prime Agent TS | aa=20 cmp5b=10 | 2 (n10) | 11.8 (n10) | 875.9 (n10) | 705.0 (n10) | 716.4 (n10) | 875.9 (n10) | 4 (n10) | 474.0 (n10) | 9006 (n10) | 694.3 (n10) | 1 | +0% |

Status (no trials ran):

- Claude Code: not_applicable — session.* benchmarks resume the Prime session fixture; BENCHMARK_SUITE_SPEC §A scopes them to Prime Agent Rust/TS
- Codex CLI: not_applicable — session.* benchmarks resume the Prime session fixture; BENCHMARK_SUITE_SPEC §A scopes them to Prime Agent Rust/TS
- Pi Mono: not_applicable — session.* benchmarks resume the Prime session fixture; BENCHMARK_SUITE_SPEC §A scopes them to Prime Agent Rust/TS

_Comparability: Prime Agent Rust=equivalent, Prime Agent TS=equivalent_

_Disclosures: Prime Agent TS: probe_quantized=9_

## A/A calibration

| pair | p50 a | p50 b | spread | valid |
|---|---|---|---|---|
| session.cold_open_10mib/rust | 2084.3 | 2078.2 | 0.3% | YES |
| session.cold_open_10mib/ts | 938.8 | 906.7 | 3.5% | YES |
| compare.scroll_typing/rust | 1.1 | 1.1 | 0.0% | YES |
| compare.scroll_typing/ts | 3.3 | 3.2 | 3.1% | YES |
| compare.scroll_typing/pi | 3.3 | 3.8 | 15.2% | NO |
| daemon.boot/rust | 51.0 | 46.0 | 10.9% | NO |
| daemon.boot/ts | 125.6 | 118.9 | 5.6% | YES |
| session.agent_view_roundtrip/rust | 119.3 | 119.3 | 0.0% | YES |
| session.agent_view_roundtrip/rust/agents_to_tail_ms | 22936.1 | 22820.8 | 0.5% | YES |
| session.agent_view_roundtrip/rust/chat_ready_after_ms | 22942.0 | 22823.8 | 0.5% | YES |
| session.agent_view_roundtrip/ts | 65.3 | 67.0 | 2.6% | YES |
| session.agent_view_roundtrip/ts/agents_to_tail_ms | 1785.8 | 1808.6 | 1.3% | YES |
| session.agent_view_roundtrip/ts/chat_ready_after_ms | 1793.2 | 1820.1 | 1.5% | YES |
| compare.msg_send/rust | 38.2 | 33.0 | 15.8% | NO |
| compare.msg_send/rust/submit_to_settle_ms | 750.3 | 747.4 | 0.4% | YES |
| compare.msg_send/ts | 2.5 | 2.6 | 4.0% | YES |
| compare.msg_send/ts/submit_to_settle_ms | 900.2 | 861.5 | 4.5% | YES |
| compare.msg_send/claude | 57.9 | 82.1 | 41.8% | NO |
| compare.msg_send/claude/submit_to_settle_ms | 717.1 | 708.6 | 1.2% | YES |
| compare.msg_send/codex | 0.4 | 0.3 | 33.3% | NO |
| compare.msg_send/codex/submit_to_settle_ms | 1014.6 | 975.0 | 4.1% | YES |
| compare.msg_send/pi | 0.7 | 0.7 | 0.0% | YES |
| compare.msg_send/pi/submit_to_settle_ms | 688.3 | 688.5 | 0.0% | YES |
| compare.install_disk/rust | 205867840 | 205867840 | 0.0% | YES |
| compare.install_disk/ts | 172147733 | 172147733 | 0.0% | YES |
| compare.install_disk/claude | 474960387 | 474960387 | 0.0% | YES |
| compare.install_disk/codex | 386998144 | 386998144 | 0.0% | YES |
| compare.install_disk/pi | 466087714 | 466087714 | 0.0% | YES |
| compare.warm_start/rust | 2040.8 | 2053.8 | 0.6% | YES |
| compare.warm_start/ts | 558.9 | 568.6 | 1.7% | YES |
| compare.warm_start/claude | 280.9 | 277.6 | 1.2% | YES |
| compare.warm_start/codex | 294.8 | 294.4 | 0.1% | YES |
| compare.warm_start/pi | 190.7 | 183.4 | 4.0% | YES |
| compare.memory_idle_load/rust | 203.0 | 206.7 | 1.8% | YES |
| compare.memory_idle_load/ts | 694.1 | 696.7 | 0.4% | YES |
| compare.memory_idle_load/pi | 193.4 | 193.0 | 0.2% | YES |
| compare.cold_start/rust | 2076.9 | 2096.6 | 0.9% | YES |
| compare.cold_start/ts | 694.2 | 679.1 | 2.2% | YES |
| compare.cold_start/claude | 279.3 | 274.4 | 1.8% | YES |
| compare.cold_start/codex | 295.5 | 296.0 | 0.2% | YES |
| compare.cold_start/pi | 241.4 | 255.1 | 5.7% | YES |

_A/A coverage: 9/9 benchmarks calibrated — an A/A table entry is the only noise evidence, its absence is never an OK._
