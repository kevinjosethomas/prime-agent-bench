# Pi Mono — product adapter

## What it needs
- The pinned source checkout: `~/bench/repos/pi-mono` (node 22 runs the
  bundled `packages/coding-agent/dist/bundle/cli.js`; revision pinned in
  `product.yaml`)
- The pinned source's package version at that revision: `0.87.1` (git
  describe `v0.87.1-16-gb455975`; verified live on the benchmark node:
  `node cli.js --version` -> 0.87.1). The npm package
  `@mariozechner/pi-coding-agent` publishes 0.59-0.73.1 under a different
  version scheme and does NOT correspond to the pinned source;
  `product.yaml install.npm_version` records the SOURCE version — the
  binary is built from the pinned source, never packed from npm
  (`npm pack @mariozechner/pi-coding-agent@0.87.1` 404s: the number is
  the source package version, not a published npm release — do NOT use
  it for `compare.install_disk` on pi; the pi footprint is the
  built-from-source vendor payload, not an npm pack)

## Where auth comes from
- `~/.prime/agent/auth.json` (preprovisioned Prime auth copied into the
  trial agent dir) — copied auth keeps pi authenticated with NO onboarding.
  The copy is CONDITIONAL: in a secret-free sandbox (`/root/.prime` absent)
  `copy_prime_auth` is a no-op, trials run with ZERO auth, and pi still
  boots — `models.json` + the launch flags carry the mock provider/key.
- The launch argv pins `--provider prime-inference --model mock-1`: traffic
  routes to the offline mock. Without the flags pi selects Anthropic
  subscription auth from the copied auth.json = PAID traffic — the flag set
  is load-bearing. Loaded-session scenarios never submit, so no auth is
  exercised there at all.
- `product.yaml` declares the full prime-home credential set as
  `auth_sources` (auth.json + config.json + agent/settings.json), so
  `bench vendor --no-secrets` drops all of it from the payload; the vendor
  builder additionally redacts any undeclared prime-home entry
  (config.json carries the api_key) — a secret-free payload ships binaries,
  never prime-home state.

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

## Loaded-session fixture import (spec §F, native)

Pi's persisted transcript IS the bench session-JSONL schema (pi v3 session
header + `message`/`custom_message` entries with id/parentId — Prime Agent
forked pi), so the vendor-native fixture needs no format translation:

- `prepare_native_fixture` validates the corpus (parseable v3-style session,
  assistant tail row carries the visible suite sentinel), stages a byte copy
  into the trial's `<home>/.pi/agent/sessions/bench-fixture-<sha16>.jsonl`,
  and ensures the recorded session cwd exists (pi otherwise asks an
  interactive "cwd from session file does not exist" continuation prompt —
  the recorded cwd must be real per the fixture reproducibility contract;
  the prompt is also covered as a fallback `first_run_dialogs` entry).
- `argv` resumes it with the native `--session <path>` flag
  (`SessionManager.open` — a direct file path is a first-class resume input
  in the pinned source, v0.87.1-16-gb455975).
- The trial row carries the import evidence under `fixture.native`:
  format/mechanism/path/sha256/bytes/rows/turns/sentinel plus the source
  identity — the semantic workload (rows/turns/bytes/sentinel) is identical
  to the gold fixture by construction (same format, byte copy).
- The TUI appends only to the staged trial copy; the gold fixture file is
  never mutated.

Evidence so far (offline, synthetic data only, no submit, no auth): an
isolated-home PTY run of `pi --session <staged corpus> --provider
prime-inference --model mock-1 ...` with the mock base URL pointed at a
dead port renders the loaded transcript tail (suite sentinel visible on
the reopened UI) and accepts + echoes a typed probe token. The proving
binary was the local `@earendil-works/pi-coding-agent` 0.80.6 fork (the
pinned v0.87.1-16 checkout was not built on this machine); the same proof must
be rerun against the pinned build on the benchmark node/sandbox before
any loaded-session rank is trusted — per-trial sentinel+echo validation
gates that regardless (rows without the live sentinel render are invalid,
never ranked).
