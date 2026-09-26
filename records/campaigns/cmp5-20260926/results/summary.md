# Benchmark summary

_Published phases: w1, aa; A/A rows calibrate only, never publish; gate: strict result-validity (bench.analysis.validity)._

## compare.cold_start

| product | trials | dropped_probes | erase_ms | erase_ok | frame_bursts | input_ready_gap_ms | launch_to_first_paint_ms | launch_to_ready_ms | nproc_settled | pss_settled_mb | pty_bytes | rss_settled_mb | tree_nproc | rank | Δ vs TS |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Prime Agent Rust | aa=20 w1=10 | 4 (n10) | 9164.4 (n10) | 1 (n10) | 29 (n10) | 256.9 (n10) | 35.9 (n10) | 292.8 (n10) | 4 (n10) | 94.8 (n10) | 6117 (n10) | 133.0 (n10) | 4 (n10) | 2 | -49% |
| Prime Agent TS | aa=20 w1=10 | 0 (n10) | 58.8 (n10) | 1 (n10) | 9 (n10) | 12.9 (n10) | 562.6 (n10) | 575.6 (n10) | 4 (n10) | 420.1 (n10) | 107240 (n10) | 640.4 (n10) | 4 (n10) | 5 | +0% |
| Claude Code | aa=20 w1=10 | 1 (n10) | 2838.0 (n10) | 1 (n10) | 10 (n10) | 67.7 (n10) | 239.5 (n10) | 310.8 (n10) | 1 (n10) | 235.7 (n10) | 2814 (n10) | 237.3 (n10) | 1 (n10) | 4 | -46% |
| Codex CLI | aa=20 w1=10 | 0 (n10) | 116.0 (n10) | 1 (n10) | 3 (n10) | 19.4 (n10) | 275.9 (n10) | 295.7 (n10) | 2 (n10) | 133.2 (n10) | 2767 (n10) | 134.8 (n10) | 2 (n10) | 3 | -49% |
| Pi Mono | aa=20 w1=10 | 0 (n10) | 713.0 (n10) | 1 (n10) | 4 (n10) | 6.4 (n10) | 235.1 (n10) | 241.5 (n10) | 1 (n10) | 144.0 (n10) | 4220 (n10) | 145.9 (n10) | 1 (n10) | 1 | -58% |

_Comparability: Claude Code=qualified, Codex CLI=qualified, Pi Mono=qualified, Prime Agent Rust=qualified, Prime Agent TS=qualified_

**Mixed identity — never aggregate across these rows**: runs ['camp-claude-20260926-020252', 'camp-codex-20260926-020252', 'camp-pi-20260926-020252', 'camp-rust-20260926-020252', 'camp-ts-20260926-020251'], harness ['unknown']

_Disclosures: Codex CLI: probe_quantized=10; Pi Mono: probe_quantized=10; Prime Agent TS: probe_quantized=10_

## compare.install_disk

| product | trials | download_bytes | installed_bytes | rank | Δ vs TS |
|---|---|---|---|---|---|
| Prime Agent Rust | w1=10 | 53291156 (n10) | 206668003 (n10) | 2 | +20% |
| Prime Agent TS | w1=10 | 172192855 (n10) | 172192855 (n10) | 1 | +0% |
| Claude Code | w1=10 | 27581 (n10) | 483322595 (n10) | 5 | +181% |
| Codex CLI | w1=10 | 4902 (n10) | 391253952 (n10) | 3 | +127% |
| Pi Mono | w1=10 | 7329151 (n10) | 462249835 (n10) | 4 | +168% |

_Comparability: Claude Code=qualified, Codex CLI=qualified, Pi Mono=qualified, Prime Agent Rust=qualified, Prime Agent TS=qualified_

**Mixed identity — never aggregate across these rows**: runs ['camp-claude-20260926-021152', 'camp-codex-20260926-021152', 'camp-pi-20260926-021152', 'camp-rust-20260926-021151', 'camp-ts-20260926-021152'], harness ['unknown']

## compare.memory_idle_load

