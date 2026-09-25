# records/

Committed benchmark records. Two kinds live here:

- `campaigns/<run-label>/` — publishable campaign record bundles (below);
- standalone acceptance ledgers (e.g. `editor-cohort-acceptance.md` on
  their lane branches).

## The campaign records bundle

One campaign (one `run.label`) is committed as a minimal, privacy-audited,
re-analyzable bundle:

```
records/campaigns/<run-label>/
  rows/<benchmark>/trials-<phase>.jsonl   eligible rows only
  settle.jsonl                           settle evidence, screen text
                                         reduced to auth-marker labels
  summary.json                           the strict-gate analysis over
                                         exactly the bundled rows
  summary.md                             the same, human-readable
  provenance.json                        provenance + row accounting +
                                         privacy audit (machine-readable)
  NOTES.md                               the human record
  SHASUMS.txt                            sha256 of every file above
```

Build it offline (nothing is uploaded; commit it explicitly):

```bash
python scripts/publish_records.py --results-dir ~/bench/results [--label <run-label>] [--phase w1]
python scripts/publish_records.py --check records/campaigns/<run-label>   # verify SHASUMS
```

### Eligibility

A trial row enters the bundle only when it:

1. **matches the current row shape** — `schema_version` 1, the current
   core fields, the `run` provenance stamp (campaign label + harness
   revision), and no field this publisher does not know. Legacy unstamped
   rows and unknown-shape rows are excluded loudly (counted per reason in
   `provenance.json`), never silently passed through;
2. **belongs to the campaign** — its `run.label` matches the bundle label
   (mixed-label trees are the audit-F7/F8 failure class: pass `--label`
   and the other labels' rows are excluded + reported);
3. **passes the privacy audit** — see the contract below.

### Privacy contract

Excluded from every bundle, by construction — the bundler never reads raw
logs, trial homes/templates, fixture corpora, sandbox-runs, or vendor
payloads, and never writes a screen:

- raw PTY screens and screen tails (`settle_miss_screen` dropped; settle
  `screen_tail` reduced to the auth-marker labels it matched — the only
  consumer — plus a char count);
- machine paths (dropped as `path`/`cwd` keys; redacted inside strings);
- typed probe tokens (synthetic, but screen-derived — counts stay);
- credential-shaped values (`sk-…`, `bearer …`, `key/token/secret/password`
  assignments — real or dummy) redacted to `<credential>`;
- screen text embedded in harness error strings, reduced to the auth-marker
  labels it matched (the gate's reason codes stay identical);
- any string over 400 chars (the row quarantines, never silently trims).

Kept: metrics and per-row evidence, run provenance, and harness-generated
error strings (captured ≤400 chars, paths redacted) — the validity gate's
exclusion reason codes derive from them.

### Ranks

The bundle never invents ranks. `summary.json` is `bench analyze`'s strict
path over exactly the bundled rows, under the campaign config's rank
policy: `aa.required=false` (default) publishes validation-only stats with
**no ranks**; a strict campaign (`aa.required=true` + explicit
`aa.expected_products`) ranks a benchmark only over its complete,
A/A-calibrated, spread/drift-stable cohort (`ranks_withheld` otherwise).
`NOTES.md` states the rank status per benchmark.

### Reproducibility

`bench analyze --results-dir <bundle>/rows` (+ the bundled `settle.jsonl`
copied next to it) reproduces `summary.json`: the bundle carries every
input the gate consumed, redacted without semantic loss. `SHASUMS.txt`
pins the bytes; `--check` re-verifies them.

## Published campaigns

### `cmp-v4-campaign2-623b1a9` (2026-09-24) — validation-only, no ranks

The cmp-v4 comparative campaign's second pass, measured on one Prime VM
(8 vCPU / 16 GB / 100 GB, `tiequu6qsneqk9jxpwcdrw85`, deleted after
capture, ~69 min billed). Sequential ABBA waves, raw-PTY driver, N=10
published + N=10 A/A calibration rows per product, strict
result-validity gate, `aa.required=false` — validation-only: every
benchmark's ranks are withheld by policy (`validation_only`), so this
record publishes stats, marks and denominators, never a leaderboard.

- **Harness**: rev `623b1a9` = `f442a9d` + `92741f6` (session-10mib-v4
  generator) + `c7bfd5e` (loaded-session scenario switch). Fixture
  `session-10mib-v4` sha256 `5fa6e193…c3bba` (per-trial clone hashes
  bundled in every row); vendor payload sha256 `7f335b9e…98a2be`, built
  `--no-secrets` and audited with zero home/credential members.
- **Pins** (products that produced the bundled rows — full map in
  `provenance.json` → `source.versions`): rust `0.1.0`
  (`bdf82f4f1`/`eaed8f00`), ts `0.9.5-beta.2043.1.acc5bc0`
  (`e1583ca5`), pi `0.87.1` (`b455975`/`e79626f2`), claude `2.1.281`
  (`56fe3da8`, from the campaign's W2 run log). Codex `0.156.1` was
  pinned but excluded before capture (below).
- **Gate outcomes** (the summary's own marks):
  - `compare.warm_start` [rust, ts] — A/A and drift gates green.
  - `compare.memory_idle_load` [rust, ts, pi] — A/A and drift gates
    green.
  - `compare.msg_send` [rust, ts, claude] — A/A calibrated; ts (+19.0%)
    and claude (+23.3%) published-vs-A/A drift over the 10% threshold
    (unstable marks; sub-ms floor: the probe quantizes at 0.1 ms and the
    harness noop-control floor measured p50 0.072 ms / p95 0.095 ms
    over 30 rounds).
  - `compare.scroll_typing` [rust, ts, pi] — ts typing A/A spread 12.9%
    over the 10% floor (unstable mark).
- **Excluded before capture** (never in the bundle's rows or stats):
  codex on all benchmarks (unqualified for this campaign: trust-guard
  uncommitted and the mock lacks the responses wire); claude
  scroll_typing (`not_comparable` — no vendor-native session fixture);
  pi msg_send (first W2 aborted: fd/rg startup-download side-effect on
  the fresh home, settle=false at 90.93 s — rows preserved only in the
  private evidence archive under label `cmp-v4-campaign-623b1a9`,
  never pooled).
- **Not published here**: `compare.cold_start` (W1). Its rows are not
  part of the verified cmp2 evidence tree, so this record claims no W1
  numbers.
- **Evidence chain**: the bundle was built by
  `scripts/publish_records.py` from the verified private evidence
  archive `cmp-v4-final-evidence.tar.gz` (sha256
  `853f355f…76f23a`), which stays private: raw PTY logs, trial homes,
  fixture corpora and vendor payloads are never read by the publisher
  (`provenance.json` → `source.never_read`). Bundle integrity:
  `SHASUMS.txt` via `--check`.
