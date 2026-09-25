# Campaign record: cmp-v4-campaign2-623b1a9

_Records bundle `bench-records-bundle/1`; generated 2026-09-24T17:40:28-0700 by harness rev a03bf0389158780b4c88876efc652634520a5215 (dirty=False)._

## Provenance

- campaign run label: **cmp-v4-campaign2-623b1a9** (labels seen in the source tree: ['cmp-v4-campaign2-623b1a9'])
- harness revisions that measured the rows: ['623b1a948920859aa0cc65cc61a65d546e4a30a3']
- benchmarks: compare.memory_idle_load, compare.msg_send, compare.scroll_typing, compare.warm_start
- phases: aa, cmp2
- source results tree: `<path>` (machine paths redacted)
- pinned product versions: see `versions` in provenance.json (binary paths scrubbed)

## Row accounting

- bundled rows: **220** ({"compare.memory_idle_load/trials-aa.jsonl": 30, "compare.memory_idle_load/trials-cmp2.jsonl": 30, "compare.msg_send/trials-aa.jsonl": 30, "compare.msg_send/trials-cmp2.jsonl": 30, "compare.scroll_typing/trials-aa.jsonl": 30, "compare.scroll_typing/trials-cmp2.jsonl": 30, "compare.warm_start/trials-aa.jsonl": 20, "compare.warm_start/trials-cmp2.jsonl": 20})
- publisher-excluded rows: 0 — {}

## Validity gate (over the bundled rows)

- no gate exclusions among the bundled rows

## Ranks

- `compare.memory_idle_load`: ranks withheld (validation_only)
- `compare.msg_send`: ranks withheld (validation_only)
- `compare.scroll_typing`: ranks withheld (validation_only)
- `compare.warm_start`: ranks withheld (validation_only)

## Privacy audit

- no raw screens: PTY/screen/tail text keys dropped; settle screen_tail reduced to auth-marker labels + char count
- no raw logs, homes, fixtures, session payloads, vendor material: never read (see source.never_read)
- no machine paths: path/cwd keys dropped, strings redacted
- no typed probe tokens (synthetic but screen-derived); counts stay
- no string over 400 chars (rows quarantine)
- no credentials: credential-shaped values (sk-…, bearer …, key/token/secret/password assignments — real or dummy) are redacted to <credential>
- harness-generated error strings kept (≤400 chars at capture) with screen text reduced to marker labels, paths and credentials redacted — the validity gate's reason codes derive from them and stay intact

- dropped keys: {"path": 320, "cwd": 120, "binary": 3}; redacted path strings: 260
- settle rows bundled: 0 of 0 (screen text reduced to auth-marker labels)

Caveat: harness-generated error/diagnostic strings are kept truncated (≤400 chars, paths redacted). Product screens, session text, homes, fixtures and vendor payloads are not in this bundle by construction.

Verify: `python scripts/publish_records.py --check cmp-v4-campaign2-623b1a9` (or pass the bundle dir).