| product | trials | launch_to_ready_ms | nproc_settled | pss_settled_mb | rss_settled_mb | tree_nproc | rank | Δ vs TS |
|---|---|---|---|---|---|---|---|---|
| Prime Agent Rust | w1=10 | 22465.5 (n10) | 4 (n10) | 512.0 (n10) | 550.5 (n10) | 4 (n10) | 1 | -51% |
| Prime Agent TS | w1=8 | 688.1 (n8) | 4 (n8) | 911.5 (n8) | 1131.9 (n8) | 4 (n8) | 2 | +0% |

Status (no trials ran):

- Claude Code: not_comparable — claude has no native session-10mib fixture: its argv ignores resume_fixture, and spec §F large-session rows require a vendor-native fixture (sentinel + message count equivalence)
- Codex CLI: not_comparable — codex has no native session-10mib fixture: its argv ignores resume_fixture, and spec §F large-session rows require a vendor-native fixture (sentinel + message count equivalence)
- Pi Mono: not_comparable — pi has no native session-10mib fixture: its argv ignores resume_fixture, and spec §F large-session rows require a vendor-native fixture (sentinel + message count equivalence)

_Comparability: Prime Agent Rust=equivalent, Prime Agent TS=equivalent_

**Mixed identity — never aggregate across these rows**: runs ['camp-rust-20260926-021151', 'camp-ts-20260926-021152'], harness ['unknown']

_Disclosures: Prime Agent TS: probe_quantized=8_

Excluded from rankings (validity gate):

| product | excluded | reasons |
|---|---|---|
| Prime Agent TS | 2 | fixture_not_confirmed=2 |

## compare.msg_send

| product | trials | submit_to_ack_ms | submit_to_settle_ms | rank | Δ vs TS |
|---|---|---|---|---|---|
| Prime Agent Rust | w1=10 | 1.4 (n10) | 2106.7 (n10) | 3 | -30% |
| Prime Agent TS | w1=10 | 2.0 (n10) | 2023.6 (n10) | 4 | +0% |
| Claude Code | w1=10 | 45.4 (n10) | 5385.9 (n10) | 5 | +2170% |
| Codex CLI | w1=10 | 0.2 (n10) | 2657.1 (n10) | 1 | -90% |
| Pi Mono | w1=10 | 1.1 (n10) | 2689.9 (n10) | 2 | -45% |

_Comparability: Claude Code=qualified, Codex CLI=qualified, Pi Mono=qualified, Prime Agent Rust=qualified, Prime Agent TS=qualified_

**Mixed identity — never aggregate across these rows**: runs ['camp-claude-20260926-033835', 'camp-codex-20260926-033310', 'camp-pi-20260926-021701', 'camp-rust-20260926-040222', 'camp-ts-20260926-034846'], harness ['unknown']

Excluded from rankings (validity gate):

| product | excluded | reasons |
|---|---|---|
| Codex CLI | 1 | real_api_regime=1 |

## compare.scroll_typing

| product | trials | launch_to_ready_ms | nproc_10mib | pss_10mib_mb | pty_bytes | rss_10mib_mb | scroll_pgup_ms_p50 | scroll_pgup_ms_p95 | typing_ms_p50 | typing_ms_p95 | typing_ok | typing_scrolled_ms_p50 | typing_scrolled_ms_p95 | wheel_bursts | wheel_bytes | rank | Δ vs TS |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Prime Agent Rust | w1=10 | 22429.5 (n10) | 4 (n10) | 509.9 (n10) | 76077 (n10) | 547.9 (n10) | 2.7 (n10) | 2.7 (n10) | 1.0 (n10) | 1.2 (n10) | 1 (n10) | 0.2 (n10) | 0.2 (n10) | 1 (n10) | 1320 (n10) | 1 | — |

Status (no trials ran):

- Claude Code: not_comparable — claude has no native session-10mib fixture: its argv ignores resume_fixture, and spec §F large-session rows require a vendor-native fixture (sentinel + message count equivalence)
- Codex CLI: not_comparable — codex has no native session-10mib fixture: its argv ignores resume_fixture, and spec §F large-session rows require a vendor-native fixture (sentinel + message count equivalence)
- Pi Mono: not_comparable — pi has no native session-10mib fixture: its argv ignores resume_fixture, and spec §F large-session rows require a vendor-native fixture (sentinel + message count equivalence)

_Comparability: Prime Agent Rust=equivalent_

Excluded from rankings (validity gate):

