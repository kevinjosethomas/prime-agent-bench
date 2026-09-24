# Pi — recorded live proof: native --session resume (function-only)

One recorded qualification proof for the Pi adapter, produced by the
`bench-pi-live` session on 2026-09-24 and archived externally. This file
is the in-repo reference record (scrubbed, digest-pinned); the artifacts
stay outside the repo and are referenced by sha256. It is evidence of
exactly its scope below — not a campaign trial, not a ranking, and not
a validation of the v3 corpus the corrected campaign's loaded-session
benchmarks run on.

## Scope (what this run proved)

- Harness: `prime-agent-bench` @ `9d5071b` (branch off
  `vendor-history-imports`), git-archive staged; deploy bundle sha256
  `417d5000ff71fd3a955ff9a1e521e9d32dee66f42498b219e00b0e2eef3325c7`.
- Product: pinned Pi `0.87.1`, revision `b45597504eeaba1f11a9920a1d1048c361ed4b8e`
  (git describe `v0.87.1-16-gb455975`), built from the benchmark-node
  source checkout; `cli.js` sha256
  `e79626f2dd6f94aa45d30f3fa63cd84319a6eefcd150b353cfaf274366926774`,
  runtime sha256
  `9c304f2fe9b0b9211f0ea201cf92206526833db58dc1c45341d09c372a0232a0`.
- Fixture: the 10MiB **v2** corpus (`session-10mib`, generator
  `session-size/2`), 7391 rows, sha256
  `dadaecfcac511e24ed0e0df15fb1facbe556557856486d62bad628250194cdda`,
  tail sentinel `CORPUS-TAIL-9f3a1c70`, staged as a byte-identical native
  transcript (staged-file sha256 = golden sha256).
- Proven, in one sandbox run: native `--session` resume of the v2 fixture
  loads the transcript and renders the tail sentinel (~16s); the editor is
  interactive before and after mount (typed probe `Zq7x01` echoed at
  ~280ms pre-mount; a fresh token echoed post-mount); the line is
  clearable — **Ctrl-U pre-mount, DEL post-mount**; zero model submits
  (mock port unbound and verified dead; argv pinned
  `--provider prime-inference --model mock-1`; launch + render + echo +
  erase only).

## What this run did NOT prove (never claim it did)

- No v3-corpus validation: `session-10mib-v3` (the corrected campaign's
  `session.cold_open_10mib` / `compare.memory_idle_load` /
  `compare.scroll_typing` corpus) was never resumed.
- No adapter capability at this revision: `resume_fixture_capable` stays
  `False` until the native-fixture lane (`vendor-history-imports`) merges.
- No campaign trial, no A/A calibration, no performance number, no
  cross-product comparison.
- Single sandbox, single build, single run: a feasibility proof, not a
  statistical one.

## Findings (recorded caveats)

1. **Pre-mount DEL-burst erase fails on pi.** The harness `erase_all`
   burst (14x `0x7f`, one write) did not clear a token typed during the
   pre-mount transcript render (r1: `probe_erased: false`); Ctrl-U
   (`0x15`) cleared the line; a token typed *after* mount erases fine
   with DELs (r2). Loaded-session scenarios that probe early then erase
   with DELs would record `erased=false` on pi — the row-validity gate
   rejects those rows (honest no-data, never a false number). Candidate
   fix classes (not implemented here): a pi-proven Ctrl-U erase in the
   adapter, post-sentinel probe ordering, or erase validation aware of
   buffered pre-mount input.
2. **`version_info` layout gap.** The package.json lookup via the
   bench-root layout breaks in the sandbox layout (the proof captured
   identity from files instead — see `proof-versions.json`). Fix landed
   on `pi-pin-provenance` @ `405ae13` (resolve from the cli ancestry),
   pending integration.

## Artifacts (external archive, sha256-pinned)

Archive: `/tmp/bench-pi-live/` (the producing session's archive; the
sandbox was destroyed after the run, quota freed).

| artifact | sha256 |
|---|---|
| `PROVENANCE.json` | `829c4c1aa676bbd27c9c3224f7e2f3cca355d8769ca2af4652992f3289e8b130` |
| `pi-native-proof-r2.json` | `c96d0943c65636667e45938921694638d44378b3db096eef8edd168a4cbc20fe` |
| `pi-native-proof.json` | `fe20da559e6f7a8d69c771f145deeffe2af310a71923e86a345b0ece43d7937e` |
| `proof-versions.json` | `78fa339ee03e06f25b3a0d015f8ffc61526a1cd923707ac7f0e2ed62352cf4a6` |

`product.yaml` carries this proof as the `native-session-resume` entry
(`proofs:`); `ProductAdapter.proof_records()` verifies artifact digests
when the archive is present on the host and reports `absent-external`
when it is not — never a silent pass.

## Pending (the honest next proofs)

- The same function proof on the **v3 corpus** once the corrected
  campaign's loaded-session paths settle.
- A re-proof after `pi-pin-provenance` (`d0fa0e6`) merges, and again
  after the native-fixture/erase lanes land, before any pi
  loaded-session number is published.
