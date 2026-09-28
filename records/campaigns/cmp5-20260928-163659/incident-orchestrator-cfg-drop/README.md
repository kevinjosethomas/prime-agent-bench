# Incident: orchestrator dropped the controller cfg (qualification wave 20260928-180926)

The orchestrator's `materialize()` did not pass the controller campaign cfg
to `deploy_harness`, so the per-sandbox `configs/sandbox.yaml` was written
WITHOUT the campaign's `benchmarks:` overrides. In the strictly-mock
campaign config, `benchmarks: compare.msg_send: {msg_routing: mock}` must
beat every product-level routing declaration; with the override missing,
codex's product.yaml `msg_routing: real-api` won and its 5 qualification
msg_send trials ran REAL-API (sentinel-certified: `real_api_certified: true`,
model openai/gpt-5.6-sol via its api-key route — 5 real inference calls,
short sentinel replies; small spend, no other product affected — rust/ts/
claude/pi all ran mock and settled on the mock reply).

Resolution: `materialize`/`deploy_harness`/`_handle_outliers`/`_run_waves`
now carry the controller cfg through every provision path; the sandbox
config deploys the overrides (regression test:
`test_run_parallel_deploys_controller_benchmark_overrides`). The wave was
re-qualified (phase qual2) after the fix; this directory preserves the raw
evidence of the bug: manifest.json + the qual results tree with the codex
real-api rows. The full campaign runs only the fixed orchestrator.
