# TS anchor: second-kernel cost on in-process whole-session replacement (new_session / switch_session / fork)

Scope: one research question — what does the TypeScript reference implementation pay for a SECOND ipython kernel when an RPC-hosted session is replaced in-process, and does that cost sit inside the new_session/switch_session/fork response wall?
Tree read (read-only): /home/ubuntu/prime-agent-ts. All citations are absolute `path:line`. Code states are as of 2026-09-27.

Baseline chain (RPC stdio surface): `runRpcMode` builds an `InProcessAgentConnection` over an `AgentSessionRuntime` (`/home/ubuntu/prime-agent-ts/packages/coding-agent/src/modes/rpc/rpc-mode.ts:41-46`). A command's response is written to stdout only after its handler resolves: `output(await handleCommand(command))` at `/home/ubuntu/prime-agent-ts/packages/coding-agent/src/modes/rpc/rpc-mode.ts:480`; the `new_session` case awaits `connection.newSession(...)` at `rpc-mode.ts:237-244`, `switch_session` at `rpc-mode.ts:313-314`, `fork` at `rpc-mode.ts:315-318`.

---

## Q1. KERNEL OWNERSHIP

**Answer: one `IpythonKernelProvisioner` (and thus one kernel process) per `AgentSession`. A replacement generation builds a NEW `AgentSession`, so it spawns a SECOND kernel process. No kernel process, provisioner, or namespace snapshot is reused across replacement generations. The only shared state is the machine-wide kernel venv, the process-wide boot semaphore, and the in-flight venv-ensure promise.**

Wiring, quoted:

- Per-session field: `private _ipythonKernelProvisioner?: IpythonKernelProvisioner;` — `/home/ubuntu/prime-agent-ts/packages/coding-agent/src/core/agent-session.ts:1691`.
- The session constructor synchronously calls `_buildRuntime(...)` — `/home/ubuntu/prime-agent-ts/packages/coding-agent/src/core/agent-session.ts:1867-1870`.
- `_buildRuntime` (when no `baseToolsOverride`) constructs a fresh provisioner per build: `this._ipythonKernelProvisioner = new IpythonKernelProvisioner(this._cwd, { env, commandPrefix, shellPath, sessionId, hostHandlers, pythonSkills, snapshotDir, readyGate: previousDispose, ... })` — `/home/ubuntu/prime-agent-ts/packages/coding-agent/src/core/agent-session.ts:10810-10825`, and hands THAT provisioner to the ipython tool: `createAllToolDefinitions(this._cwd, { ipython: { provisioner: this._ipythonKernelProvisioner, ... } })` — `/home/ubuntu/prime-agent-ts/packages/coding-agent/src/core/agent-session.ts:10826-10834` (provisioner handed over at `agent-session.ts:10828`).
- The tool factory consumes the passed provisioner or, only when none is passed, makes its own: `const provisioner = options?.provisioner ?? new IpythonKernelProvisioner(cwd, options);` — `/home/ubuntu/prime-agent-ts/packages/coding-agent/src/core/tools/ipython.ts:682`, reached via `createAllToolDefinitions` — `/home/ubuntu/prime-agent-ts/packages/coding-agent/src/core/tools/index.ts:53-57`. The session path always passes its own provisioner; repo-wide, the only `new IpythonKernelProvisioner` sites are `agent-session.ts:10810` and the `ipython.ts:682` fallback. The `provisioner` option exists for hosts that want sharing ("Shared provisioner owning the kernel lifecycle. When provided, the remaining options are ignored." — `/home/ubuntu/prime-agent-ts/packages/coding-agent/src/core/tools/ipython.ts:349-350`), but no replacement path uses it.
- Provisioner class doc: "Owns the lazy create+start+runtime-bootstrap of one session's Python kernel." — `/home/ubuntu/prime-agent-ts/packages/coding-agent/src/core/tools/ipython.ts:353-359`.

What IS shared (not per-session, but not kernel state either):

