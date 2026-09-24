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
