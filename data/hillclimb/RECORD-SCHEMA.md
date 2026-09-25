# Hillclimb experiment record schema (orchestrator-defined 2026-09-25)

The mission prompt says the JSON format lives in ~/hillclimb-prompt.md, but that file
contains no schema (verified). This is the orchestrator's definition; every worker uses it.

File: /home/ubuntu/prime-agent-bench/data/hillclimb/experiments/<YYYYmmdd-HHMMSS>-<axis>-<slug>.json
(one attempt per file, merged or discarded). Commit ONLY that file on branch `hillclimb`
(git add <file> && git commit && git push origin HEAD:hillclimb) — the bench repo carries
unrelated WIP; never `git add -A`.

```json
{
  "id": "<timestamp>-<axis>-<slug>",
  "axis": "startup|interaction|memory|binary-size|cpu|io|other",
  "hypothesis": "the bottleneck and its likely mechanism",
  "approach": "what was changed, files/functions",
  "parity_notes": "why feature/behavior/model-API/platform parity is preserved",
  "base": {"revision": "7152746b99f6767843bb40b4674a23a5a501fdc0"},
  "branch": "lane/hillclimb-<axis>",
  "commits": ["<sha>", "..."],
  "build": {"sandbox_id": "...", "binary_sha256": "...", "binary_bytes": 0,
             "build_seconds": 0, "toolchain": "rustup 1.98.1"},
  "gates": {"fmt": "pass|fail", "clippy": "pass|fail", "test": "pass|fail <detail>"},
  "measurements": {
    "method": "parallel-sandboxes|same-vm-sequential",
    "suites": {"<suite>": {
        "baseline": {"trials": 5, "valid": 5, "p50_ms": 0, "p95_ms": 0, "values_ms": []},
        "candidate": {"trials": 5, "valid": 5, "p50_ms": 0, "p95_ms": 0, "values_ms": []},
        "delta_pct": 0,
        "regression": false
    }},
    "extra": {"binary_bytes": {"baseline": 0, "candidate": 0}, "rss_mb": {"baseline": 0, "candidate": 0}}
  },
  "validity": {"excluded": [], "notes": "A/A or noise-floor notes"},
  "outcome": "merged|discarded|failed|in-progress",
  "decision": "orchestrator decision + why",
  "pr_url": "https://github.com/PrimeIntellect-ai/prime-agent/pull/N",
  "record_path": "data/hillclimb/experiments/<file>.json",
  "session": {"worker": "<name>", "session_dir": "~/.prime/agent/sessions/<id>.jsonl"},
  "timestamp": "<ISO8601>"
}
```

Failure records are as valuable as successes: record discarded attempts with the numbers
and the reason. Never fabricate a number; an unmeasured cell is null.
