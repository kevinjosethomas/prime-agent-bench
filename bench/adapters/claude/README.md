# Claude Code — product adapter

## What it needs
- npm-installed CLI: `/usr/bin/claude` -> `/usr/lib/node_modules/@anthropic-ai`
  (node 22; installed by `vendor/bootstrap.sh`)
- The node's authenticated `~/.claude` state (settings, trust, credentials)
  minus project data (projects/todos/statsig/shell-snapshots excluded)

## Where auth comes from
- `~/.claude` + `~/.claude.json` copied into the trial home at template build
- The API key is a dummy; `ANTHROPIC_BASE_URL` routes traffic to the offline
  mock — no paid inference, real auth state only for the onboarding walk

## First-run dialogs (config, in product.yaml)
- "1. Auto (match terminal)" -> `enter` (theme picker)
- "Do you want to use this API key?" -> `up, enter` (Yes)
- "Press Enter to continue" -> `enter` (security note)
- "Is this a project you created or one you trust?" -> `down, enter` (workspace trust)
- Trust state is ALSO pre-set per trial (`hasTrustDialogAccepted` in
  `.claude.json` for the work dir) — the dialog config covers fresh states.

## Known quirks — the fix classes hit here
- **Route matching must split query strings**: the mock must answer
  `/v1/messages?beta=true` by path only (raw path+query matching 404s — the
  campaign's claude mock-404 fix). Generalized fix: the mock strips query
  strings before route matching.
- **Onboarding dialogs reappear on copied homes** (claude + codex): dialogs
  are walked IN-PLACE (the prepass) so the settled state bakes into the
  template. Generalized fix: `needs_prepass: true` + dialog config.
- **Mock SSE framing must be spec-compliant**: anthropic-style events carry
  `data:` prefixes and terminate connections cleanly.
- **TUI hard-wrapping breaks naive text matching**: all markers match the
  whitespace-normalized screen.
