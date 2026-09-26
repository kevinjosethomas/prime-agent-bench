# cmp5-20260926 — operational notes

Timeline (UTC, 2026-09-25/26): installs 21:30-22:15 (latest versions), harness changes +
local validation 22:15-00:45, sandbox provisioning 00:45-02:00, calibration 02:00-02:15,
measured waves 02:05-04:15, analysis + report 04:15-05:00.

## Products (latest at campaign time)
- rust: install-rust.sh -> continuous run 36193301325 @ 59a9c658 (campaign-private prefix
  ~/bench-cmp5/pa-rust-prefix; the shared ~/.local payload is another session's runtime and was
  never touched)
- ts: official v0.9.6 release tarball installed in the install.sh layout
- claude: npm @anthropic-ai/claude-code 2.1.283 (postinstall allowed)
- codex: npm @openai/codex 0.157.0 (self-updated to 0.157.1 mid-campaign)
- pi: badlogic/pi-mono @ d6af72e (0.87.1), npm install + build in ~/bench-cmp5/repos/pi-mono

## Harness changes on campaign-cmp5 (all tests green, 128 pass)
1. per-benchmark msg routing (benchmarks.<name>.msg_routing) resolved per trial before any
   launch; adapters apply it in apply_routing (new ABC hook).
2. msg_send real-api: sentinel-certified settle (prompt demands one fixed token, split
   structurally so the typed prompt never contains it contiguously; certifying lines must be
   fresh + prompt-stem-free; growth-only never certifies). real_api_certified gates the rankings.
3. authed template homes actually reach the trial (new_trial copied template/ AS home, nesting
   home/home — the captured codex login screen was exactly this; fixed to template/home).
4. copy_tree/rsync skip sockets+fifos (codex's app-server daemon-updater.sock killed copytree).
5. rust/ts real-api: PRIME_TEAM_ID env + pinned provider/model/thinking + allowedModels pinned
   (the daemon blocks unallowed models, no fallback; the live node settings carry other
   sessions' allowlists).
6. codex: --no-daemon (107-char UNIX socket path limit), api-key auth mode (OAuth refresh
   rotation is incompatible with isolated trial homes — proven), KEY_MODEL gpt-5.6-sol (the
   codex family 404s under an API key; every key-served model opens a per-launch migration NUX —
   answered inline with dismissal time excluded), bubblewrap installed (its warning toast
   swallows keys mid-trial).
7. pi: OAuth-only trial auth (its WS retry fallback sends other entries' api keys to the
   ChatGPT backend, which rejects them), vendor payload path mirrors the controller tree.
8. msg_send: post-readiness dialog dismissal before typing; dropped prompt keys fail loudly.
9. results_dir expands ~ (a configured ~/... dir previously created a literal ./~ tree).

## Race found and fixed in provisioning
harness_bundle() tars vendor/ while a concurrent vendor build rewrites products.tar.gz ->
bundle tar fails. Fixed by per-product bundle dirs (rsync of the harness + one payload each).

## Sandbox reference calibration
1233-1312ms across the five VMs (median ~1284) — comparable; no replacement needed.

## Concurrent-work note
The devbox hosts sibling fleet sessions (hillclimb lane + a mission-daemon sharing the glm-5.3-fast
quota). This campaign ran from a dedicated git worktree (~/prime-agent-bench-cmp5, branch
campaign-cmp5) with its own bench root (~/bench-cmp5) — no shared-state writes except the global
npm installs (claude/codex) and the shared auth sources, which are read-only here.
