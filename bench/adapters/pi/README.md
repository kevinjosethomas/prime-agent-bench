# Pi Mono — product adapter

## What it needs
- The pinned source checkout: `~/bench/repos/pi-mono` (node 22 runs the
  bundled `packages/coding-agent/dist/bundle/cli.js`; revision pinned in
  `product.yaml`)
- npm package `@mariozechner/pi-coding-agent` at the pinned version

## Where auth comes from
- `~/.prime/agent/auth.json` (preprovisioned Prime auth copied into the
  trial agent dir) — copied auth keeps pi authenticated with NO onboarding
- The launch argv pins `--provider prime-inference --model mock-1`: traffic
  routes to the offline mock. Without the flags pi selects Anthropic
  subscription auth from the copied auth.json = PAID traffic — the flag set
  is load-bearing.

## First-run dialogs (config, in product.yaml)
- None at the pinned revision — the provider/model flags settle it
  (`first_run_dialogs: []`). A future dialog = one config entry.

## Known quirks — the fix classes hit here
- **Copied auth selects the wrong provider silently**: the campaign caught pi
  picking Anthropic subscription auth from the copied auth.json (paid
  traffic). Generalized fix: the argv pins provider+model explicitly; the
  README documents that the flags are load-bearing.
- **Node-only launch**: pi is a node bundle — `node` must be on PATH (the
  bootstrap installs node 22).


## Product naming (the "pi mono" question, 2026-10-02)

The driver IS "Pi Mono": it has always run the pi-mono monorepo's
coding-agent (`packages/coding-agent/dist/bundle/cli.js`, npm
`@earendil-works/pi-coding-agent`, first `@mariozechner/pi-coding-agent`
before the package moved). There is no distinct "pi" product or mode vs
"pi mono" in this harness — the repo's other packages (agent, tui,
codemode, ...) are libraries/subagents of the same monorepo, not separate
CLIs we measure. The publishable suite therefore keeps this driver as
the one `pi` product, display name "Pi Mono".
