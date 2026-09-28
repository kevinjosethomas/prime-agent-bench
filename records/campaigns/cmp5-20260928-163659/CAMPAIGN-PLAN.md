# Five-product comparative benchmark campaign plan

Campaign: `cmp5-20260928-163659`. Pin frozen at 2026-09-28T16:36:59+00:00: Prime Agent Rust `origin/rust` = `b5bf28f1d752ca9bea0ab1d3d24b572e682d69e5` (fetched on bench box). Controller: `ssh bench`, `~/prime-agent-bench-cmp5`, branch `campaign-cmp5`; previous campaign: `records/campaigns/cmp5-20260926`. Results will be committed and pushed from this same worktree/branch. No `cargo` builds on controller or Mac.

## Frozen SHAs (recorded 2026-09-28, gate evidence in GATE-EVIDENCE.md)

- Rust binary tarball `prime-agent-0.1.0-linux-x64.tar.gz` (19,385,942 B): SHA-256 `a4b8bb115527318f4268c42fecf48e9f80724ac56752960f72fd1b8abeffdfaf`
- Rust shipped binary `prime-agent` (57,108,704 B): SHA-256 `5b1042ecfc495b8e51b3661c3b1c874c04834abcd6499b563fe6a512a430f40f` (`--version` = `0.1.0-continuous.b5bf28f1d752ca9bea0ab1d3d24b572e682d69e5`; built on Prime VM per the pinned commit CI recipe; GLIBC gate 2.34 <= 2.35)
- Debug decoder `prime-agent-0.1.0-linux-x64.debug.gz`: SHA-256 `904daf9fa59adc1cec5895440e6253bf07e05006b2cfed5925af23ca3746d094`
- origin/rust advanced past the pin by exactly one commit (`b89b8ffdd`, 2026-09-28T16:49:02Z — 12 minutes AFTER campaign start/pin freeze); the pin was the latest merged commit at campaign start, so the freeze stands.


## Gates before full suite

1. Find a successful org Rust CI Linux artifact built from exactly `b5bf28f1d752ca9bea0ab1d3d24b572e682d69e5`. Download to a campaign-private bounded location; verify commit, Linux x86_64, Ubuntu 22.04/glibc 2.35 compatibility, SHA-256 and `--version`. Only if unusable, build on a 16c/32GB Ubuntu 22.04 Prime Sandbox, never here.
2. On an Ubuntu 22.04 Prime Sandbox, run binary `--version` and a headless session boot; record outputs/exit codes. No full suite before both checks pass.
3. Update `bench/adapters/rust/product.yaml` binary/revision to this frozen commit and private binary installation; update vendor tarball. Check runtime payload dependencies and all five product versions/SHA-256 before launch. Pin latest stable Prime Agent TS, Claude Code, Codex CLI, Pi Mono at campaign start; prevent silent upgrades. Record exact artifacts and versions in campaign config/results. Do not disturb shared hillclimb paths or sessions.

## Experiment

Use the existing `bench orchestrator` on Prime Sandbox backend with one fresh Ubuntu 22.04 VM per benchmark type and all five products sequentially on **the same VM** for each type. Campaign suites: `compare.cold_start`, `compare.warm_start`, `compare.msg_send`, `compare.scroll_typing`, `compare.memory_idle_load`, `compare.install_disk`, `session.cold_open_10mib`, `session.agent_view_roundtrip`, `daemon.boot` (and compare previous campaign inventory before launching). Run a small qualification wave `--trials 5 --no-aa` before the full `--trials 10` wave with A/A calibration. Keep per-VM resource specifications and reference calibrations alongside the rows; benchmark-specific RAM increases where required by the harness. Default task concurrency to min(task count,120) where exposed; do not confuse provider rate limits with worker capacity.

Routing is strictly **mock-routed** for every product and every benchmark, including `compare.msg_send`: no real inference, paid provider calls, auth API routing, or real-API submission. Use a campaign-specific config instead of previous `configs/campaign.yaml`, which explicitly selected paid real API. Verify the effective routing and per-row provenance before accepting msg_send rows.

## Validity and publication

Gate each measurement semantically before scoring: settled app state, fixture sentinel present, successful typing and model-independent mock reply, no pop-up/auth/error/timeout, and exact frozen binary provenance. Unsupported product/benchmark pairs remain status rows. Missing or invalid evidence is withheld with reason, not assigned a latency. A/A >~5% gets an explicit noise annotation; failure under configured acceptance thresholds remains unranked. Benchmark failure yields a marker and the isolation chain continues. Recheck versions and SHA-256 against the frozen campaign config after each wave to catch auto-updaters.

Publish `CAMPAIGN-PLAN.md`, pinned config, raw per-trial JSONL, versions/provenance, A/A medians, and `RESULTS.md` (ranked table, withheld-with-reasons, measurement appendix) into `records/campaigns/cmp5-20260928-163659/`; commit and push `campaign-cmp5`. Record `df -h /` before/after; keep downloads and sandbox payloads bounded; never touch `~/.prime/agent/sessions`, `session-artifacts`, the hillclimb tmux/session, or the idle prior campaign tmux/session. If a gate cannot pass, stop and report evidence rather than run a partial full suite.