- Kernel venv: one directory per machine — `getKernelVenvDir()` returns `~/.prime/agent/kernel-venv` — `/home/ubuntu/prime-agent-ts/packages/coding-agent/src/core/kernel/bootstrap.ts:387-390`; resolved per boot via `resolveWritableKernelVenvDir()` — `bootstrap.ts:400-416`.
- Boot concurrency gate: a lazily created process-wide semaphore — `/home/ubuntu/prime-agent-ts/packages/coding-agent/src/core/kernel/boot-gate.ts:27-34`.
- In-flight venv-ensure promise: module-level single slot — `let inFlightEnsureKernelPython` — `bootstrap.ts:109` (see Q5).
- Namespace snapshots are per-session artifact dirs: `this._ipythonKernelSnapshotDir = this.sessionManager.getSessionArtifactDir();` — `/home/ubuntu/prime-agent-ts/packages/coding-agent/src/core/agent-session.ts:10805`; the kernel gets `snapshot: { path: snapshotPathIn(snapshotDir), manifestPath: ... }` — `/home/ubuntu/prime-agent-ts/packages/coding-agent/src/core/tools/ipython.ts:532-535`.

Same-session rebuilds (NOT replacement): `/reload` and ACP-MCP rebuilds call `_buildRuntime` again on the SAME session object; there the previous provisioner is disposed and the new kernel's startup is gated on that dispose (`const previousDispose = this._ipythonKernelProvisioner?.dispose();` ... `readyGate: previousDispose` — `/home/ubuntu/prime-agent-ts/packages/coding-agent/src/core/agent-session.ts:10804`, `:10816`, with the rationale comment at `agent-session.ts:10799-10803`). Replacement generations are separate `AgentSession` objects (see Q2), so a fresh provisioner has no `readyGate` (`this._ipythonKernelProvisioner` is still `undefined` at first construction).

---

## Q2. THE REPLACEMENT FLOW

**Answer: the flow DOES await `teardownForReplacement`, and `teardownForReplacement` awaits the OLD session's full dispose — including the old kernel's final snapshot flush, host-request drain, and protocol shutdown. It then awaits construction of the new `AgentSession`, whose kernel prewarm is fire-and-forget (Q3). So the response wall contains the old kernel's teardown and extension events, but NOT the new (second) kernel's boot.**

Call chain with awaited steps:

1. RPC: `output(await handleCommand(command))` — `/home/ubuntu/prime-agent-ts/packages/coding-agent/src/modes/rpc/rpc-mode.ts:480`; `new_session` → `await connection.newSession(...)` — `rpc-mode.ts:237-244`; `switch_session` → `await connection.switchSession(command.sessionPath)` — `rpc-mode.ts:313-314`; `fork` → `await connection.fork(command.entryId)` — `rpc-mode.ts:315-318`.
2. Connection delegates: `async newSession(...) { return this.runtimeHost.newSession(options); }` — `/home/ubuntu/prime-agent-ts/packages/coding-agent/src/modes/agent-connection/in-process-agent-connection.ts:551-552`; `switchSession` — `in-process-agent-connection.ts:554-559`; `fork` — `in-process-agent-connection.ts:561-566`.
3. Runtime `newSession` (`/home/ubuntu/prime-agent-ts/packages/coding-agent/src/core/agent-session-runtime.ts:453-497`), in order:
   - `await this.emitBeforeSwitch("new")` — `agent-session-runtime.ts:459` (extension `session_before_switch` handlers; can cancel — `agent-session-runtime.ts:166-180`).
   - `SessionManager.create(...)` + optional parent header — `agent-session-runtime.ts:464-470` (sync).
   - `const lease = this.acquireReplacementLease(...)` — `agent-session-runtime.ts:472` (sync; lease reuse-if-same-path at `agent-session-runtime.ts:224-229`).
   - **`await this.teardownForReplacement("new", sessionManager.getSessionFile(), lease)`** — `agent-session-runtime.ts:474`.
   - **`await this.buildAndApplyReplacement(...)`** — `agent-session-runtime.ts:475-487`.
   - `await this.finishSessionReplacement(options?.withSession)` — `agent-session-runtime.ts:496`.
   `switchSession` is the same shape at `agent-session-runtime.ts:409-449` (teardown `:431`, build `:432`, finish `:449`); `fork` at `agent-session-runtime.ts:500-627` (three variants: teardown `:545`/`:574`/`:607`, build `:546`/`:575`/`:608`, finish `:563`/`:592`/`:625`).
