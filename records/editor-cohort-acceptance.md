# Editor cohort acceptance — Claude Code / Codex CLI / Pi Mono (offline lane)

The status ledger for the editor-cohort qualification lane (branch
`editor-preflight-qualification`, off `bench-campaign-corrected` @ 3384d6b).
Scope: the three external editors only. Prime Agent TS/Rust onboarding
(consent dialog, telemetry notice, persisted-consent preseed) is owned by
the bench-consent-restart lane and is NOT tracked here.

## Recorded proofs (product-owned `proofs:` in each product.yaml)

| product | proof | kind | status |
|---|---|---|---|
| pi | `native-session-resume` (v2 corpus, pinned `b455975`, product 0.87.1) | live-function-only | recorded; external artifacts sha256-pinned (see `bench/adapters/pi/proofs/native-resume-2026-09-24.md`) |
| claude | — | — | none recorded (`proofs: []` is the explicit declaration) |
| codex | — | — | none recorded (`proofs: []` is the explicit declaration) |

The pi proof is one sandbox, function-only feasibility: NOT a campaign
trial, NOT a ranking, NOT v3-corpus validation, NOT an adapter capability
at this revision (`resume_fixture_capable` stays False until the
native-fixture lane merges). Its pending list (v3 re-proof once the
corrected campaign's loaded-session paths settle; re-proof after
pi-pin-provenance `d0fa0e6` and the native-fixture/erase lanes land) lives
in the record itself.

## Offline qualification (this lane, committed)

`tests/test_editor_qualification.py` — 13 tests, entirely offline:

- **session**: resume capability is a declared flag, never inferred
  (spec §F); recorded proof scopes disclaim v3 validation and adapter
  capability in writing.
- **editor**: dialog configs are complete (marker + keys per step; pi's
  pinned revision declares the honest no-dialogs state); the harness
  dialog walk settles a PTY-synthetic TUI replaying each product's OWN
  markers and keystroke-resolved keys (a wrong key never advances it) —
  a harness floor, NOT product proof.
- **message**: routing regimes are declared honestly (claude/pi mock with
  pinned argv/env; codex `real-api` with `auth_limited: true` because its
  0.156 rejects the mock wire) — mock is claimed only where it is routed.
- **evidence**: `proof_records()` verifies artifact sha256s when present,
  reports `absent-external` otherwise, and raises on a mismatch (corrupt
  evidence never passes silently).
- **vendor hygiene**: `undeclared_secret_srcs` reports per-scope
  prime-home vendor entries missing from `auth_sources`.

No benchmark 120s deadline is involved anywhere in the offline suite
(bounded 10s/60s timeouts only); the historical Claude/Codex/Pi ~120s
cold-open artifacts are invalid and never ranked (bench/analysis/validity.py).

## Pending live proofs (NOT recorded; consent boundaries apply)

These launch the real product binaries, so they are explicitly NOT
claimed by this lane. Each is offline-safe by construction (mock provider
or dead mock port, dummy keys, probe + erase only — no message submits),
and each needs an explicit go from the parent before it is run:

- **claude** (pinned npm 2.1.281 at `/usr/bin/claude`): the node-side
  pin is absent on this host — a version-matching 2.1.281 exists at
  `~/.local/bin/claude` but off the pinned path, so the proof runs on the
  bench node (or after a local pin-install, with consent). There:

  `PRIME_BENCH_REAL_PTY=1 python scripts/verify_erase_pty.py --products claude`

  Probe + erase + stress burst only; the trial env pins the mock provider
  and the dummy key; the mock request log must show zero model requests.
- **codex** (pinned npm 0.156.1 at `/usr/bin/codex`): same script,
  `--products codex`, on the node — the local `/opt/homebrew/bin/codex`
  is 0.155.1 (off-pin; NOT usable as the pinned proof). Probe + erase
  only, no message submits; any accidental submit 401s under the settled
  dummy key (real-api regime, `auth_limited`) — paid traffic still
  requires Kevin's explicit call.
- **pi**: re-proof on the bench node after the pi-pin-provenance and
  native-fixture lanes land (no local pi checkout on this host); the v2
  function proof stands as recorded until then.

## Recorded acceptance conditions

- **pi vendor-declaration gap**: pi's vendor block ships
  `~/.prime/config.json` and `~/.prime/agent/settings.json` undeclared in
  `auth_sources` at this base, so a pi-scoped `--no-secrets` build would
  carry the api_key. This closes with the pi-pin-provenance integration
  (`d0fa0e6`, merged via bench-integration-2 `bbf4923`), whose
  `auth_sources` declares the full prime-home credential set. The hygiene
  check (`bench/drivers/vendor.py: undeclared_secret_srcs`) is the
  standing gate for the class.
