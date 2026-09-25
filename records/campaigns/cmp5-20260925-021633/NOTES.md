# cmp5 campaign raw record (run 20260925-021633)

- Terminal-set campaign: 9 concurrent Prime VM sandboxes (one per benchmark type), 5 products sequential inside each; 20-trial balanced A/A + 10 measured trials per product; strict gates declared in campaign-full-five.yaml (aa.required=true with expected cohorts).
- Rust pin fa9395128d8c2f1f18b14b0f634f0df25525cc25, binary sha256 e61c5ca7b8a2ad8cd7cef2cf5df623723550fede0ce9f487144f2671af084ed0 (most-recent-verified per operator directive).
- Harness bench-integration-3 @ 141e917 (228/228 offline; skip-isolation; codex vendor path fix).
- Secret-free payload 665MB sha 90675818917d075a...; per-trial data is synthetic (mock provider, v4 fixture golden 5fa6e193...).
- Data: per-sandbox collected results trees (trials-aa/cmp5 JSONL, settle.jsonl, versions.json, noop-control.json) + orchestrator manifest + run logs + auto-analysis outputs.