4. `teardownForReplacement` — `/home/ubuntu/prime-agent-ts/packages/coding-agent/src/core/agent-session-runtime.ts:266-277` — awaits `teardownCurrent(reason, targetSessionFile)` — `agent-session-runtime.ts:272`.
5. `teardownCurrent` — `/home/ubuntu/prime-agent-ts/packages/coding-agent/src/core/agent-session-runtime.ts:200-210`:
   - `await emitSessionShutdownEvent(... { type: "session_shutdown", reason, targetSessionFile })` — `agent-session-runtime.ts:201-205`.
   - `this.beforeSessionInvalidate?.()` — `agent-session-runtime.ts:206` (sync host callback).
   - **`await this.session.disposeAsync()`** — `agent-session-runtime.ts:208`, with the comment "Await the kernel's final snapshot flush before invalidating the session."
   - `await this.disposeHostedSubagentRuntimes()` — `agent-session-runtime.ts:209`.
6. `AgentSession.disposeAsync` — `/home/ubuntu/prime-agent-ts/packages/coding-agent/src/core/agent-session.ts:4919-4940`: concurrent callers join one in-flight promise (`agent-session.ts:4923-4927`); `kernelSnapshot` defaults to `true` (`agent-session.ts:4928`); it awaits `_drainPendingRefinementForDisposal()` (`agent-session.ts:4932`) then `_disposeAsyncOnce(kernelSnapshot)` (`agent-session.ts:4938`).
7. `_disposeAsyncOnce` — `/home/ubuntu/prime-agent-ts/packages/coding-agent/src/core/agent-session.ts:5075-5114`: awaits RLM child-session disposals (`agent-session.ts:5078-5106`), then **`await this._ipythonKernelProvisioner?.dispose({ snapshot: kernelSnapshot })`** — `agent-session.ts:5108`, then `this.dispose()` and `await this._disposeCallbacksPromise` — `agent-session.ts:5112-5113`.
8. `IpythonKernelProvisioner.dispose` — `/home/ubuntu/prime-agent-ts/packages/coding-agent/src/core/tools/ipython.ts:408-421`: sets snapshot policy (`ipython.ts:410`), aborts a still-queued/in-flight startup (`this.disposeController.abort()` — `ipython.ts:414`), then **awaits the pending startup promise** (`const m = await pending;` — `ipython.ts:418-419`) and **`await m.shutdown({ snapshot: this.disposeSnapshot, drainHostRequests: true })`** — `ipython.ts:421`.
9. `ReplKernelManager.shutdown` → `performShutdown` — `/home/ubuntu/prime-agent-ts/packages/coding-agent/src/core/kernel/repl-manager.ts:1463-1481`, `:1482-1558`: `await this.flushSnapshotForDispose()` when snapshotting (`repl-manager.ts:1491-1492`; flush implementation joins concurrent teardowns and runs the final snapshot cell, `repl-manager.ts:1744-1779`, bounded by `SNAPSHOT_EXECUTION_TIMEOUT_MS = 5000` — `/home/ubuntu/prime-agent-ts/packages/coding-agent/src/core/kernel/shared.ts:9`); host-request drain bounded by `HOST_REQUEST_SHUTDOWN_TIMEOUT_MS = 5000` (`repl-manager.ts:1506-1510`; `shared.ts:6`); then protocol shutdown + kernel exit bounded by `KERNEL_SHUTDOWN_TIMEOUT_MS = 5000` (`repl-manager.ts:1511-1536`; `shared.ts:7`).
10. `buildAndApplyReplacement` — `/home/ubuntu/prime-agent-ts/packages/coding-agent/src/core/agent-session-runtime.ts:251-263` — awaits `build()` (`agent-session-runtime.ts:257`), i.e. `this.createRuntime(...)` → `createAgentSessionRuntime` → `createAgentSessionFromServices` → `new AgentSession({...})` (`/home/ubuntu/prime-agent-ts/packages/coding-agent/src/core/sdk.ts:360-394`). The constructor runs `_buildRuntime` synchronously (`agent-session.ts:1867-1870`), which fires `prewarm()` (Q3) — **nothing kernel-related is awaited here**.
11. `finishSessionReplacement` — `/home/ubuntu/prime-agent-ts/packages/coding-agent/src/core/agent-session-runtime.ts:397-405` — awaits `rebindSession` (connection rebind + `session_replaced` emit — `/home/ubuntu/prime-agent-ts/packages/coding-agent/src/modes/agent-connection/in-process-agent-connection.ts:98-108`), session-replaced listeners, and the optional `withSession` callback. `bindCurrentSessionExtensions` awaits extension binding only (`in-process-agent-connection.ts:672-697`); no kernel wait.

