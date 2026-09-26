# Five-Product Benchmark Campaign — Latest Versions, Authed (2026-09-26)

**Campaign**: cmp5-20260926 — Prime Agent Rust vs Prime Agent TS vs Claude Code vs Codex CLI vs Pi Mono.
**Layout**: one Prime VM sandbox (ubuntu:22.04, 4 CPU / 8 GB / 60 GB) per product; every product ran its
full benchmark set sequentially inside its own sandbox (fairness by identical hardware + the same
harness); the five sandboxes ran in parallel. 10 measured trials per benchmark per product
(install_disk is per-product footprint accounting), plus a 20-trial A/A calibration pass per product on
`compare.cold_start` **before** any measured trial.
**Authed state**: every product started in its authenticated state — auth files shipped into each
sandbox before any launch, onboarding/consent dialogs answered during the settle/prepass, never during
measurement. `compare.msg_send` used **real API calls** for every product (50 paid calls + the
calibration/debug probes; no paid inference for any startup/calibration benchmark).
**Environment**: raw-PTY driver (pyte screen emulation, monotonic controller-side clocks, per-trial
isolated homes, per-trial process sweep, load gates); scrubbed env; ambiguous-terminal path (the Rust
250ms kitty probe on the ambiguous path is documented in the harness's `tui-keyboard-probe` notes).
Reference calibration (fixed CPU loop per sandbox): rust 1293.6ms, ts ~1312ms, claude 1233.0ms,
codex 1280ms, pi 1273.5ms — all within 5% of the median (~1284ms), no sandbox replaced.

## Headline table — p50 / p75, 10 trials per cell, **fastest bolded**

| benchmark (metric) | Prime Agent Rust | Prime Agent TS | Claude Code | Codex CLI | Pi Mono |
|---|---|---|---|---|---|
| compare.cold_start (launch→ready ms) | 293.3 / 294.4 | 584.9 / 603.9 | 311.2 / 317.9 | 295.8 / 296.1 | **242.7** / 244.8 |
| compare.warm_start (launch→ready ms) | 276.7 / 281.9 | 427.9 / 430.6 | 312.0 / 321.0 | 297.4 / 299.7 | **178.1** / 186.0 |
| compare.msg_send (Enter→ack ms) | 1.4 / 9.7 | 2.0 / 2.2 | 45.5 / 46.8 | **0.2** / 0.6 | 1.1 / 1.1 |
| compare.msg_send (Enter→reply ms) | 2,127.4 / 2,243.1 | **2,044.1** / 2,631.2 | 5,402.9 / 5,431.1 | 2,714.3 / 3,028.5 | 2,709.4 / 3,067.9 |
| compare.scroll_typing (typing ms p50) | **1.0** / 1.1 | — | — | — | — |
| compare.memory_idle_load (RSS MB (10MiB session)) | **554.9** / 581.0 | 1,130.0 / 1,138.2 | — | — | — |
| compare.install_disk (installed bytes) | 206,668,003 / 206,668,003 | **172,192,855** / 172,192,855 | 483,322,595 / 483,322,595 | 391,253,952 / 391,253,952 | 462,249,835 / 462,249,835 |
| session.cold_open_10mib (launch→ready ms) | 22,533.8 / 22,927.0 | **721.5** / 742.4 | — | — | — |
| session.agent_view_roundtrip (chat→agents view ms) | 118.8 / 118.9 | **69.2** / 69.9 | — | — | — |
| daemon.boot (spawn→accept ms) | **30.9** / 30.9 | 113.1 / 113.7 | — | — | — |
(rows show **p50 / p75**; n shown in the per-cell denominators below. `—` = the harness's §F comparability
rule: the product has no native 10MiB Prime-session fixture (session.*, scroll/memory) or no resident
daemon (daemon.boot) — status rows, never fake-measured.)

**Rust vs TS (the port's headline deltas):** cold start 293ms vs 585ms (rust **1.99× faster**), warm start
277ms vs 428ms (rust **1.55× faster**), daemon boot 30.9ms vs 113.1ms (rust **3.66× faster**), memory with
the 10MiB session 555MB vs 1130MB (rust **2.04× less**), on-disk 206.7MB vs 172.2MB (rust +20%),
msg reply 2127ms vs 2044ms (ts 3.9% faster), 10MiB cold open 22.5s vs 0.72s (ts **31× faster** — the
render-volume path), agents-view round trip 118.8ms vs 69.2ms (ts **1.72× faster**).

## Version / binary evidence (versions.json, machine-collected per sandbox)

| product | version | revision / source | binary sha256 | bytes |
|---|---|---|---|---|
| Prime Agent Rust | 0.1.0-continuous.59a9c658 | rust branch, continuous run 36193301325 (install-rust.sh, latest) | 6f10ea7a56749bf5d11786b30c2d39bf81e6cc5819798e5d0a647ddca8a0c370 (payload) | 204,860,672 |
| Prime Agent TS | 0.9.6 (official stable) | GitHub release v0.9.6 (install.sh layout) | 69e5bb9173d0ed6df270aa59bb9919a05a2dc7076af6f830254820735bc996fb | 163,595,464 |
| Claude Code | 2.1.283 | npm @anthropic-ai/claude-code@latest | 1859583ce32920595c61ef868bee52e1b1594f7486db209935e01f1e5e804ae2 | — |
| Codex CLI | 0.157.0 → 0.157.1 (auto-updated mid-campaign; see caveats) | npm @openai/codex@latest | 61b0194f3bb6534439c8d26a3ed57d0805f84b884588b761795323eeb92fcf70 | — |
| Pi Mono | 0.87.1 @ d6af72e | github.com/badlogic/pi-mono (→ earendil-works/pi), built from source @ HEAD | e79626f2dd6f94aa45d30f3fa63cd84319a6eefcd150b353cfaf274366926774 (bundle cli.js) | — |

## msg_send routing (REAL API — the reply is the live model's answer, model recorded per row)

| product | provider / model | settle p50 (Enter→reply rendered) |
|---|---|---|
| rust | prime-inference/openai/gpt-6-sol | 2127.4 ms |
| ts | prime-inference/openai/gpt-6-sol | 2044.1 ms |
| claude | anthropic/claude-fable-5 (Prime Inference's Anthropic-protocol endpoint) | 5402.9 ms |
| codex | openai/gpt-5.6-sol (its api-key auth mode) | 2714.3 ms |
| pi | openai-codex/gpt-6-sol (its own OAuth) | 2709.4 ms |

The settle is certified semantically: the prompt demands one fixed sentinel token
(`BENCH-OK-7f3d9a`, split structurally so the typed prompt never contains it contiguously), and the
settle fires only when that token renders in a fresh line without the prompt's stem words — screen
growth alone never certifies (the captured codex 401 error render from the 2026-09-24 campaign stays
failed evidence under this detector). Every msg_send row carries `msg_routing: real-api`,
`real_api_certified: true`, and the model it routed to.

## A/A calibration (20 trials per product on compare.cold_start, halves-interleaved)

| product | half-A p50 | half-B p50 | spread | gate (<10%) |
|---|---|---|---|---|
| rust | 292.5 | 294.7 | 0.8% | PASS |
| ts | 589.3 | 592.0 | 0.5% | PASS |
| claude | 331.6 | 316.2 | 4.9% | PASS |
| codex | 296.6 | 295.4 | 0.4% | PASS |
| pi | 238.1 | 243.9 | 2.4% | PASS |

## Excluded / invalid trials (the validity gate's report — nothing silently dropped)

| benchmark | product | rows | reason |
|---|---|---|---|
| compare.scroll_typing | ts | 10 | `typing_ok=false` ×9 + `fixture_not_confirmed` ×1 — the TS TUI drops keys under the raw-PTY driver while typing into the 10MiB session (the known 2026-09-24 limitation; ts 0.9.6 still reproduces it here — its msg_send typing works, the loaded-session typing does not) |
| compare.msg_send | codex | 1 | `real_api_regime` — one uncertified row from a debug wave (login-screen era, before the api-key route); kept as evidence, never ranked |
| compare.memory_idle_load | ts | 2 | `fixture_not_confirmed` — the resumed-fixture sentinel evidence missing on 2 of 10 rows (8 valid rows remain) |
| session.cold_open_10mib | ts | 3 | `fixture_not_confirmed` (7 valid rows remain) |
| session.agent_view_roundtrip | ts | 3 | `fixture_not_confirmed` (7 valid rows remain) |

Status rows (never measured, never numeric): claude/codex/pi on session.* (no native 10MiB
Prime-session fixture, spec §F), claude/codex/pi on compare.scroll_typing + compare.memory_idle_load
(same fixture rule), claude/codex/pi on daemon.boot (no resident daemon).

## Caveats

- **Claude auth**: this node has no Claude OAuth state. Claude Code ran against Prime Inference's
  Anthropic-protocol endpoint (`api.pinference.ai/api`, `ANTHROPIC_AUTH_TOKEN` = the Prime API key +
  `X-Prime-Team-ID` team-billing header via `ANTHROPIC_CUSTOM_HEADERS`, model
  `anthropic/claude-fable-5`) — verified live: the endpoint speaks the Anthropic Messages wire format
  and the team carries the billing (the personal balance is empty). This is real inference, real API,
  one extra network hop vs Anthropic's own endpoint.
- **Codex auth**: the ChatGPT OAuth **cannot survive isolated trial homes** — its refresh token is
  single-use, so the first refresh rotates the family and every copied home (template included) answers
  "refresh token was already used" with the login screen. Proven live: 10/10 copied-token trials sat at
  the login prompt. Codex's own api-key auth mode (its login-menu option 3 format) has no rotation and
  was used for msg_send, pinned to `gpt-5.6-sol` — the newest model the key actually serves
  (`/v1/responses` 404s on the codex-family models and on gpt-6-sol; verified live). Every key-served
  model opens the "Meet GPT-6 ..." migration NUX on each launch; the harness answers it inline
  ("use existing model") with the dismissal time excluded from every published metric.
- **Codex auto-update**: codex self-updated 0.157.0 → 0.157.1 mid-campaign. Startup benchmarks were
  measured on 0.157.0; msg_send on 0.157.1 (each wave's versions.json records the version it measured —
  per-wave attribution preserved in the raw rows).
- **Warm-start memory**: `compare.memory_idle_load` follows the TUI process tree (TUI→daemon→worker→
  kernel) on cold starts; the daemon itself is in that tree for rust/ts. Warm-start daemons are not
  part of the cold-start tree; the `rss_settled_mb` values above are the loaded-session tree, not
  TUI-only.
- **rust erase residue**: the readiness probe leaves up to `len(PROBE_TOKEN)-1` chars in the editor
  before the msg prompt is typed (the harness's known probe-retry buffering); the submitted prompt can
  carry a 3-char prefix. Same treatment for every product; models comply regardless.
- **Sandbox spec**: 4 CPU / 8 GB VMs per the campaign brief (the harness default for
  `session.cold_open_10mib` was 12 GB in per-benchmark-type sandboxes; this campaign ran one sandbox
  per product at the brief's 8 GB — no OOM, no anomalies).
- **No paid inference** for any startup/calibration benchmark: they run mock-routed
  (`models.json`/`ANTHROPIC_BASE_URL` at the in-sandbox offline provider); only `compare.msg_send`
  billed real inference (10 trials × 5 products + a handful of debug/calibration probes).

## Raw data

- On the controller (this machine): `~/bench-cmp5/results-campaign-20260925/merged-results/`
  (per-benchmark `trials-*.jsonl`, `versions.json`, `summary.json`, `summary.md`,
  `summary.notion.json`, `noop-control.json`, `settle.jsonl`) + the per-wave collections in
  `~/bench-cmp5/results-campaign-20260925/sandbox-runs/`.
- Pushed to git: this record directory (`records/campaigns/cmp5-20260926-*/`) on the `hillclimb` branch
  of `kevinjosethomas/prime-agent-bench`.
- Harness: `campaign-cmp5` branch (the campaign's harness changes: per-benchmark msg routing,
  sentinel-certified real-api settle, authed template homes, the codex/pi/claude routing adapters),
  merged into `hillclimb`.

## Sandbox provenance

| product | sandbox | spec | reference |
|---|---|---|---|
| rust | bench-camp-rust (btbt505aclb0d0pujxfri3lf) | 4c/8GB/60GB ubuntu:22.04 VM | 1293.6 ms |
| ts | bench-camp-ts (df787eb4bq9p45bainl3lysr) | 4c/8GB/60GB ubuntu:22.04 VM | ~1312 ms |
| claude | bench-camp-claude (ffm7eo6q05z7zqaw5kawp1s0) | 4c/8GB/60GB ubuntu:22.04 VM | 1233.0 ms |
| codex | bench-camp-codex (j1tq8cp2oqwag3sstp98q0hc) | 4c/8GB/60GB ubuntu:22.04 VM | 1280 ms |
| pi | bench-camp-pi (yc18102or7zza9k2ca2zvlrp) | 4c/8GB/60GB ubuntu:22.04 VM | 1273.5 ms |
