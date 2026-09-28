# cmp5-20260928-163659 — Five-Product Comparative Benchmark Campaign (RESULTS)

**Campaign**: cmp5-20260928-163659 — Prime Agent Rust vs Prime Agent TS vs Claude Code vs Codex CLI vs Pi Mono.
**Regime**: strictly **mock-routed** for every product and every benchmark (including compare.msg_send — every reply is the offline mock provider's scripted answer; zero network inference in the ranked rows; see the incident note for the qualification-era exception, kept out of this run).
**Layout**: one fresh Prime VM sandbox (ubuntu:22.04, 4c/8GB/60GB, one per benchmark type) with ALL FIVE products installed and run sequentially on the same VM (cross-product fairness on identical hardware); 9 sandboxes provisioned in parallel. 10 measured trials per benchmark per applicable product, plus a 10-trial A/A calibration pass per product per sandbox (halves interleaved in time).
**Driver**: raw-PTY (pyte screen emulation, monotonic controller-side clocks, per-trial isolated homes, per-trial process sweep, load gates); scrubbed env; reference CPU-loop calibration per sandbox (fixed-loop ms, recorded per wave).
**Pins (frozen, no drift across all 9 waves — per-wave versions.json rechecked)**:

| product | version | revision / source |
|---|---|---|
| Prime Agent Rust | 0.1.0-continuous.b5bf28f1d | origin/rust frozen at campaign start; built on a 16c/32GB Ubuntu 22.04 Prime VM replicating the pinned commit's continuous.yml recipe (rustc 1.98.1, --release --locked, split_debug shipped binary 57,108,704 B sha256 5b1042ec..., GLIBC gate 2.34<=2.35) |
| Prime Agent TS | 0.9.6 | official stable (GitHub release v0.9.6, latest non-prerelease) |
| Claude Code | 2.1.283 | npm @anthropic-ai/claude-code@latest |
| Codex CLI | 0.158.0 | npm @openai/codex@latest (updated from 0.157.0 at campaign start) |
| Pi Mono | 0.87.1 | origin/master HEAD 11894012dd rebuilt from source (bundle tree sha256 96cf0668...) |

## Headline table — p50 / p75, 10 trials per cell, fastest bolded

| benchmark (metric) | Prime Agent Rust | Prime Agent TS | Claude Code | Codex CLI | Pi Mono |
|---|---|---|---|---|---|
| compare.cold_start (launch→ready ms) | 270.8 / 271.1 | 542.0 / 556.0 | 308.9 / 314.9 | 299.3 / 303.9 | **246.9** / 248.2 |
| compare.warm_start (launch→ready ms) | 265.3 / 267.5 | 497.1 / 530.7 | 328.3 / 353.1 | 302.7 / 306.0 | **178.3** / 181.8 |
| compare.msg_send (Enter→ack ms) | **0.2** / 0.4 | 2.0 / 2.2 | 42.5 / 44.0 | withheld | 0.8 / 0.8 |
| compare.msg_send (Enter→reply-rendered ms) | 702.5 / 734.8 | **679.8** / 680.4 | 755.1 / 758.3 | withheld | 688.4 / 689.2 |
| compare.scroll_typing (typing ms p50) | **1.0** / 1.0 | withheld | — | — | — |
| compare.memory_idle_load (RSS MB, 10MiB session) | **231.7** / 234.8 | 946.2 / 1128.2 | — | — | — |
| compare.install_disk (installed bytes) | **57,883,163** | 172,192,855 | 483,322,595 | 444,219,856 | 462,745,683 |
| session.cold_open_10mib (launch→ready ms) | **703.3** / 753.4 | 776.1 / 798.4 | — | — | — |
| session.agent_view_roundtrip (chat→agents view ms) | **13.7** / 14.2 | 66.8 / 68.0 | — | — | — |
| daemon.boot (spawn→accept ms) | **53.6** / 70.0 | 112.8 / 116.1 | — | — | — |
| daemon.boot (spawn→first-create ms) | **141.2** / 208.8 | 589.3 / 609.4 | — | — | — |

(rows show p50 / p75 over semantically-validated rows; `—` = the harness §F comparability rule — the product has no native 10MiB Prime-session fixture or no resident daemon — status row, never measured. Valid denominators: every cell n=10 except ts memory n=6, ts cold_open n=6, ts agent_view n=5 — withheld rows listed below.)

**Rust vs TS (the port's deltas, this campaign):** cold start 271 vs 542ms (rust **2.00x faster**), warm start 265 vs 497ms (rust **1.87x faster**), daemon boot 53.6 vs 112.8ms accept / 141 vs 589ms first-create (rust **2.1-4.2x faster**), memory with the 10MiB session 232 vs 946MB (rust **4.1x less**), on-disk 57.9MB vs 172.2MB (rust **3.0x smaller**), 10MiB cold open 703 vs 776ms (rust **1.10x faster**), agents-view round trip 13.7 vs 66.8ms (rust **4.9x faster**). All five products ranked: pi fastest at raw launch (247ms cold), rust fastest at daemon/resume/memory/disk paths, ts slowest at launch paths among the measured set.

## msg_send routing (STRICTLY MOCK)

Every ranked msg_send row carries `msg_routing: mock` and settled on the mock provider's scripted reply (rendered + 600ms stability). Claude's ack (42.5ms) is its render path; the reply-rendered metric is dominated by the common 600ms stability window plus the mock round-trip. **Codex msg_send: 10/10 rows withheld** — codex 0.158.0 does not complete the offline mock route (ack renders, the mock reply never does: 4 rows settle-false; 6 rows lost the typed prompt to its per-launch migration NUX racing the editor). Per campaign rules its rows stay withheld-with-reason; no real-API fallback was improvised.

## A/A calibration (10 trials per product per sandbox, halves interleaved; spread >5% annotated)

| sandbox | product | half-A p50 | half-B p50 | spread | note |
|---|---|---|---|---|---|
| compare.cold_start | rust | 301.4 | 276.9 | **8.8%** | noise-annotated |
| compare.cold_start | ts | 551.4 | 548.4 | 0.5% | |
| compare.cold_start | claude | 302.0 | 331.1 | **9.6%** | noise-annotated |
| compare.cold_start | codex | 304.1 | 299.3 | 1.6% | |
| compare.cold_start | pi | 236.5 | 240.2 | 1.6% | |
| compare.warm_start | rust | 269.7 | 271.1 | 0.5% | |
| compare.warm_start | ts | 521.6 | 550.6 | **5.6%** | noise-annotated |
| compare.warm_start | claude | 384.7 | 381.0 | 1.0% | |
| compare.warm_start | codex | 302.1 | 302.9 | 0.2% | |
| compare.warm_start | pi | 195.1 | 176.3 | **10.7%** | noise-annotated |
| compare.msg_send (ack) | rust | 0.4 | 0.2 | 100%* | *sub-millisecond metric — relative spread is meaningless at this scale; absolute delta 0.2ms |
| compare.msg_send (ack) | ts | 2.0 | 2.1 | **5.0%** | borderline |
| compare.msg_send (ack) | claude | 43.5 | 44.2 | 1.6% | |
| compare.msg_send (ack) | pi | 0.8 | 0.8 | 0.0% | |
| compare.msg_send (settle) | rust | 736.5 | 669.7 | **10.0%** | noise-annotated |
| compare.msg_send (settle) | ts | 726.8 | 705.4 | 3.0% | |
| compare.msg_send (settle) | claude | 756.6 | 755.7 | 0.1% | |
| compare.msg_send (settle) | pi | 687.6 | 688.6 | 0.1% | |
| compare.scroll_typing | rust | 1.0 | 1.0 | **6.3%** | sub-ms metric; absolute delta ~0.06ms |
| compare.memory_idle_load | rust | 233.7 | 238.0 | 1.8% | |
| compare.memory_idle_load | ts | 965.7 | 1141.2 | **18.2%** | bimodal RSS (see withheld note) |
| compare.install_disk | rust/ts | identical | identical | 0.0% | byte-exact footprint |
| session.cold_open_10mib | rust | 718.7 | 737.3 | 2.6% | |
| session.cold_open_10mib | ts | 809.5 | 765.3 | **5.8%** | noise-annotated |
| session.agent_view_roundtrip | rust | 13.4 | 13.6 | 1.5% | |
| session.agent_view_roundtrip | ts | 67.7 | 66.8 | 1.3% | |
| daemon.boot (accept) | rust | 40.9 | 40.9 | 0.0% | |
| daemon.boot (accept) | ts | 108.3 | 112.4 | 3.8% | |
| daemon.boot (first-create) | rust | 160.7 | 141.8 | **13.3%** | noise-annotated — create-latency is scheduler-sensitive on the shared VM |
| daemon.boot (first-create) | ts | 563.4 | 599.6 | **6.4%** | noise-annotated | |

## Withheld rows (33 — nothing silently dropped; each carries per-row reason in the raw JSONL)

| benchmark | product | rows | reason |
|---|---|---|---|
| compare.msg_send | codex | 10 | mock route never settles (4x settle=false — the scripted reply never rendered; 6x prompt typing dropped at key 2/11 — the per-launch migration NUX raced the editor). Per campaign rule: withheld, no real-API fallback |
| compare.scroll_typing | ts | 10 | `typing_ok=false` on all 10 — the TS TUI drops keys under the raw-PTY driver while typing into the 10MiB session (the known 2026-09-24 limitation; still reproduces on 0.9.6) |
| compare.memory_idle_load | ts | 4 | `fixture_not_confirmed` — the resumed-fixture sentinel evidence missing (6 valid rows remain; ts RSS is bimodal 751-1138MB, also visible in the A/A) |
| session.cold_open_10mib | ts | 4 | `fixture_not_confirmed` (6 valid rows remain) |
| session.agent_view_roundtrip | ts | 5 | roundtrip validation failures (`agents_chrome`/`roster_row`/`tail_after` false; 5 valid rows remain) |

Status rows (15, never measured, never numeric): claude/codex/pi on compare.scroll_typing + compare.memory_idle_load + session.cold_open_10mib + session.agent_view_roundtrip (no native 10MiB Prime-session fixture) and on daemon.boot (no resident daemon) — the harness §F comparability rule.

## Follow-up measurements (post-campaign, 2026-09-28 evening — same frozen pins, strictly-mock)

Three post-campaign follow-ups, each on a fresh campaign-spec sandbox (ubuntu:22.04, 4c/8GB/60GB) with ALL FIVE products installed and run sequentially on the same VM, mock-routed end to end, 10 measured trials per product plus the standard 10-trial A/A calibration pass (aa→w1 interleaved halves), per-run versions.json rechecked against the frozen campaign pins (sha256 identical). Raw JSONL + analysis + versions live in `followup/`; the two new adapters (`bench/adapters/benchmarks/memory_idle.py`, `bench/adapters/benchmarks/cpu_idle.py`) are committed alongside (registry 20; full suite 132/132 green). Nothing else in the harness changed.

| follow-up (metric) | Prime Agent Rust | Prime Agent TS | Claude Code | Codex CLI | Pi Mono |
|---|---|---|---|---|---|
| compare.memory_idle (settled idle RSS MB p50 / p75) | **110.9** / 111.2 | 643.8 / 645.6 | 237.4 / 237.7 | 161.1 / 161.2 | 145.7 / 145.9 |
| compare.memory_idle (settled idle PSS MB p50 / p75) | **73.7** / 74.2 | 423.6 / 425.3 | 235.8 / 236.1 | 159.5 / 159.7 | 143.8 / 144.0 |
| compare.cpu_idle (idle CPU % p50 / p75, 10s window) | 0.300 / 0.400 | 5.394 / 5.399 | 1.000 / 1.100 | **0.000** / 0.000 (n9) | 0.800 / 0.899 |
| compare.cpu_idle (wakes/s p50 / p75) | 36.06 / 42.35 | 98.58 / 119.47 | 17.18 / 19.19 | **0.00** / 0.00 (n9) | 3.99 / 4.70 |

- **compare.memory_idle** (`followup/memory_idle/`) — plain idle process-tree RSS at a ready interactive session, no fixture: the all-five complement to `compare.memory_idle_load`, which needed the 10MiB resume fixture and so only measured rust+ts. Whole-process-tree settled sample with the same /proc smaps_rollup sampler; tree coverage rust/ts 4 procs, codex 2, claude/pi 1. Rust's plain-idle floor is 110.9MB vs 231.7MB with the 10MiB session loaded (headline table above). A/A drift ≤0.5% on RSS p50 for every product; noop-control harness floor p50 0.052ms; every product's erase_ok 10/10. The rust erase_ms ~9.2s (probe-token backspace erase) runs before the settle+sample window and does not touch the sampled idle state.
- **compare.cpu_idle** (`followup/cpu_idle/`) — idle CPU% and wake rate of the whole process tree at a plain ready session, no fixture: /proc/<pid>/stat utime+stime tick deltas and /proc/<pid>/status context-switch (nvcsw+nivcsw) deltas over a fixed 10.0s window after a 3s settle, summed across the tree (CPU% is percent of one core; each blocking wait that returns is a voluntary switch, so the total switch rate is the wake proxy). At idle TS burns 5.39% of a core at 98.6 wakes/s; rust 0.30% at 36.1 wakes/s (involuntary 16.0/s); claude 1.00% at 17.2/s; pi 0.80% at 4.0/s; codex is fully quiescent at 0.000% and 0.00 wakes/s. Codex carries 3 withheld rows (2 aa + 1 w1, `tree_stable=false` — the tree changed shape inside the window, making tick deltas meaningless, negative-delta artifacts −2.4 to −6.7% CPU; reason per row in the raw JSONL); its ranked cells keep the 9 valid rows. A/A drift on idle-CPU% p50: rust 0.0%, claude +0.1%, ts +5.9% (noise-annotated), pi +14.4% relative but 0.10pp absolute (sub-1% metric — relative spread noisy), codex 0.0%. noop-control harness floor p50 0.057ms. erase_ok 10/10 per product. **Codex 0.00 spot-check (independent instruments, 2026-09-28, `followup/cpu_idle/codex-idle-spotcheck/`)**: verified on a fresh codex-only sandbox (same pin sha 61b0194f, exact harness launch path, no harness sampler) — 15 direct /proc reads @2s over 28s: utime +0, stime +1 tick, nvcsw/nivcsw +0/+0, both procs parked the whole window (node wrapper in `ep_poll`, codex core in `__futex_wait`); pidstat 10s×3 reads 0.00% usr/sys/CPU on both procs in every window; a 10s `strace -c -f` attach shows only ptrace attach/detach mechanics (0.0101s total syscall time, zero network syscalls), with counters frozen between the attach and detach boundaries. The 3 withheld rows are launch-transient helpers exiting inside the window (nproc 6→2 / 3→2 / 3→2 — negative deltas from their accumulated counters), not a recurring churn (0 shape changes in 60s of per-second direct watching across two fresh launches). The 0.000% / 0.0 wakes/s stands as published.
- **kitty env-detect cold-start arms, rust only** (`followup/kitty-cold-start/`) — same-VM two-arm, 5 trials each, campaign plain-PTY driver, interleaved: **plain PTY p50 301.35ms vs TERM_PROGRAM=ghostty p50 228.66ms** (−72.69ms, 24% faster launch→ready). Root cause: the pinned binary's vendored terminal env-detect queries enhanced-keyboard support (kitty protocol escape probe) when the spawn env carries no known-terminal marker; `TERM_PROGRAM=ghostty` (equally `KITTY_WINDOW_ID` / `GHOSTTY_RESOURCES_DIR` / `WEZTERM_PANE`) short-circuits the detect to Supported in the pinned source (enhanced_keys.rs) and skips the probe round-trips — dropped_probes 4→3, pty bytes 6130→5143, frame bursts 28→22, input-ready gap 258.43→188.20ms. Arm (a)'s absolute p50 (301.35ms) sits ~11% above the campaign cold_start headline (270.8ms) — a different VM instance; the campaign's own A/A table records 8.8% cold-start VM-to-VM noise, so only the same-VM interleaved delta is the valid env-detect cost. Real terminals set the marker and skip the probe; the benchmark's plain PTY (no TERM_PROGRAM) pays it on every launch.

## Measurement appendix

- **Reference calibration per sandbox (fixed CPU loop)**: cold_start 1327.7ms, warm_start 1295.7ms (VM REPLACED — first VM measured -5.4% outlier), msg_send 1399.1ms (VM REPLACED — same), scroll_typing 1272.6ms, memory_idle_load 1271.3ms, install_disk 1202.6ms (normalize factor 0.946 recorded), cold_open_10mib 1290.1ms, agent_view_roundtrip 1230.4ms, daemon_boot 1379.5ms (normalize factor 1.0851 recorded). Post-replacement comparison still flags msg_send +8.4% / install_disk -6.8% / daemon_boot +6.9% vs the 1271-1290ms median: the msg_send, install_disk and daemon_boot columns carry a residual ±7-8% VM-speed caveat (raw values published; factors recorded here and in the manifest — nothing normalized in the headline table).
- **noop-control harness floor** (30 rounds per sandbox): p50 0.043-0.061ms, p95 <=0.091ms — three-plus orders below every measured latency; no measurement contamination.
- **Binary-size / footprint note**: this campaign's rust payload is the pinned commit's CI-recipe **split** binary — 57,108,704B shipped (57,883,163B installed incl. runtime sidecar + skills), vs the previous campaign (cmp5-20260926) whose rust payload was the **unstripped** continuous artifact (204,860,672B; 206,668,003B installed). Install-disk and RSS comparisons vs that campaign mix (a) the payload change and (b) twelve days of perf work between 59a9c658 and b5bf28f1 (the hillclimb's memory/render lanes). This campaign's own rust-vs-ts deltas are measured on identical VMs with identical fixtures.
- **Pin freeze footnote (per parent decision)**: origin/rust advanced past the frozen pin by exactly one commit (`b89b8ffdd`, "pa-cli: print_boundary.rs split - the 4 stages", 2026-09-28T16:49:02Z — 12 minutes AFTER the campaign-start pin freeze 16:36:59Z). The pin `b5bf28f1d` was the latest merged commit at campaign start; the freeze stands; the delta is a module split with no user-visible surface.
- **Incident — orchestrator cfg drop (qualification era, excluded from this run)**: the orchestrator's materialize path dropped the controller campaign cfg, so the first qualification wave's sandbox config lacked the `msg_routing: mock` override and codex's product-level `real-api` declaration won — 5 real inference calls (sentinel-certified) occurred before the gap was caught. Fixed (cfg now flows through every provision path; regression test `test_run_parallel_deploys_controller_benchmark_overrides`); the full campaign above ran the fixed orchestrator: every msg_send row in THIS run is mock-routed, `real_api_certified` absent on all ranked rows. Raw evidence preserved in `incident-orchestrator-cfg-drop/`.
- **Harness identity**: bench harness campaign-cmp5 worktree, git b464f81 (dirty: campaign pin/config edits), deploy bundle sha256 f6e49ba40bb9139eb309501ff9570649c38d07538343d7c54d23b3062d69ed82; full pytest 129/129 green post-fix.
- **Provenance**: every trial row carries run label 20260928-185903, sandbox identity, per-wave versions.json, fixture sha256 (10MiB fixture dadaecfc..., sentinel CORPUS-TAIL-9f3a1c70), and A/A position. Raw JSONL per benchmark (trials-w1 + trials-aa) + settle + noop-control + versions + the orchestrator manifest are in `results/` here; the controller-side run tree is `~/bench-cmp5/results-cmp5-20260928/parallel/20260928-185903/`.
- **Bench box**: disk 302G free before / 298G free after; all campaign VMs (build, preflight, 2x qual, 9x full) destroyed after use.