Cost profile of the wall (warm old kernel): extension `session_shutdown` events + old kernel final snapshot flush + drain + graceful shutdown (each 5 s-capped) + child-session disposals + new `AgentSession` construction (sync) + rebind. The second kernel's boot is NOT in the wall.

Special case — old kernel still BOOTING when replacement arrives: `dispose` aborts the in-flight startup (`ipython.ts:414`); `m.start()` is raced with the abort signal (`raceStartupWithAbort(this.startPromise, options.signal)` — `/home/ubuntu/prime-agent-ts/packages/coding-agent/src/core/kernel/repl-manager.ts:341`; race semantics at `/home/ubuntu/prime-agent-ts/packages/coding-agent/src/core/kernel/shared.ts:217-229`), so the pending startup rejects promptly instead of completing; the not-yet-running kernel skips the snapshot flush (`if (!this.options.snapshot || !this.isRunning) return;` — `repl-manager.ts:1754-1756`) and the protocol shutdown (`protocolShutdownAvailable = this.state === "running"` — `repl-manager.ts:1496`); a startup that had not spawned yet never spawns (`if (startupSignal.aborted) throw ... "Kernel provisioner disposed before start"` — `ipython.ts:551-553`; post-venv bail: "Kernel was disposed during startup" — `repl-manager.ts:370-372`). So a mid-boot old kernel is torn down fast; the teardown does not wait for a cold venv to finish materializing.

---

## Q3. PREWARM SEMANTICS

**Answer: prewarm fires at session-create time inside `_buildRuntime`, is strictly background (`void ... .catch(() => {})`, never awaited), and YES — it fires on replacement sessions too, because a replacement constructs a fresh `AgentSession` whose constructor calls `_buildRuntime`.**

- Call site: `if ((this._prewarmIpythonKernel || hasSnapshot) && this.getActiveToolNames().includes("ipython")) { this._ipythonKernelProvisioner?.prewarm(); }` — `/home/ubuntu/prime-agent-ts/packages/coding-agent/src/core/agent-session.ts:10906-10908`, with the intent comment at `agent-session.ts:10900-10903`; `hasSnapshot` is checked via `existsSync(snapshotPathIn(...))` — `agent-session.ts:10904-10905`.
- Fire-and-forget: `prewarm(): void { void this.ensure().catch(() => {}); }` — `/home/ubuntu/prime-agent-ts/packages/coding-agent/src/core/tools/ipython.ts:385-388` ("Start the kernel in the background. Failures are swallowed here and surface on the next ensure().").
- Config gate: `_prewarmIpythonKernel = (config.prewarmIpythonKernel ?? false) && this._rlmDepth === 0;` — `/home/ubuntu/prime-agent-ts/packages/coding-agent/src/core/agent-session.ts:1816`. The production runtime factory hard-enables it for main agents: "Main agents boot their kernel in the background at session creation; subagent sessions (rlmDepth > 0) keep the lazy first-call start." + `prewarmIpythonKernel: true` — `/home/ubuntu/prime-agent-ts/packages/coding-agent/src/main.ts:773-775`; passed through `createAgentSessionFromServices` (`/home/ubuntu/prime-agent-ts/packages/coding-agent/src/core/agent-session-services.ts:291`) into `new AgentSession({...})` (`/home/ubuntu/prime-agent-ts/packages/coding-agent/src/core/sdk.ts:360`, `:390`). Every replacement build goes through this factory (`this.createRuntime` — `agent-session-runtime.ts:478`, factory field at `agent-session-runtime.ts:77-80`), so replacement sessions (rlmDepth 0) prewarm.
- Because it is background, the first `ipython` tool call JOINS the in-flight startup rather than restarting: `ensure()` replays the current stage to late progress listeners and returns the same `managerPromise` — `/home/ubuntu/prime-agent-ts/packages/coding-agent/src/core/tools/ipython.ts:440-483` (join/replay at `ipython.ts:456-460`, single-flight memo at `ipython.ts:462-478`, shared-promise return at `ipython.ts:482`).

