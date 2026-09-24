# Prime Agent (Rust) — product adapter

## What it needs
- The pinned release binary: `~/bench/repos/prime-agent-rust/target/release/prime-agent`
  (from-source `cargo --release` build of `origin/rust`; revision pinned in `product.yaml`)
- `prime-agent-runtime/` next to the binary (the daemon builds the kernel venv from it)
- The uv toolchain (`~/.local/bin/uv`, `~/.local/share/uv`) — the kernel venv builder
- A kernel venv that carries the daemon's OWN `.bootstrap-version` identity marker

## Where auth comes from
- `~/.prime/config.json` — the `PRIME_API_KEY` used in the trial env
- `~/.prime/agent/auth.json` — preprovisioned Prime auth copied into every trial agent dir
- Model traffic routes to the offline mock (`models.json` written per trial); no paid inference

## First-run dialogs (config, in product.yaml)
- "Share agent traces with Prime Intellect?" -> `down, enter` (Not now)
- **Fix tracker (product side):** the trace-sharing modal disappears once the
  trace-default PR merges (the setting is pre-configured on install and the
  dialog never shows). The config entry stays anyway — harmless when the dialog
  is gone, and other products still need theirs.

## Known quirks — the fix classes hit here
- **TUI hard-wrapping breaks naive text matching** (rust + ts): dialog markers
  match the whitespace-normalized screen, never raw rows. Generalized fix:
  every matcher in `drive_to_ready` normalizes whitespace — new dialogs inherit it.
- **Daemons wipe venvs lacking their bootstrap identity marker** (rust + ts):
  a harness-pre-built kernel venv has no `.bootstrap-version`, so the daemon
  wipes and rebuilds it mid-measurement. Generalized fix: `warm_kernels` NEVER
  pre-builds; it launches once and waits for the daemon's own build (marker +
  `import rlm.repl`), so no measured trial races a rebuild.
- **Kernel bootstrap pauses input** (rust + ts): first launch against a cold
  `PRIME_AGENT_KERNEL_VENV` stalls input for minutes. Generalized fix: the
  settle/warm pass before every measured wave (`bench sandbox setup` runs it;
  `bench run --sandbox` re-verifies — both idempotent).
- **Mock SSE framing must be spec-compliant**: `data:` prefix frames,
  `Connection: close`, non-stream JSON branches. Generalized fix: the mock
  serves stream and non-stream correctly for every route.
