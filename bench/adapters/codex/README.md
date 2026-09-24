# Codex CLI — product adapter

## What it needs
- npm-installed CLI: `/usr/bin/codex` -> `/usr/lib/node_modules/@openai`
  (node 22; installed by `vendor/bootstrap.sh`)
- The FULL `~/.codex` device state (auth.json, config.toml, installation_id,
  version.json, the sqlite state) — codex 0.156 boots to the login menu
  without the device identity

## Where auth comes from
- The node's real ChatGPT OAuth state, copied with the device identity
- **`auth_limited: true`** — copied tokens do NOT authenticate a copied home:
  the settle walk types a dummy API key (menu option 3) to reach the settled
  interactive baseline. Real-API msg_send needs Kevin's call (real key /
  device-code login / node-side run; the $10 budget covers it).

## Message routing (`msg_routing: real-api`)
- codex 0.156 rejects the mock provider's chat wire_api, so submitted
  messages hit the live API — and 401 under the settled dummy key.
- msg_send therefore measures only the submit-ack for codex; no settle
  is attempted (screen growth certified the 401 error render as a
  "settle" once — that detector is gone). The row records
  `msg_routing: real-api` and the result-validity gate keeps
  cross-regime values out of the rankings.
- Flip to `msg_routing: mock` when a codex accepts the mock wire or real
  auth is provisioned; comparable settles resume with no scenario edit.

## First-run dialogs (config, in product.yaml)
- "3. Provide your own API key" -> `3` (login menu; the copied OAuth never
  authenticates a copied home)
- "Paste or type your API key" -> literal `sk-bench-dummy-not-real` + `enter`
- "Press enter to continue" -> `enter`
- "Trust and continue" -> `enter` (folder trust)

## Known quirks — the fix classes hit here
- **Copied auth tokens do not transfer across copied homes**: the definitive
  codex quirk. Generalized fix: `auth_limited` in the version evidence, the
  dummy-key settle as the baseline state, and the FULL device state vendored.
- **Onboarding dialogs reappear on copied homes**: walked in-place via the
  prepass (`needs_prepass: true`).
- **New CLI-flag argv can break the second launch** (codex flag changes):
  the adapter keeps the bare `codex` argv; a flag change upstream = one
  `product.yaml`/adapter edit, found by `bench diagnose codex`.
- **TUI hard-wrapping breaks naive text matching**: all markers match the
  whitespace-normalized screen.
