#!/usr/bin/env python3
"""Emit the final concurrent-io lane record (measurements + narrative)."""

import json
import subprocess
import sys
from pathlib import Path

BASE = json.loads(subprocess.run(
    [sys.executable, "/home/ubuntu/prime-agent-bench/scripts/build_concurrent_io_record.py"],
    capture_output=True, text=True).stdout)

BASE_SHA = "392efffae0c08cfba85911565adc8171a31002d17850daf20306d89fd7716402"

record = {
 "id": "20260926-210500-io-concurrent-event-fanout-arc",
 "axis": "io",
 "lane": "concurrent-io (perf-concurrent-io-fast)",
 "hypothesis": (
   "Per-request supervisor cost for concurrent session I/O is superlinear in resident "
   "sessions N: every session event (2 per append_custom_message: message_start + "
   "message_end, each carrying the full message payload) is published on the one "
   "daemon-wide tokio broadcast channel (supervisor.events), and every connected "
   "client's event arm wakes, DEEP-CLONES the (ClientRouting, Value) frame, locks its "
   "attached-list mutex, checks, and discards: Theta(N) per request, Theta(N^2) "
   "aggregate for equal per-session traffic. Sharing the payload (Arc<Value>) removes "
   "the per-receiver deep clone while keeping the same channel, ring capacity, routing "
   "decisions in the same recv order, and byte-identical wire frames (the worker-side "
   "EventPump already shares its frames this way via Arc<OutboundFrame>)."),
 "approach": (
   "External real-daemon benchmark (scripts/concurrent_io_curve.py, no product "
   "imports): ONE supervisor hosts N live sessions; a P-process driver fan-out (one "
   "thread per owned session, wall-clock deadline lock-step per phase) drives create+"
   "attach, seed appends, idle window, 2x measured append phases (200 appends per "
   "session per phase), kill+resume (create with sessionPath) storm, census. Metrics: "
   "per-request client latency arrays, supervisor+worker CFS schedstat (summed over "
   "all threads) per phase boundary, /proc/<pid>/io per boundary, fd census, "
   "RSS/PSS census, meminfo, fixed-work calibration between phases. Byte-parity "
   "oracles per session: JSONL structure, custom-row semantics, resume prefix "
   "preservation; session_semantics_digest must match across roles (base vs "
   "candidate) and trials. Baseline curve N in {1,10,50,100} x 2 trials at tip "
   "7064d039, then same-vm sequential ABBA (B C C B per N) at N in {1,100} twice: "
   "once at the iteration commit, once head-exact."),
 "base": {"revision": "7064d039ac3437596f75b44423d76a8f4bf4856a (baseline + 2 clean pairs)",
          "settled_head_base": "1507d399b54f2ffe65cda22ed7a9c86fee6a1480 (final gated pair; tip after #2844/#2866/#2877/#2878/#2887/#2879/#2884/#2880)",
          "folds": "two batched folds at clean boundaries per standing policy: a40b33ea0 (fold_1790456504) then 1507d399b (fold_1790457270); post-fold re-diff vs each merge-base = exactly the lane change (6 files, +40/-25)"},
 "branch": "lane/hillclimb-concurrent-io (settled head 4becda49a54abfbcc33413a6566947064760b378)",
 "commits": ["b56a2b332 (Arc<Value> event payloads)", "b4c89869b (2 missed send sites + test compile)",
             "d3ac85973 (rustfmt/test helpers)", "ac83e5baf (style)",
             "4d8d0e2f3 (fold a40b33ea0)", "4becda49a (fold 1507d399b; final head)"],
 "build": {"sandbox_id": "l0j1fuwrk79pvehuoevwn60f",
           "base_binary_sha256": BASE_SHA,
           "iteration_candidate_binary_sha256": "af49e01c2d1c7ac2fc35a0031f4993962713a9b4c162f977304d65d09f296ac4",
           "head_exact_candidate_binary_sha256": "0967047cced911d33a49f746d6e1c550d3d527b62457bfba4edcc04fc49b1fa7 (ac83e5baf @ 7064d039 lineage)",
           "settled_head_base_binary_sha256": "88a5f37edf3f125173f82c4ca9b1505fe3d18e61ea9966140a0f9775f82808a0 (1507d399b)",
           "settled_head_candidate_binary_sha256": "ab86a7935a446d646ba485781277389a11a1ab61590ab57035842a187c37ab8d (4becda49a)",
           "toolchain": "rustup 1.98.1 on ubuntu:22.04 (glibc 2.35); rustfmt+clippy components installed and exercised (real diffs/lints observed before green)"},
 "gates": {
   "measurement_vm_pa_daemon_scope_ac83e5baf": "fmt pass; clippy --workspace --all-targets -D warnings "
       "pass; cargo test --release -p pa-daemon --lib: 747 passed / 2 failed, 6 ignored "
       "(FAILED-1 acp::compaction_arms threshold meta test: PRE-EXISTING AT TIP - reproduced on base "
       "7064d039 exact; it PASSED on the gate VM's kernel env - environment-sensitive; FAILED-2 "
       "worker::tests::goal_turn_end_loop_runs_to_completion: ENVIRONMENT - needs packaged kernel "
       "runtime per docs/parity-battery.md).",
   "full_suite_vm_gate_4d8d0e2f3": "fleet_pipeline gate (rust:1-bookworm pooled VM, toolchain 1.98.1): "
       "fmt GREEN, clippy GREEN, cargo test --workspace --no-fail-fast RED only on "
       "mcp_login::tests::worker_begin_login_persists_creds_and_unlocks_gating - classified ACTIVE "
       "KNOWN-RED (rotating daemon-timing flake family, citations auto-attached, NOT a lane red); "
       "verdict RED_KNOWN_REDS = not merge evidence per the fleet rule.",
   "full_suite_vm_gate_4becda49a": "gate_1790458149: fmt/clippy GREEN, workspace test rc=101 with EXACTLY ONE "
       "failure = the registered rotating mcp_login known-red flake (auto-cited), zero unknown failures "
       "(RED_KNOWN_REDS = not merge evidence).",
   "full_suite_vm_gate_e61c5f2e3": "gate_1790464516: FULLY GREEN (fmt+clippy+workspace test, ZERO failures) on "
       "the folded combined tree at the 013e40a4a lineage.",
   "full_suite_vm_gate_828beb5e7_REBIND_HEAD": "gate_1790466471: FULLY GREEN (fmt+clippy+workspace test, ZERO "
       "failures) on the folded combined tree at the 4d57eb082 lineage - merge-grade evidence at the re-bind head.",
   "github_ci_at_4becda49a": "FULLY GREEN per both adversarial reviewers (fmt, check+clippy, shards 1-4/4, test "
       "summary, Bugbot, Macroscope; only red = the standing non-applicable TS benchmark, operator disposition)."},
 "measurements": BASE["measurements"],
 "decomposition": {
   "sup_cpu_per_append_fit": "base: a=515us + b=21.2us*N fits N=1/10/50/100 within 4% at both trials; candidate: b drops to ~5.9us*N (clone share ~15us of the 21us per session per append)",
   "append_latency_shape": "bimodal: fast cluster ~0.4-1ms (buffered appends), slow cluster 20-150ms (fdatasync barrier landing; VM storage dependent); at N>=10 ~98-99% of appends take the slow path",
   "fsync_behavior": "strace (N=1 full set + N=20 io-only): exactly ONE fdatasync per append_custom_message in the worker (20/20, 400/400), ~2.2KB written per append (row + sidecar share), zero supervisor fsync; resume/worker-boot path pays ~8 fsync + ~300 write calls per boot (cross-lane: concurrent-boot serialization ~0.42s per create, 100 concurrent creates take ~42s wall - serialized)",
   "socket_data_path": "daemon client socket I/O uses sendto/recvfrom (NOT counted in /proc/<pid>/io rchar/wchar/syscw/syscr - earlier sup_syscw numbers in the raw result.json are FILE-IO-ONLY and must not be read as request counts)",
   "fd_growth": "supervisor fds = 12 + 4 per session (client conn + worker conn, unix sockets counted per end): 16 @ N=1 -> 412 @ N=100; linear, no leak; worker fds flat 12",
   "memory": "worker RSS floor ~40MB/session at 20+220 rows (N=100 sum 4.11GB); supervisor RSS ~0.9MB/session (46MB -> 135MB); PSS follows; no superlinear growth to N=100",
   "idle_cpu": "supervisor idle ~0.06-0.13us/s per session at census; no per-session timer storm",
 },
 "claims": {
   "primary": "supervisor CPU per append_custom_message at N=100 live sessions "
              "(same-vm sequential ABBA, B C C B, sha-asserted binaries, all legs disclosed). "
              "CLEAN-WINDOW pairs: at 7064d039 lineage base 2670.6us (legs 2698/2641/2728/2615) "
              "-> candidate 995.9us (legs 977/1033/1060/915) = -62.5%, reproduced at ac83e5baf "
              "2643.8us (legs 2672/2664/2676/2563) -> 1011.0us (legs 1010/926/1061/1047) = -61.7%. "
              "AT THE SETTLED HEAD (base 1507d399b vs candidate 4becda49a), gated clean-window "
              "append1 pair (both probe classes healthy at leg start): base 3566.9us (legs "
              "3289.7/3844.2) -> candidate 1587.2us (legs 1524.7/1649.7) = -55.5%. The base's "
              "per-append CPU is higher at the newer tip for BOTH binaries (~+35%, consistent "
              "with larger upstream event payloads); the mechanism delta holds across all "
              "clean pairs. AT THE FINAL RE-BIND HEAD (fold of tip 4d57eb082 -> 828beb5e7): "
              "append1 base 2687.7us (legs 2664.3/2711.1) -> candidate 1081.1us (legs "
              "1075.7/1086.5) = -59.8%; append2 -60.0% (the tightest legs of the campaign; "
              "both binaries returned to the ~2690/~1080 band at this lineage, with the "
              "intermediate-tip +35% cost shift not present at 4d57eb082).",
   "secondary_none": "wall/latency: NO CLAIM - append wall and p50/p95 are dominated by "
                     "the fdatasync barrier + storage regime. N=1 CPU: NO CLAIM (B/C "
                     "ranges overlap at every lineage).",
   "stability_observation": "under fleet I/O turbulence (fresh+rename probe class at "
                            "~90ms p50 while the repeat class reads 0.19ms - the "
                            "time-varying regime class per the fleet correction), the "
                            "BASE binary's later-phase per-append CPU inflated 2-18x on "
                            "4 of 4 base N=100 legs across two runs (append2 legs "
                            "18298/7593/7994/3344us) while the CANDIDATE stayed within "
                            "985-1650us on all 8 legs ever measured at any lineage; the "
                            "clone-heavy fan-out is disproportionately fragile under "
                            "host pressure. Directionally favorable to the candidate but "
                            "magnitude is environment-dependent - NOT a numeric claim.",
   "projected_implication": "every session event pays the same per-connection cost class; "
                             "turn streaming emits many more events per request than "
                             "append_custom_message, so a daemon hosting many live "
                             "sessions (Kevin's 30-concurrent-subagent waves, multi-user "
                             "hosts) burns Theta(N) supervisor CPU per event; the change "
                             "cuts that ~62% at N=100 and ~11% of the fixed N=1 term is "
                             "untouched (routing/wakeup floor remains Theta(N) - see "
                             "follow-up)."},
 "follow_up": {
   "targeted_delivery": "the remaining ~5.9us/session/append is the wakeup+recv+match "
                        "floor of waking every connection per event; a per-session "
                        "subscriber registry (send-time attached-check) would make "
                        "delivery O(attached) instead of O(connections) - BUT it moves "
                        "the attached-check from recv time to send time, changing which "
                        "events a racing attach/detach observes (TS evaluates filters "
                        "at send time in its single-threaded loop; the Rust recv-time "
                        "check is already a divergence in the race window). Needs its "
                        "own parity case vs TS - not attempted here.",
   "boot_serialization": "concurrent create/resume serializes at ~0.42s per worker "
                         "(100 concurrent creates: 42s wall) with ~8 fsync + ~300 "
                         "writes per worker boot - belongs to the kernel/boot lanes "
                         "(daemon-boot discarded, kernel-boot PR #2857): cross-lane "
                         "note only.",
   "resume_budget_flake": "1 of 8 N=100 runs hit 'session worker did not come up in "
                           "time' (30s connect budget breached by the concurrent "
                           "respawn storm tail; product-side budget, not "
                           "candidate-specific; the run was rerun and disclosed)."},
 "regime": {
   "probe_correction": "per fleet correction, the 4KB repeat-fdatasync probe does not "
                       "sample the fresh-write+sync_all+rename class; both classes were "
                       "probed (scripts/dual_probe.py output in "
                       "re-pair-regime.jsonl / abba-regime-watch.jsonl)",
   "first_pair": "N=1 legs: repeat-class p50 0.19-0.21ms (healthy); N=100 legs: "
                 "repeat-class p50 13-52ms - partly self-induced (100 concurrent "
                 "fdatasync-per-append sessions saturate the shared storage: the "
                 "concurrent-append latency mechanism itself)",
   "re_pair": "repeat-class p50 0.17ms at probe time but product append p50 3x the "
              "first pair - the product's durability class (fdatasync on a growing "
              "file under 100-way concurrency) samples neither probe class cleanly; "
              "latency legs are DIAGNOSTIC-ONLY everywhere in this record",
   "calibration": "fixed 32MB sha256 work: min 0.017s across all runs; single-sample max "
                  "spikes to 0.021-0.036s in a few runs (I/O-window turbulence); CPU legs "
                  "unaffected (B legs stable 2658-2740us at the final lineage).",
   "advisory_v0_9_compliance": "perf-write-regime-fast advisory applied: (a) the confirm-series leg gates "
                  "used 20-op dual-class p50 probes - the advisory's underdetection limitation is disclosed; "
                  "(b) retroactive classification of the re-bind-head pair (confirm5): 3 of 4 legs HEALTHY "
                  "(both classes 0% stalls >15ms: repeat p50 0.14-0.24ms, fresh p50 0.22-0.35ms, max 0.56ms); "
                  "leg B-3's window had the fresh class degraded (p50 140.7ms, 100% stalls) while the repeat "
                  "class stayed clean (0.21ms, 5% stalls) - and B-3's CPU legs stayed in-band (2711/2740 vs "
                  "B-0's 2664/2658), mechanistically consistent with the advisory's flush-path-only picture "
                  "AND with the append path riding the repeat class; (c) post-pair preflight (>=40 isolated "
                  "fresh+sync_all+rename @0.5s spacing + 20 repeat): window DEGRADED (fresh stall-rate 100%, "
                  "p50 141.6ms = ~354x this host's known-good; repeat p50 0.23ms, 5% stalls, one 135.7ms) - "
                  "no further timing legs taken; (d) probe script left at /root/preflight.py on the VM; "
                  "thresholds applied host-relative (known-good fresh ~0.4ms, repeat ~0.2ms on this host).",
   "vm_coordination": "perf-subscriber-registry-fast (the follow-up lane this record names) sequenced its own "
                  "ABBA behind this lane's legs on the shared measurement VM (its driver stopped at 0 legs on "
                  "first contact; VM-FREE sent after the re-bind pair + the DEGRADED-window warning).",
 },
 "evidence": {
   "runner": "scripts/concurrent_io_curve.py + scripts/concurrent_io_analyze.py + "
             "scripts/build_concurrent_io_record.py (bench hillclimb)",
   "archive": "/home/ubuntu/hillclimb/archives/perf-concurrent-io/ (raw trial trees, "
              "strace parses, regime logs, VM logs)",
   "vm_record": "/home/ubuntu/hillclimb/vms/perf-concurrent-io.json",
 },
 "parity_notes": (
   "Frozen surfaces untouched: session JSONL bytes, durability (1 fdatasync/append "
   "unchanged), wire frames, routing decisions, ring capacity, recv order. The "
   "session_semantics_digest is identical between base and candidate at every N "
   "(4195cad0 @ N=1, 85607aee @ N=100) and all 24 runs validate every oracle "
   "(structure, custom-row semantics, resume prefix preservation, fixture semantics). "
   "Internal-only change: the broadcast carries (ClientRouting, Arc<Value>) and the "
   "per-connection event arm serializes from the shared Value. The change mirrors the "
   "worker-side EventPump's existing Arc<OutboundFrame> pattern. cfg(test) helpers "
   "deref back to owned Values so test assertions are unchanged in meaning."),
 "decision": "PAIRED WIN on the mechanism, evidenced at FOUR upstream lineages: -62% twice at "
             "7064d039; -55.5% at the 1507d399b settled head; -59.9%/-62.6% at the 013e40a4a fold; "
             "-59.8%/-60.0% at the 4d57eb082 re-bind fold (tightest legs). BOTH adversarial reviewers "
             "EXPLICITLY APPROVED at 4becda49a; per their binding stale-base conditions the lane folded "
             "twice more (e61c5f2e3, 828beb5e7) with byte-identical mechanism re-diffs and FULLY GREEN "
             "full-suite gates at both folded heads; re-bind requests at 828beb5e7 are out. The "
             "orchestrator's numeric review ACCEPTED. Merge is the parent's under the standing "
             "authorization (operator dispositions: benchmark non-applicability + flake registrations).",
}
print(json.dumps(record, indent=1, sort_keys=True))