---

## Q4. THE SECOND-KERNEL COST (warm venv)

A second kernel boot in TS (`prewarm()` → `ensure()` → `startKernel()` — `/home/ubuntu/prime-agent-ts/packages/coding-agent/src/core/tools/ipython.ts:499-602`) consists of, with a warm shared venv:

1. **Venv-ready probe** (per boot, not memoized on success): `m.start()` → `doStart` resolves the interpreter via `ensureKernelPython({ pythonSkills, onProgress })` — `/home/ubuntu/prime-agent-ts/packages/coding-agent/src/core/kernel/repl-manager.ts:355-362`; the probe is `hasPrimeAgentRuntime(python)` — a real `python -c RUNTIME_READY_CHECK` subprocess (import + assertion battery over the `rlm` runtime API — `/home/ubuntu/prime-agent-ts/packages/coding-agent/src/core/kernel/bootstrap.ts:98`, `:457-465`) plus the on-disk marker check `bootstrapVersionCurrent` (`bootstrap.ts:666-685`, read at `bootstrap.ts:608-645`), combined in `kernelReady`/`kernelBaseReady` — `bootstrap.ts:923-941`. A warm venv returns after one short python import probe (sub-second class; no uv/pip work).
2. **Process spawn**: `spawnHidden(python, ["-m", "rlm.repl"], {...})` — `/home/ubuntu/prime-agent-ts/packages/coding-agent/src/core/kernel/repl-manager.ts:374-386` — a second python process, per session (Q1).
3. **Ready handshake**: `await this.waitForReady(child)` over JSON lines on stdout (`repl-manager.ts:393`); the `"ready"` event carries the protocol version and resolves the deferred (`repl-manager.ts:864-866`); capped by `READY_TIMEOUT_MS = 30_000` — `repl-manager.ts:67` (wait implementation `repl-manager.ts:776-813`).
4. **Namespace restore (only if the session has a snapshot — e.g. fork/switch of a snapshotted session)**: `m.restoreState()` is awaited inside the boot permit path — `/home/ubuntu/prime-agent-ts/packages/coding-agent/src/core/tools/ipython.ts:560-566`.
5. **Bootstrap cell**: `const bootstrap = await m.execute(bootstrapCode, ...)` — `/home/ubuntu/prime-agent-ts/packages/coding-agent/src/core/tools/ipython.ts:568-576`; the cell imports `rlm`, `rlm.mcp`, and every installed Python skill (`RLM_BOOTSTRAP_HEADER_CODE`/`RLM_BOOTSTRAP_RUNTIME_CODE` and the skill-import loop — `ipython.ts:25-69`, `:103-131`).
6. Boot concurrency is gated by a process-wide semaphore `withKernelBootPermit` around only `m.start()` — `/home/ubuntu/prime-agent-ts/packages/coding-agent/src/core/tools/ipython.ts:550-556`; default permits `Math.min(16, Math.max(4, cpus*2))` — `/home/ubuntu/prime-agent-ts/packages/coding-agent/src/core/kernel/boot-gate.ts:6`, env-tunable and clamped at 64 (`boot-gate.ts:9-23`, `:27-34`).