| product | excluded | reasons |
|---|---|---|
| Prime Agent TS | 10 | fixture_not_confirmed=1, validation_failed=9 |

## compare.warm_start

| product | trials | dropped_probes | erase_ms | erase_ok | frame_bursts | input_ready_gap_ms | launch_to_first_paint_ms | launch_to_ready_ms | nproc_settled | pss_settled_mb | pty_bytes | rss_settled_mb | tree_nproc | rank | Δ vs TS |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Prime Agent Rust | w1=10 | 4 (n10) | 9141.0 (n10) | 1 (n10) | 30 (n10) | 257.8 (n10) | 17.7 (n10) | 276.3 (n10) | 1 (n10) | 32.5 (n10) | 6161 (n10) | 43.3 (n10) | 1 (n10) | 2 | -35% |
| Prime Agent TS | w1=10 | 0 (n10) | 58.8 (n10) | 1 (n10) | 9 (n10) | 13.4 (n10) | 413.8 (n10) | 427.6 (n10) | 1 (n10) | 150.7 (n10) | 107210 (n10) | 223.4 (n10) | 1 (n10) | 5 | +0% |
| Claude Code | w1=10 | 1 (n10) | 2840.1 (n10) | 1 (n10) | 10 (n10) | 65.5 (n10) | 241.3 (n10) | 310.8 (n10) | 1 (n10) | 235.7 (n10) | 2814 (n10) | 237.4 (n10) | 1 (n10) | 4 | -27% |
| Codex CLI | w1=10 | 0 (n10) | 152.4 (n10) | 1 (n10) | 3 (n10) | 19.4 (n10) | 276.7 (n10) | 297.1 (n10) | 2 (n10) | 133.3 (n10) | 2767 (n10) | 134.9 (n10) | 2 (n10) | 3 | -30% |
| Pi Mono | w1=10 | 0 (n10) | 715.3 (n10) | 1 (n10) | 4 (n10) | 6.3 (n10) | 170.2 (n10) | 177.9 (n10) | 1 (n10) | 127.7 (n10) | 4220 (n10) | 129.6 (n10) | 1 (n10) | 1 | -58% |

_Comparability: Claude Code=qualified, Codex CLI=qualified, Pi Mono=qualified, Prime Agent Rust=qualified, Prime Agent TS=qualified_

**Mixed identity — never aggregate across these rows**: runs ['camp-claude-20260926-021152', 'camp-codex-20260926-021152', 'camp-pi-20260926-021152', 'camp-rust-20260926-021151', 'camp-ts-20260926-021152'], harness ['unknown']

_Disclosures: Codex CLI: probe_quantized=10; Pi Mono: probe_quantized=10; Prime Agent TS: probe_quantized=10_

## daemon.boot

| product | trials | create_ok | hello_ok | spawn_to_accept_ms | spawn_to_first_create_ms | spawn_to_hello_ms | rank | Δ vs TS |
|---|---|---|---|---|---|---|---|---|
| Prime Agent Rust | w1=10 | 1 (n10) | 1 (n10) | 30.8 (n10) | 132.2 (n10) | 31.0 (n10) | 1 | -73% |
| Prime Agent TS | w1=10 | 1 (n10) | 1 (n10) | 112.9 (n10) | 860.0 (n10) | 115.0 (n10) | 2 | +0% |

Status (no trials ran):

- Claude Code: not_applicable — benchmark applies to ['rust', 'ts'] only
- Codex CLI: not_applicable — benchmark applies to ['rust', 'ts'] only
- Pi Mono: not_applicable — benchmark applies to ['rust', 'ts'] only

_Comparability: Prime Agent Rust=qualified, Prime Agent TS=qualified_

**Mixed identity — never aggregate across these rows**: runs ['camp-rust-20260926-033219', 'camp-ts-20260926-021152'], harness ['unknown']

## session.agent_view_roundtrip

