# Prime Agent (TypeScript) — product adapter

Wire-compatible with the Rust adapter (same daemon socket contract, same
trial isolation); subclasses it and overrides the binary source.

## What it needs
- The official compiled beta binary: `~/.local/share/prime-agent/bin/prime-agent`
  (install.sh layout; revision pinned in `product.yaml`)
- The uv toolchain (kernel venv builder), same as rust
- A kernel venv with the daemon's own `.bootstrap-version` identity marker

## Where auth comes from
Same as rust: `~/.prime/config.json` (PRIME_API_KEY) + `~/.prime/agent/auth.json`
(preprovisioned Prime auth); traffic routes to the offline mock.

## First-run dialogs (config, in product.yaml)
- "Share agent traces with Prime Intellect?" -> `down, enter` (Not now)
- Same fix-tracker note as rust: the trace-default PR removes the modal at the
  source; the config entry stays (harmless when the dialog is gone).

## Return-user consent baseline
Inherited from the rust adapter: the template seeds the pinned return-user
settings.json (onboardingShown / agentTraces.enabled=false /
telemetry.noticeShown — verified against this binary's own revision
acc5bc0) at both product-visible locations; a sheet in a measured launch
is a baseline breach and invalidates the trial (see the rust README).

## Known quirks — the fix classes hit here
- **TUI hard-wrapping breaks naive text matching**: the campaign caught the TS
  TUI hard-wrapping dialog text at arbitrary columns (d48a5d1). Generalized
  fix: all matchers whitespace-normalize the screen.
- **Daemons wipe venvs lacking their identity marker**: same class as rust —
  `warm_kernels` waits for the daemon's own build, never pre-builds.
- **Kernel bootstrap pauses input**: same class as rust — settle/warm before
  every measured wave.