**Probe memoization:** there is NO success memo of the venv-ready probe. Per-process there is only an in-flight single-slot dedup: `ensureKernelPython` joins `inFlightEnsureKernelPython` when the skill-set key matches, and clears the slot when the promise settles — `/home/ubuntu/prime-agent-ts/packages/coding-agent/src/core/kernel/bootstrap.ts:1027-1036` (slot declared at `bootstrap.ts:109`). So a second boot after the first has COMPLETED re-runs the `python -c RUNTIME_READY_CHECK` probe and marker read; a second boot while the first is still resolving JOINS it. On disk, the memo is the venv itself plus the `.bootstrap-version` marker (`bootstrap.ts:99`, `:687-705`), which makes the probe cheap but does not skip it. Per-manager, the resolved interpreter is cached for restarts of the SAME manager: `this.options.python = python;` — `repl-manager.ts:362` — but each session has its own manager (Q1).

**Cold venv (first boot still materializing the venv):** the ensure path prints "› setting up python kernel (one-time, ~30s)…" — `bootstrap.ts:1010` — and pays `uv python install` + `uv venv` + `uv pip install` of the runtime, the state-snapshot package, and default extras, then a skill sync — `/home/ubuntu/prime-agent-ts/packages/coding-agent/src/core/kernel/bootstrap.ts:808-838` (`bootstrapVenv`) and `:840-921` (`syncPythonSkills`), guarded by the on-disk `.bootstrap.lock` (Q5). A `PRIME_AGENT_KERNEL_PYTHON` override skips the venv entirely — `bootstrap.ts:951-1018` (`ensureKernelPythonUncached`).

---

## Q5. COLD-VENV CONTENTION

**Answer: same-process concurrent boots do NOT both build the venv. They join the in-flight `ensureKernelPython` promise when the python-skill key matches; on key mismatch (or cross-process), they contend on the on-disk `.bootstrap.lock` directory lock, and the loser re-checks readiness after acquiring it, so only one venv build runs. The second KERNEL process still spawns afterwards — the venv is deduped, the kernel is not.**

Citations:

- In-flight join (per process, same key): `export function ensureKernelPython(...)` — `/home/ubuntu/prime-agent-ts/packages/coding-agent/src/core/kernel/bootstrap.ts:1027-1036`: `if (inFlightEnsureKernelPython?.key === key) return inFlightEnsureKernelPython.promise;` (`bootstrap.ts:1030`); key = normalized python-skill set (`ensureKernelPythonKey` — `bootstrap.ts:377-385`). The slot is cleared on settle (`bootstrap.ts:1033-1034`).
- Lock (cross-call, cross-process): `const releaseLock = await acquireBootstrapLock(venv);` — `bootstrap.ts:1001`; `acquireBootstrapLock` loops on `tryAcquireDirLock` with a stale-holder check and retries every `BOOTSTRAP_LOCK_RETRY_MS = 100` ms — `bootstrap.ts:510-524`, constants at `bootstrap.ts:101-102`, `:107` (lock dir `<venv>.bootstrap.lock` next to the venv, `bootstrap.ts:497-498`).
- Double-check after acquiring: `if (await readyForCaller()) return python;` — `bootstrap.ts:1003` — so the lock loser finds the venv ready and does not rebuild. Pre-lock fast path: `if (await readyForCaller()) return python;` — `bootstrap.ts:999`; probe definitions `bootstrap.ts:995-998`, `:923-941`.
- Replacement-during-cold-boot, end to end: the old session's still-booting kernel is aborted fast by the awaited teardown (Q2 special case: `ipython.ts:414`, `repl-manager.ts:341`, `:1754-1756`, `:370-372`), the venv ensure keeps running in the background, and the NEW session's background prewarm calls `ensureKernelPython` which JOINS that in-flight promise (`bootstrap.ts:1030`). No second venv build, no lock wait, and the RPC response is not blocked by any of it.

