# Codex idle spot-check — independent instruments (2026-09-28)

Kevin questioned the codex cpu_idle result (0.000% CPU / 0.00 wakes/s). This is
the independent verification, run on a fresh codex-only Prime sandbox
(`codexcheck`, trhug16c54g8z9sr6a0eym7b, campaign-spec 4c/8GB/60GB ubuntu:22.04,
codex-cli 0.158.0, binary sha256 61b0194f3bb6 — identical to the frozen campaign pin).

Method: the harness launch path was reused EXACTLY (registry, PTY driver, per-trial
isolated home, readiness probe, erase; cpu_idle never sends a message, so the routing
regime is inert — no inference in any trial or spot-check launch), but the SAMPLING
was independent: pure-/proc reads, pidstat (sysstat), and strace — never the harness
sampler. Note: `compare.cpu_idle` has no `msg_routing` config and stamps no routing
field on any row (message routing is a msg_send concern); the codex cmdline shows its
configured model string but zero network syscalls occur at idle (strace evidence).

## Results

1. **watchA** (launch → ready → erase → 3s settle → 15 direct /proc reads @2s = 28s,
   no instruments attached): tree deltas over the window — utime +0, stime +1 tick
   (0.0036% of one core), nvcsw +0, nivcsw +0. Tree shape 2 procs stable at every
   read. Both procs state S throughout: the node wrapper (pid 6152,
   `node /usr/bin/codex --no-daemon -m gpt-5.6-sol`) parked in `ep_poll`; the codex
   core (pid 6160, `@openai/codex-linux-x64/.../bin/codex --no-daemon`) parked in
   `__futex_wait`. Neither has an idle timer/wakeup source.
2. **pidstat** (independent instrument, 10s interval × 3, both pids): 0.00 %usr /
   0.00 %system / 0.00 %CPU on both processes in every window (average 0.00).
3. **strace -c -f** (10s attach on both pids, then SIGTERM detach): 223 syscalls,
   0.0101s total syscall time — all of it ptrace attach/detach mechanics
   (restart_syscall×14, futex×54, epoll_pwait×10 re-entries, mmap/munmap noise).
   Zero network syscalls (no connect/sendto/recvfrom). Concurrent direct /proc
   reads during the strace window: counters frozen between the attach (t≈0-2s,
   +3 nvcsw per proc) and detach (t≈10s, +2 per proc) boundaries; utime/stime
   never moved. ~8 tids total (2 processes + node worker threads); /proc/<pid>/stat
   aggregates the thread group, so the harness sampler's coverage matches.
4. **watchB churn watch** (second fresh launch, per-second reads ×30 from ready):
   tree shape 2 procs at every read — 0 churn events in 60s of direct watching
   across both launches.

## The 3 withheld `tree_stable=false` rows re-examined

All three are launch-transient helpers EXITING inside the 10s window:
start nproc 6 → end 2 (aa trial 2), 3 → 2 (aa trial 3), 3 → 2 (w1 trial 2); the
start sums carry the helpers' accumulated ticks/switches, hence the negative
deltas (−2.4 to −6.7% CPU). The helpers only exited (nproc shrank; nothing
respawned), all three failures cluster in the wave chain's early rounds
(launch teardown latency on a loaded 5-product VM — consistent with codex's
known per-launch migration/NUX subprocess chain), and no recurring churn was
observed in the spot-check's 60s of per-second watching. The 9 valid windows
are not lucky slices of a churning tree.

## Verdict

(a) — the counters are genuinely frozen while blocked. The published
0.000% idle CPU / 0.00 wakes/s (n9, 3 rows withheld-with-reason) stands.

Files: codexwatch.py / codexwatch2.py (the instruments, self-contained),
codexwatch-results.json (watchA + watchB raw counter reads), codexwatch2-results.json
(pidstat + strace + concurrent /proc reads).