| product | trials | agents_chrome_ms | agents_to_tail_ms | chat_ready_after_ms | chat_to_agents_ms | launch_to_ready_ms | nproc_10mib | pss_10mib_mb | pty_bytes | roundtrip_ok | rss_10mib_mb | rank | Δ vs TS |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Prime Agent Rust | w1=10 | 117.9 (n10) | 21457.4 (n10) | 21460.3 (n10) | 118.7 (n10) | 23064.1 (n10) | 4 (n10) | 640.8 (n10) | 46350 (n10) | 1 (n10) | 679.8 (n10) | 2 | +72% |
| Prime Agent TS | w1=7 | 68.4 (n7) | 1817.9 (n7) | 1827.1 (n7) | 69.2 (n7) | 690.3 (n7) | 5 (n7) | 1041.3 (n7) | 80607 (n7) | 1 (n7) | 1368.9 (n7) | 1 | +0% |

Status (no trials ran):

- Claude Code: not_applicable — session.* benchmarks resume the Prime session fixture; BENCHMARK_SUITE_SPEC section A scopes them to Prime Agent Rust/TS
- Codex CLI: not_applicable — session.* benchmarks resume the Prime session fixture; BENCHMARK_SUITE_SPEC section A scopes them to Prime Agent Rust/TS
- Pi Mono: not_applicable — session.* benchmarks resume the Prime session fixture; BENCHMARK_SUITE_SPEC section A scopes them to Prime Agent Rust/TS

_Comparability: Prime Agent Rust=equivalent, Prime Agent TS=equivalent_

**Mixed identity — never aggregate across these rows**: runs ['camp-rust-20260926-033219', 'camp-ts-20260926-021152'], harness ['unknown']

Excluded from rankings (validity gate):

| product | excluded | reasons |
|---|---|---|
| Prime Agent TS | 3 | fixture_not_confirmed=3 |

## session.cold_open_10mib

| product | trials | frame_bursts | input_ready_gap_ms | launch_to_first_paint_ms | launch_to_ready_ms | launch_to_sentinel_ms | nproc_10mib | pss_10mib_mb | pty_bytes | rss_10mib_mb | rank | Δ vs TS |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Prime Agent Rust | w1=10 | 376 (n10) | 22441.4 (n10) | 36.4 (n10) | 22504.3 (n10) | 22506.8 (n10) | 4 (n10) | 525.8 (n10) | 70767 (n10) | 564.3 (n10) | 2 | +3019% |
| Prime Agent TS | w1=7 | 10 (n7) | 13.6 (n7) | 708.3 (n7) | 721.5 (n7) | 2471.6 (n7) | 4 (n7) | 894.6 (n7) | 111423 (n7) | 1115.0 (n7) | 1 | +0% |

Status (no trials ran):

- Claude Code: not_applicable — session.* benchmarks resume the Prime session fixture; BENCHMARK_SUITE_SPEC §A scopes them to Prime Agent Rust/TS
- Codex CLI: not_applicable — session.* benchmarks resume the Prime session fixture; BENCHMARK_SUITE_SPEC §A scopes them to Prime Agent Rust/TS
- Pi Mono: not_applicable — session.* benchmarks resume the Prime session fixture; BENCHMARK_SUITE_SPEC §A scopes them to Prime Agent Rust/TS

_Comparability: Prime Agent Rust=equivalent, Prime Agent TS=equivalent_

**Mixed identity — never aggregate across these rows**: runs ['camp-rust-20260926-021151', 'camp-rust-20260926-032300', 'camp-rust-20260926-034840', 'camp-ts-20260926-021152'], harness ['unknown']

_Disclosures: Prime Agent TS: probe_quantized=7_

Excluded from rankings (validity gate):

| product | excluded | reasons |
|---|---|---|
| Prime Agent TS | 3 | fixture_not_confirmed=3 |

## A/A calibration

| pair | p50 a | p50 b | spread | valid |
|---|---|---|---|---|
| compare.cold_start/claude | 331.6 | 316.2 | 4.9% | YES |
| compare.cold_start/codex | 296.6 | 295.4 | 0.4% | YES |
| compare.cold_start/pi | 238.1 | 243.9 | 2.4% | YES |
| compare.cold_start/rust | 292.5 | 294.7 | 0.8% | YES |
| compare.cold_start/ts | 589.3 | 592.0 | 0.5% | YES |

_A/A coverage: 1/9 benchmarks calibrated; none for compare.install_disk, compare.memory_idle_load, compare.msg_send, compare.scroll_typing, compare.warm_start, daemon.boot, session.agent_view_roundtrip, session.cold_open_10mib — an A/A table entry is the only noise evidence, its absence is never an OK._
