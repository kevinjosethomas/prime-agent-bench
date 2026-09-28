# Whole-worker passivation pre-analysis (the deferred arm of the settled-child memory lane)

- Lane: wave-6 design pre-analysis (NO CODE CHANGES; the orchestrator's decision input)
- Date: 2026-09-28 | Author: wave-6 design lane (subagent), for the Hillclimb orchestrator
- Inputs: PR #2983 record `20260927-234500` (the settled-child kernel release, in review), the worker-rss baseline census `20260926-183300`, the spawn-admission decompose `20260926-204300`, the TS reference at `cd1f215` (main, in sync), the Rust checkout at `60e2e198c` (#2872; origin/rust read at `95f425a3d` on 2026-09-28 — the #2983 park-arm/stop_kernel seams are on its review branch, cited from the PR record)
- Question: should a lane implement the TS daemon-mode whole-worker passivation for RLM child workers in the Rust port (stop the child WORKER process at idle, not just its kernel)? Implement / defer / discard?

## 1. The TS daemon-mode passivation, in full

### 1.1 The two-tier residency policy (core/session-action-store.ts)

The TS daemon owns residency with TWO tiers (session-action-store.ts:377-437):

- **Tier 1, per-session passivation** (`canPassivateSession`, session-action-store.ts:411-419) applies ONLY to child sessions (`hasParent`: kind `subagent` + a `parentActiveSessionId`, daemon-mode.ts:3116). The comment states the split outright: "Pure per-node residency policy. Roots remain owned by whole-worker eviction." A child passes when: no non-passive descendants (`hasNonPassiveDescendants` false), not hydrating, and the idle threshold holds (`isIdleEvictionThresholdMet`, session-action-store.ts:393-405): `!isSessionActive && attachedClients === 0 && !hasRegisteredCronJob && lastActivityAt finite && now - lastActivityAt >= idleEvictionMinutes * 60_000`. `isSessionActive` is computed worker-side (daemon-mode.ts:3084-3120): the session summary's active flag, OR running RLM children, OR pending prompt admissions; attached clients counts pending attaches; cron counts only non-heartbeat jobs (session-action-store.ts:398-400).
- **Tier 2, whole-worker eviction** (`canEvictWorker`, session-action-store.ts:421-437) is the root-owned tier: lifecycle `ready`, connected, not stopping, no owner client, not preparing an update restart, **no wake-blind schedule**, at least one session, and EVERY hosted session idle-threshold-met. The wake-blind shield (daemon-supervisor.ts:1412 `hasWakeBlindSchedule: this.isWakeBlindScheduledWorker(worker)`) is what keeps a heartbeat-armed worker alive at the eviction tier.

Policy parameters: `DEFAULT_IDLE_EVICTION_MINUTES = 90` (settings-manager.ts:11; the global setting `idleEvictionMinutes`, settings-manager.ts:215, "global daemon policy; default: 90"; read at settings-manager.ts:928-931; `"off"` or <= 0 disables). The sweep cadence is `idleEvictionSweepIntervalMs` (daemon-supervisor.ts:700-706): `max(60s, min(5min, idle/3))` -> 5 min at the 90-min default (constants at daemon-supervisor.ts:250-253: MAX 5 min, MIN 60 s, mutation-drain timeout 5 s, per-worker child cap 2).

### 1.2 The sweep driver (daemon-supervisor.ts:1441-1515)

`runIdleEvictionSweep` runs on the cadence timer (daemon-supervisor.ts:1390): reload settings, refresh every worker's summaries, then:
1. Collect whole-tree eviction candidates (`canEvictWorker` over the refreshed snapshot, :1459). "Whole-tree candidates skip child work because stopWorker releases everything" (:1471-1472).
2. For every NON-candidate worker, send `worker_passivate_idle_children` (daemon-worker-protocol.ts:123-125; daemon-supervisor.ts:1470-1477) with a 30 s request timeout and `CHILD_PASSIVATION_PER_WORKER_CAP = 2`; then refresh summaries again. A failed sweep demotes the worker from this round (a disconnected/transitioning worker is never a candidate).
3. Under the eviction fence (a mutation-drain latch, `withEvictionFence`, daemon-supervisor.ts:1531-1543; drain timeout 5 s), re-refresh the candidates and `stopWorker(worker, true)` each, logging `Evicted idle worker ... idleMinutes ... sessions=N` (:1504-1515).

### 1.3 What stops at idle, and what stays (worker side, daemon-mode.ts)

The worker handles the sweep command at daemon-mode.ts:4158-4160 -> `passivateIdleChildren` (daemon-mode.ts:3193-3214): one snapshot pass over all session states, filter by `canPassivateSession`, **sort by lastActivityAt (LRU) and cap at the limit**, then passivate in parallel.

`passivateSession` (daemon-mode.ts:3121-3191) is the unit:
- Guards: the session must be a subagent with an `rlmChildId` and a resident parent (:3127-3129). Single-flight per resolved session file — an existing passivation is awaited, not duplicated (:3135-3139; the registry `passivatingSessions`, daemon-mode.ts:547, is keyed by resolved session file with the documented purpose: "Resolved-session-file keyed passivations let wake paths join after closeSessionOnce", :542-547).
- **The fresh-snapshot fence** (:3151-3153): the close re-checks `canPassivateSession` on a FRESH snapshot inside the passivation promise — touches between candidate selection and close are fenced out (shutting down, update restart, session identity change).
- The close itself (:3167-3179): detach parent tracking first (`releaseRlmChildSession`, "The registry/catalog rows remain the sole passive representation after close"), then the standard graceful close `closeSession(state, "shutdown", true, false)`, then log `Passivated idle child sessionId=... idleMinutes=...`.

**What stops** is the child SESSION's process residency inside the worker: the graceful close runs the session's `disposeAsync` (agent-session.ts:4915-4938 — concurrent callers join the same in-flight teardown; pending refinement is drained first, :4936; `_disposeAsyncOnce`, agent-session.ts:5075-5130, disposes the child's own in-process descendants, then `this._ipythonKernelProvisioner?.dispose({ snapshot: kernelSnapshot })` at :5108 — the kernel stop WITH the namespace snapshot flush to `kernel-state.dill`). So a passivated child loses: its in-memory session state, its kernel process (state snapshotted), its MCP transports, its in-memory queues. **What stays**: the session JSONL, the kernel snapshot, the daemon-side cron/harness stores, the registry/catalog row, the spawn-ledger edge, and the roster row (below).

### 1.4 The passive representation after close

- **Roster**: `passivatedWorkerRosterEntry` (agent-roster.ts:82-106) keeps every durable display field and zeroes the live ones — `activity: "idle"`, `isSessionActive: false`, `isStreaming/isCompacting: false`, `attachedClients: 0`, no pid/worker state, registered heartbeat/cron flags retained via the registrations argument. Used by the worker (daemon-mode.ts:7512) and the supervisor (daemon-supervisor.ts:4958). A passivated child STAYS a visible, addressable roster row rendered as idle.
- **Ledger/catalog**: the ledger edge is the topology authority that outlives the process. `withPassiveRlmDescendantInfos` (rlm-ledger.ts:903-937): "The catalog scan never visits session-artifacts, where RLM children persist: without this merge a passivated descendant's row (and its spend) survives only as long as some resident roster remembers it." The merge re-attaches `parentSessionPath` and `rlmDepth` from the live edge, so the passive row is family-addressable and its spend is accounted.

### 1.5 The revival paths

Four wake shapes, all sharing the same in-flight-join primitive:
1. **Explicit open joins a passivation in flight** (daemon-mode.ts:1888-1891): `createRuntime` finds the session key in `passivatingSessions`, awaits it, and re-runs the create.
2. **Bound-session lookups hydrate lazily** (daemon-mode.ts:2657-2666): a bound session that is passivating -> `waitForPassivation` -> `findPassiveRlmSubagent` -> `hydratePassiveRlmSubagent`.
3. **`hydratePassiveRlmSubagent`** (daemon-mode.ts:3226-3287): requires a RESIDENT root parent ("Cannot hydrate RLM subagent ... without a resident root parent"), walks the passive chain entry-by-entry (each entry first joins any in-flight passivation of its own file), handles a parent that went non-resident mid-walk by re-finding the passive entry and restarting, and rehydrates each link through `rehydrateCompletedRlmSubagent` (daemon-mode.ts:3290-3349: single-flight per session key over `reservingSessionOpens`/`openingSessions`, existing resident reuse, replaced-close then `rehydrateCompletedRlmSubagentOnce`).
4. **`rehydrateCompletedRlmSubagentOnce`** (daemon-mode.ts:3350+): `acquireSessionLease` + `SessionManager.openAsync(sessionFile)` + model re-resolve through the parent's registry + `createAgentSessionRuntime` with `sessionStartEvent "startup"` — i.e. the revival IS a full runtime construction replaying the session file, inside the SAME worker process.

### 1.6 The relaunch-on-prompt semantics (the whole-worker tier)

A prompt/open aimed at a session whose WORKER is gone (tier-2 eviction, or any stop) hits the supervisor's create path (daemon-supervisor.ts:3227-3282): resolve the session path, `matchWorkers` -> no resident -> **`launchWorker`** (daemon-supervisor.ts:3467+): spawn a FRESH `--mode daemon --daemon-socket` child process (:3520-3528) with a **fresh per-incarnation `workerInstanceId` + token** ("peer transport grants must never survive a worker restart"), reusing only the durable descriptor paths (worker id, socket path, descriptor + recovery journal). The new worker opens the session file and replays it; the client's prompt then lands as the next turn on the replayed session. The stop side (`stopWorker`, daemon-supervisor.ts:6911-7010) is graceful: tombstone/archive bookkeeping, transcript-cache disposal, a `shutdown` (or `worker_archive_and_shutdown`) request with a 5 s (1 s force) budget, SIGTERM as the fallback. The supervisor's crash path (`recoverWorker`, daemon-supervisor.ts:4277; :4357 relaunch) is the same relaunch machinery driven by failure instead of policy.

## 2. The Rust side's equivalent surface (the child worker process)

### 2.1 The architectural delta that defines this arm

In the Rust daemon, an RLM child is NOT an in-process session: it is its OWN worker process (the #2983 census tree: parent worker + child worker + two kernels). So the TS tier-1/tier-2 split collapses for children: the "whole-worker passivation" of a child worker is simultaneously the per-child release (tier 1's target, the child) and a whole-process stop (tier 2's mechanics). The Rust root-worker idle eviction (TS tier 2 for roots) is OUT OF SCOPE here — it is a separate, larger feature (owner clients, update restarts, wake-blind schedules, attached TUIs).

### 2.2 The residency being held (census evidence)

- **#2983 census** (record `20260927-234500`, same-VM sequential A/B, mock-provider spawn, ppid-attributed tree at settle): tip A holds parent worker 58.3 MB + child worker 52.5 MB + BOTH kernels (26.8 + 26.9 = 53.7 MB); candidate B releases the child's kernel (~27 MB/child, the parent root keeps its kernel by policy) but the child WORKER stays (55.6 MB). This is the LIGHT shape (short-transcript child).
- **worker-rss baseline census** (record `20260926-183300`, tip `60e2e198c`, pure release binary): the LOADED shape — worker RSS at create-end 140.9 MB, adopt-end pre-trim 243.5 MB, settle 218.4 MB on the 10 MiB corpus; `memory_idle_load_n10_worker_rss_mb` p50 207.53 MB (same-build spread 182.46-217.88 = the 35.4 MiB noise band); slope ~17.3 MB RSS per MiB corpus; and the census's attribution: 3 of 5 retained copies of the corpus are derivable duplicates (B/C1/C2, ~31 MB wire on 10 MiB).
- So after #2983 (kernel ~27 MB/child banked), the deferred arm's marginal win is the child WORKER process: **52-58 MB in the light census shape, up to ~141-244 MB in the loaded shape** — with the honest caveat that the loaded shape is dominated by the known redundancy copies that the worker-rss adopt-onecopy lane already targets cheaper.

### 2.3 The supervision map (rlm_children.rs, checkout 60e2e198c)

`SupervisorChildSessions` is the parent kernel's handle on its children (one per parent session, shared across handler calls):
- **ChildRecord** (:154-207) is the parent's durable-side bookkeeping: `rlm_child_id`, `active_session_id`, `session_id`, `session_name`, `session_dir`, `settled_status` (done/error/cancelled), `answer_preview`/`answer_captured`, `replied_since_task`, `notice_delivered`, `prompt_admitted`, `error`, `closed_by_parent`, `session_file`, `attributed_rows` (the usage-attribution cursor over the child's session file), `usage_watch_live`/`usage_rearm`.
- **The wire calls** all go over the daemon socket: `prompt_child` (:878, `DaemonCommand::Prompt`), `kill_child` (:905, `Kill` + `rlmCloseReason` marker), `child_busy` (:923, `GetState` isStreaming || queuedCount>0), `child_answer` (:943, `GetLastAssistantText`), `wait_for_child` (:961, `WaitForIdle`, "a timeout returns current snapshots, never an error").
- **The frozen surfaces #2983 kept byte-identical**:
  - `list_subagents` (:1929-1943): a PURE record snapshot — no live worker dependency.
  - `collect` (:2038-2091): record refresh + optional re-arm of the usage watch when a settled child is busy again + bounded idle waits inside the caller's budget; timeout yields snapshots, never an error.
  - `delete_subagent` (:1944-2037): kill via the wire (with `rlmLedgerDelete`/`rlmChildId` markers), pre/post-kill usage captures from the file, registry removal, the cancelled terminal notice.
  - `child_snapshots` (:447) and the settle/usage watchers.
- **The watchers**: `watch_child_settle` (:1011-1092) polls until settle (slice waits + a settle grace + usage slices + the terminal notice + `fire_settle_hook`) and — critically — marks an UNREACHABLE child `error: "Child worker unreachable"` after `WATCH_MAX_UNREACHABLE_POLLS` and exits. `watch_child_usage` (:1283-1416) is the follow-up usage watcher for retained children: it waits for idle, observes the delivered turn, and on unreachable poll exhaustion bills whatever rows the child's FILE already holds and retires (usage attribution reads the durable file, not the live worker — `emit_child_usage` + `attributed_rows` cursor).
- **The spawn path** (:1721-1863): depth gate, name assertion, model allowlist resolve, `create_child` (:725: a `DaemonCommand::Create` with `rlmDepth`/`rlmMaxDepth`/`parentSessionPath` config and `runtime_metadata` = {kind: subagent, rlmChildId, parentActiveSessionId, rlmDepth, createdAt} + the resolved model "so the supervisor's display entry carries it for passive hydration"), then the ChildRecord registration and the DETACHED prompt admission after the parent's turn boundary (`wait_turn_done`), with the `session_file_carries_prompt` (:2091) arbitration for ambiguous route failures ("The session file is the record a worker replacement replays from").

### 2.4 What the Rust daemon ALREADY has (the ~70%)

- **The roster passivation on worker stop**: `passivate_roster_worker` (supervisor_roster.rs:249+, the TS `flipWorkerRosterEntriesInactive` port) runs on every stop-class path today (crash give-up: supervisor/supervision.rs:125-128 "every owned non-ephemeral, non-queued row passivates and keeps its model/thinking/cwd"). The doc comment is explicit and is EXACTLY the deferred arm's roster semantics: "a stopped session's row stays visible in the agents view instead of vanishing until the next catalog scan re-lists it from disk; a subagent row keeps the family walk (the live edge and a surviving resident root anchor it)" — with sequence-slot clearing and a replacement-live guard.
- **The wake/relaunch machinery**: `wake_saved_target` (messaging.rs:192-283) — the send_message path already wakes a non-resident target: catalog-resolve the selector, reuse a resident worker hosting the file, otherwise `launch_worker` over it ("the headless resume machinery"). The crash path relaunches workers (`relaunch_worker`, supervision.rs:160-166). `create_reuse.rs` owns the create/reuse/opening-guard logic.
- **The passive child representation**: `rlm_roster.rs:1-237` (the TS `walkPassiveRlmSubagents` port): `walk_passive_rlm_children` ("A resident child contributes no passive row"), the per-edge hydration metadata (:135-171, "the ledger edge ... is always the topology authority"), `passive_child_summary` (:172+, the TS `buildSessionListWithPassiveRlmSubagents` port). `rlm_ledger.rs:5`: the ledger keeps children roster-visible after passivation; the own-usage snapshot rides the edge (the spend survives the transcript).
- **Durable identity for replay**: the session header carries `rlmDepth` (session_store.rs:578-580, "TS `config.rlmDepth ?? header.rlmDepth`"); supervisor.rs:1333/3872/4102/4371 read the rlmDepth/rlmMaxDepth/parentSessionPath keys; the ledger edge carries parent/child/depth/childId.
- **#2983's contributions (in review, branch `lane/perf-revive-2483`, fold eea1794bb)**: `IpythonKernelProvisioner::stop_kernel` (the snapshot-flushing stop + the `pendingStop` revival gate; revival proven by `kernel_stop_revive`: `kernel-state.dill` flushed, `manager().is_none()`, the marker variable REVIVES through the gate), the engine seam `release_settled_child_kernel` with the `canPassivateSettledSession` gates (no unsettled descendants; the worker-wired registered-jobs probe over the shared cron store), and the child's own idle PARK ARM as the trigger surface (parent-owned rlm_depth>0 + unattached + not compacting + no lane work; per-turn granularity, a no-live-kernel stop is a no-op).

### 2.5 The measured relaunch cost (the revival budget's evidence)

From `20260926-204300` (spawn-admission-decompose, n22 legs, same-VM): total spawn-to-admit p50 **281.8 ms** (min 117.8 / max 385.1) in the DEGRADED fresh-write storage regime (the dominant class: fresh-file+sync_all+rename at ~38-45 ms/op; the record discloses the regime); the phase split: spawn-call->child-exec p50 **3.8 ms**, exec->registered p50 **77.3 ms** (the actual process boot), registered->re-reg p50 209.6 ms (async, durability-write-bound), re-reg->admit p50 0.8 ms. "Process exec, worker boot, wire, roster seeding, and kernel provisioning are NOT on the critical path" — the cost is durability writes. From the worker-rss baseline (10 MiB fixture): cold-open ready p50 ~938 ms (the launch-open single-parse candidate targets part of it). A typical settled child's transcript is far smaller than 10 MiB, and the kernel boots LAZILY on first ipython use (the #2983 accepted revival class).

## 3. The design: what a Rust worker-restart-at-idle would need

### 3.1 The durable state set (what must be on disk BEFORE the stop)

| State | Where it lives today | Stop-safe? |
|---|---|---|
| Conversation/session log | the session JSONL under session-artifacts (append+fsync per the io lanes) | YES (durable by construction) |
| Kernel namespace | `kernel-state.dill` via #2983 `stop_kernel` (snapshot flush + atomic rename) | YES **only if the park arm's kernel release has fired first** — the stop MUST sequence after it (a live kernel at stop time = flush-then-stop, never kill-with-live-kernel) |
| Subagent identity (depth, child id, parent linkage) | the session header `rlmDepth` (session_store.rs:578-580) + the spawn-ledger edge (child/parent/depth/childId) | YES |
| Spend attribution | the ledger edge's own-usage snapshot + the parent's `attributed_rows` cursor over the child's file | YES — and the parent's usage watchers already bill from the FILE, not the live worker |
| Harness state (memories/skills/prompt notes) | on-disk harness store | YES |
| Cron/heartbeat registrations | the shared cron store (the #2983 registered-jobs probe surface) | YES (daemon-side) |
| In-flight turn state | worker memory | NOT durable — gated off (idle-only stop) |
| Live background bash() handles | the child worker's process tree | NOT durable — MUST be gated off (a live handle orphans at worker death) |
| MCP transports | worker memory | NOT durable — re-established on demand (TS accepts the same at disposal) |
| The roster row | daemon roster + ledger | survives via `passivate_roster_worker` (already live for stop-class paths) |

### 3.2 The gate set (the stop policy)

Reusing #2983's engine gates plus the worker-stop-specific additions:
1. Parent-owned child (rlm_depth > 0), unattached, not compacting, no lane work (the #2983 park-arm policy).
2. **Settled AND idle**: `settled_status` set + `child_busy == false` (GetState isStreaming/queuedCount) + no pending admissions (the TS `isSessionActive` analog, daemon-mode.ts:3111).
3. No unsettled descendants (the engine `has_unsettled_rlm_work` gate, #2983).
4. No registered cron (non-heartbeat) — the #2983 registered-jobs probe.
5. **Armed heartbeats: BLOCK** (a deliberate divergence, disclosed): TS tier-1 excludes heartbeat jobs from the cron gate but shields whole WORKERS via `hasWakeBlindSchedule` (daemon-supervisor.ts:1412) — i.e., a heartbeat-armed worker never evicts. The Rust daemon has NO wake-blind schedule and no heartbeat-driven child-worker wake; blocking on armed heartbeats is the minimal parity-safe choice until a wake-blind port exists.
6. **No live background bash handles** (STRONGER than #2983's kernel stop): the kernel snapshot cannot resurrect a live process; TS never passivates a bash-running session (the `isSessionActive` summary includes bash). The engine gate needs a worker-wired bash-running probe.
7. The idle clock: `now - lastActivity >= idleEvictionMinutes * 60_000` with the TS default 90 (settings surface `idleEvictionMinutes`, `"off"` disables) — NOT stop-at-settle: #2983 releases the kernel AT the settle park (cheap, snapshot-backed), but killing a whole worker on every settle would thrash the fleet's collect-within-minutes patterns; the 90-min hysteresis is the TS semantics and the right default.
8. The fresh-snapshot fence at stop time (the TS daemon-mode.ts:3151-3153 pattern): re-verify the gate set inside the stop's own critical section, single-flight per session file (a `passivatingSessions`-equivalent map so wake paths JOIN an in-flight stop rather than racing it).

### 3.3 The trigger and the driver

The idle sweep is NOT ported to Rust at all — no `idleEvictionMinutes` setting, no sweep loop. The arm therefore needs a NEW DRIVER. Two options:
- **(a) Daemon-side sweep (the TS shape)**: a supervisor timer at the TS cadence (max(60s, min(5min, idle/3))) that queries each parent worker's children for the gate set and issues stops. Parity-faithful, but it puts child-policy knowledge in the supervisor (the TS sweep's `worker_passivate_idle_children` round-trip exists precisely because the worker owns its session states).
- **(b) Worker-side park-arm continuation (the #2983 shape, recommended)**: the child worker's OWN park arm — which already fires #2983's kernel release — checks the idle clock (its own last-activity + the gate set it already computes) and, when the 90-min threshold holds, signals the DAEMON (its supervisor link) to stop it gracefully. The parent's `SupervisorChildSessions` learns the passivated state on the record (a status transition like the existing `settled_status`, NOT a wire failure). This keeps the policy on the worker (where the bash/descendant/cron probes live) and the mechanics on the daemon (where `stopWorker`/`passivate_roster_worker` live), and it reuses the #2983 trigger surface with zero new polling on the parent kernel.

### 3.4 The stop sequence (the mechanics, all existing pieces)

1. The child worker verifies the gate set (3.2) under the fence; announces the passivation intent (the durable identity is published BEFORE the close, the TS daemon-mode.ts:542-547 lesson).
2. Kernel: the #2983 park arm has already released the kernel at settle (snapshot flushed); if a revival re-booted it, flush-then-stop again (stop_kernel is a no-op on a stopped kernel).
3. The daemon (or the worker's own graceful exit) runs the stop: the existing `stopWorker` graceful path (tombstone bookkeeping, shutdown request with a bounded budget, SIGTERM fallback — the Rust equivalents live in the supervisor's stop/cleanup paths), then `passivate_roster_worker` (supervisor_roster.rs:249) flips the roster row to the passive shape, and `registry.remove` retires the route.
4. The parent's `ChildRecord` KEEPS the row: `list_subagents`/`collect` are already record-served; the child's spend keeps flowing from the file (the usage watchers already read the file).

### 3.5 The revival path and the latency budget

The revival is the EXISTING wake machinery aimed at the child:
1. A follow-up prompt / agent_message / collect-with-timeout / open aimed at the child resolves to no resident worker -> the `wake_saved_target` shape (messaging.rs:192-283): catalog/ledger resolve (the passive walk keeps the child addressable: rlm_roster.rs), reuse-or-`launch_worker` over the session file.
2. The new worker replays the session JSONL; the header restores `rlmDepth` (session_store.rs:578-580); the ledger edge restores parent linkage; the model/thinking/cwd ride the display entry (the passive-hydration metadata).
3. The first kernel use boots fresh and revives from `kernel-state.dill` through the `pendingStop` gate (the #2983 proven mechanism).

**Latency budget (evidence-based)**: wake route + process exec ~81 ms p50 (spawn->exec 3.8 + exec->registered 77.3), replay proportional to the child's transcript (the cold-open p50 ~938 ms is the 10 MiB ceiling; a settled child is far smaller), the daemon-side create/route tail dominated by durability writes (the 209.6 ms re-registration phase in the degraded regime), and the kernel lazily on first ipython use. Budget: **sub-second to ~1-2 s for typical children**, against the TS in-worker hydration's advantage of no process spawn (the TS tier-1 revival) — but the TS tier-2 (whole-worker) revival pays the same spawn cost, and the Rust child IS a worker, so the parity target is tier-2, not tier-1.

### 3.6 The failure modes

- **An in-flight turn at stop time**: fenced by the gate set (idle-only) + the fresh-snapshot re-check; a prompt admitted in the race window joins the in-flight stop (the single-flight map) and lands on the revived worker — the `session_file_carries_prompt` arbitration (rlm_children.rs:2091) already exists for exactly this ambiguity class on the replacement path.
- **A stop crashes mid-flush**: the kernel snapshot write is atomic (flush+rename); the worker dies unclean -> the revival replays the file; worst case the kernel state falls back to a fresh boot (the #2983 accepted failure class: "a failed stop leaves the kernel resident" / a failed snapshot revives fresh).
- **The parent's watchers on a stopped child**: `watch_child_settle` has already exited at settle (it returns after the terminal notice). The follow-up usage watcher treats unreachability as "bill the file rows and retire" — for a passivated child that is CORRECT spend behavior, but the watcher must not be the thing that decides the child is dead: the record keeps `settled_status` and the row; `refresh_record`'s unreachable branch keeps the last known state (rlm_children.rs:978-1009 "An unreachable child keeps its last known state (the supervisor may be restarting)"). The design must make passivation a POSITIVE status on the record (not an error), so the unreachable-poller never marks a passivated child `error: "Child worker unreachable"` — that path (rlm_children.rs:1074-1089) is the one place a passivated child would be mis-scored today.
- **The supervisor's view**: the daemon roster shows the child's row flipping resident->passive — `passivate_roster_worker` already produces the TS-parity shape (the agents view keeps the row, activity idle); the frozen-surface bar (TUI output bytes) needs a byte-oracle across the transition, and the parent kernel's `rlm.list_subagents` row (record-served) must stay byte-identical — it is today, by construction.
- **The parent dies while the child is passivated**: the ledger edge + the session file survive; `close_children_of_dead_parent` (supervision.rs:88-92) closes LIVE children of a crashed parent — a passivated child has no live worker to close; its row dies with the family per the ledger's lifecycle (the same as any completed child today).
- **Delete of a passivated child**: `delete_subagent` kills via the wire — a stopped child cannot be killed; the path needs a passivation-aware branch (tombstone the ledger + delete the file + remove the record, no wire kill). This is a REAL gap, same class as the wake extension.

### 3.7 The TS-parity delta table

| Dimension | TS (the reference) | Rust (the deferred arm) | Delta class |
|---|---|---|---|
| Passivation target | the child session in-process within a shared worker (tier 1) | the whole child WORKER process (the child IS a worker) | STRUCTURAL — already disclosed and accepted in #2983's parity notes |
| Driver | supervisor sweep every max(60s, idle/3), `worker_passivate_idle_children`, cap 2/worker/round | RECOMMENDED: the child's own park arm + the idle clock (no supervisor sweep exists in Rust) | INTERNAL (no wire/schema change; a new daemon-side stop signal or a worker-initiated graceful exit — needs the frozen-wire review if a new command is added) |
| Idle threshold | 90 min default (`idleEvictionMinutes`, "off" disables) | port the same setting + default | PARITY (new setting surface — settings are additive) |
| Gates | !isSessionActive (bash/streaming/queued/admissions) + no cron (non-heartbeat) + no live descendants + not hydrating + the fresh-snapshot fence | the #2983 gates + child_busy + no bash + cron probe + **heartbeats BLOCK** (no wake-blind port) | DELIBERATE DIVERGENCE (heartbeats): TS passivates heartbeat children at tier 1 but shields the worker at tier 2; Rust blocks — safer, disclosed |
| What stops | session state + kernel (snapshot) + MCP, in-process | the whole worker process (same state set + the process) | same semantics, larger release (the point of the arm) |
| Roster after | `passivatedWorkerRosterEntry` (row survives, live fields zeroed) | `passivate_roster_worker` (the ported flip) + the record-served kernel roster | PORTED (needs the byte-oracle across the transition) |
| Revival | in-worker `hydratePassiveRlmSubagent` (replay in-process) / `launchWorker` at tier 2 | `wake_saved_target`-shaped relaunch (replay in a fresh process) | TS tier-2-equivalent; the spawn delta (~80 ms) disclosed |
| Wake triggers today | open, attach, a2a, collect, prompt — all wake | send_message wakes today; prompt/collect/delete need the passivation-aware branches | THE GAP |
| Spend/ledger | `withPassiveRlmDescendantInfos` merge | rlm_ledger + rlm_roster passive walk (ported) | PORTED |
| In-flight-turn arbitration | the passivation fence + join | the single-flight join + `session_file_carries_prompt` | PORTED (the prompt-arbitration primitive exists) |

### 3.8 The relaunch cost vs the holding cost

- Holding (the marginal win, post-#2983): 52-58 MB/child (light census shape) to ~141-244 MB (loaded shape; but the loaded shape's dominant cost is the known B/C1/C2 redundancy copies that the worker-rss adopt-onecopy lane removes cheaper and already landed evidence for).
- Relaunch: ~0.3-1 s p50 per revival (process + replay + route; the kernel lazily), plus the settings/registry churn, plus the regression surface below.
- The win fires only for children idle >= 90 min: in hillclimb bench shapes (collect-within-minutes) it almost never fires; on long-lived production daemons with many settled children it is the difference between a fleet of resident workers and a catalog.

## 4. The recommendation

**DEFER — do not implement this arm now.** Not DISCARD (the parity debt is real: the TS daemon's idle-eviction tier is entirely absent from the Rust port, the census proves the residency, and ~70% of the machinery exists — the lane is bounded), and not IMPLEMENT (the cost/risk is wrong this wave):

1. **The marginal win is halved by #2983 and halved again by the worker-rss lanes.** #2983 banks the kernel (~27 MB/child, in review); the loaded-shape worker cost is dominated by the redundancy copies the adopt-onecopy lane targets. Sequence those first; re-census after.
2. **The win is production-shaped, not hillclimb-shaped.** The 90-min idle clock rarely fires in fleet bench patterns; the lane would ship with no in-harness evidence of its own win — a green-fishing risk.
3. **The real work is on frozen surfaces.** The idle driver is small; the passivation-aware branches (prompt follow-ups, delete, the unreachable-scorer, the wake extension to parent-owned paths) touch the roster/collect/delete semantics that #2983 deliberately kept byte-identical — a lane-scale change with a byte-oracle burden, not a park-arm bolt-on.
4. **Two policy decisions are unresolved and orchestrator-owned**: the heartbeat block (vs a wake-blind port) and the idle default (90 min vs fleet-tuned).

**Revisit triggers** (any one reopens the arm): (a) #2983 merges AND the worker-rss redundancy lanes land, and a fresh census still shows >= 50 MB/child resident at settle in production-like shapes; (b) a production-shape report of many long-idle settled children on one daemon (the fleet's long-lived boxes); (c) the operator asks for the daemon idle-RSS floor to drop below the post-#2983 baseline; (d) a TS-parity sweep of the daemon's idle-eviction tier is scheduled anyway (then this arm rides it: the driver + the settings port are the bulk of that tier's cost).

**If implemented, the lane shape**: (1) port `idleEvictionMinutes` (default 90, "off") + the child-side idle clock on the park arm; (2) the gate set of 3.2 with the bash probe + heartbeat block; (3) the graceful stop via the existing stop path + `passivate_roster_worker`; (4) a POSITIVE passivated status on the ChildRecord (never the unreachable-error path); (5) the wake extension for parent-owned prompts/collect/delete; (6) the roster byte-oracle across the transition + the revival oracle (a settled child revived by a follow-up prompt must answer from the replayed file with the kernel marker reviving through the #2983 gate); (7) the census: same-VM sequential A/B of the daemon tree at settle with >= 90-min-fast-forwarded clocks (a scripted clock, disclosed) proving the worker process gone and the revival path green.

## 5. Scope boundary

This analysis covers the CHILD worker arm only. The TS tier-2 ROOT-worker idle eviction (owner clients, attached TUIs, update restarts, wake-blind schedules, `canEvictWorker`'s whole-tree policy) is a separate, larger port and is NOT justified by this evidence either way.

## 6. Citations index

TS reference (`/home/ubuntu/prime-agent-ts` @ cd1f215): session-action-store.ts:377-437 (the two-tier policy + thresholds), settings-manager.ts:11/215/928-931 (idleEvictionMinutes, default 90), daemon-supervisor.ts:250-253/700-706/1390/1441-1515 (sweep driver, cadence, fence, eviction), :3227-3282/3467-3560/6911-7010 (create/relaunch/stop), daemon-worker-protocol.ts:123-125 (the sweep command), daemon-mode.ts:542-547/1888-1891/2657-2666/3084-3120/3121-3191/3193-3214/3217-3224/3226-3349/3350+/4158-4160 (snapshot, passivate, join, hydrate), agent-session.ts:4915-4938/5075-5130 (the graceful disposal + kernel snapshot), agent-roster.ts:82-106 (the passivated roster row), rlm-ledger.ts:903-937 (the passive descendant merge).

Rust (`/home/ubuntu/prime-agent-rust` checkout 60e2e198c; origin/rust 95f425a3d read 2026-09-28; #2983 seams cited from PR record 20260927-234500): rlm_children.rs:145-227/447/652-977/978-1092/1283-1416/1721-1863/1929-1943/1944-2037/2038-2091/2091+ (the record, wire, watchers, spawn/roster/collect/delete), supervisor_roster.rs:249+ (passivate_roster_worker), supervisor/supervision.rs:80-170 (crash/give-up/passivate/relaunch), messaging.rs:1-9/34-160/192-283 (the wake), rlm_roster.rs:1-237 (the passive walk + summaries), rlm_ledger.rs:5/1190-1324 (the edge + spend), session_store.rs:578-580 (header rlmDepth), agent_engine.rs:921/935-938 + worker/lifecycle.rs:113 + worker/commands.rs:706 + supervisor_lost.rs:126 (dispose seams).

Census/records: 20260927-234500 (#2983, the settle tree + revival oracle), 20260926-183300 (worker-rss baseline: 140.9/243.5/218.4 MB create/adopt/settle; 207.53 MB idle-load p50; the redundancy copies), 20260926-204300 (spawn-admission decompose: 281.8 ms p50 total; 3.8/77.3/209.6/0.8 ms phases).

*This document is the design pre-analysis for the orchestrator's deferred-decision; no product code was changed by this lane.*