---

## Q6. VERDICT

**Does the TS new_session/switch_session/fork response wall ever include kernel boot cost? No — not the second kernel's boot.** Evidence chain:

1. The response is written only after `await handleCommand(command)` resolves — `/home/ubuntu/prime-agent-ts/packages/coding-agent/src/modes/rpc/rpc-mode.ts:480`.
2. `newSession`/`switchSession`/`fork` await `teardownForReplacement`, `buildAndApplyReplacement`, and `finishSessionReplacement` — `/home/ubuntu/prime-agent-ts/packages/coding-agent/src/core/agent-session-runtime.ts:474-496`, `:431-449`, `:545-563`, `:574-592`, `:607-625`.
3. None of those awaits the new session's kernel: `buildAndApplyReplacement` constructs the new `AgentSession` (`agent-session-runtime.ts:251-263` → `sdk.ts:360-394`), whose constructor fires `prewarm()` synchronously as a `void` background promise (`agent-session.ts:1867-1870` → `:10906-10908` → `ipython.ts:385-388`). `finishSessionReplacement` only rebinds and emits (`agent-session-runtime.ts:397-405`; `in-process-agent-connection.ts:98-108`).
4. What IS in the wall on the kernel axis: the OLD kernel's awaited dispose — final snapshot flush + host-request drain + graceful shutdown (`agent-session-runtime.ts:208` → `agent-session.ts:5108` → `ipython.ts:408-421` → `repl-manager.ts:1491-1534`), each 5 s-capped (`shared.ts:6-9`). If the old kernel is mid-boot, that boot is aborted rather than completed (Q2 special case), so even cold, the wall does not wait for a boot.

**Is TS's second kernel per-session (same shape as the Rust port), or reused across generations? Per-session — the same shape.** A replacement generation builds a fresh `AgentSession` with its own `IpythonKernelProvisioner` (`agent-session.ts:1691`, `:10810-10825`, `:10828`) and its own kernel process (`repl-manager.ts:374`); the old kernel is disposed during the swap (`agent-session.ts:5108`), after which the new kernel boots in the background. No kernel process, provisioner, or snapshot is handed over between generations; only the venv (`bootstrap.ts:387-390`), the boot semaphore (`boot-gate.ts:27-34`), and the in-flight venv-ensure promise (`bootstrap.ts:109`, `:1027-1036`) are shared. The one cross-generation ordering mechanism that exists — `readyGate: previousDispose` (`agent-session.ts:10804`, `:10818`) — applies only to same-session `/reload` rebuilds, not to replacement generations.

Implication for the Rust observation (context, not a Rust claim): if the Rust `replace_locked` path mirrors these TS semantics, a 10.8 s cold `new_session` wall cannot be explained by the second kernel's boot being awaited — in TS the analogous wall contains old-kernel teardown (bounded ~5 s per stage) plus extension events, and the second boot is background. Whether the Rust port actually awaits its prewarm is out of scope here ("not determinable from code" for the Rust side from this tree).

---

## Assumptions and notes

- "Replacement generation" = the `AgentSession` produced by `buildAndApplyReplacement` in `newSession`/`switchSession`/`fork`/`importFromJsonl`. Subagent runtimes (`createRlmSubagentRuntime` — `agent-session-runtime.ts:316-377`) are separate sessions with their own kernels and do NOT prewarm (`main.ts:773-775` + `agent-session.ts:1816`).
- The `IpythonToolOptions.provisioner` sharing hook (`ipython.ts:349-350`) exists but no in-tree caller shares a provisioner across sessions; per-session ownership is the observed production wiring (Q1 citations).
- Quantified timing of a warm TS second boot is not in the code; the code gives only the structure (probe + spawn + handshake + cells) and the 30 s ready cap and 5 s shutdown/snapshot caps. Actual durations: "not determinable from code".
- File line numbers refer to the tree as read on 2026-09-27; `/home/ubuntu/prime-agent-ts` was not modified.
