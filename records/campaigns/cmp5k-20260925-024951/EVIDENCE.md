# cmp5k kernel campaign — failure record (honest)

**Run**: 20260925-024951, launched 02:49:51Z, stopped 09:06Z by the operator (parent session) after structural failure was proven.

## Verdict
**FAILED — structurally invalid.** Every measured kernel trial errors with the verbatim error:
`TimeoutError: wait_for timeout after 300.0s`
(captured live from sandbox o9o2ksma5nfeuhe2r99o6ql4, /root/bench-root/results/kernel.restart_restore_10MB/trials-aa.jsonl, 2026-09-25 ~09:03Z)

Wave-chain log excerpt (the same pattern for every trial):
```
=== kernel.restart_restore_10MB ===
 rust trial 0 ready=None err=True (304.02s)
 ts trial 0 ready=None err=True (303.61s)
 ... (all trials, both products)
```

## Mechanism
- Each trial times out at the 300s wait_for, so a full chain (A/A + measured, 2 products) grinds ~3.4h of guaranteed-invalid rows.
- Sandboxes self-terminate at the 180-min cap mid-chain -> orchestrator retries (bounded 2x) -> same fate. The campaign could never complete.
- Wave chains that "exited 0" completed the CHAIN, not valid trials — the early-exited suites (multi_kernel_10 et al.) contain the same all-error rows, and their sandboxes self-terminated before collection, so their row data is unrecoverable.
- This reproduces the known historical invalidity (2026-09-24 audit findings F7/F8: "all-error kernel waves") and validates the readiness matrix's recommendation to defer kernel.* — the deferral was overridden by an explicit operator request to launch the kernel set.

## Disposition
- Terminal-set campaign (cmp5b): COMPLETE, officially ranked, published (see records/campaigns/cmp5b-20260925-044035).
- Kernel set: no valid numbers exist. Deferred pending harness-side kernel-scenario debugging (the 300s wait never sees the expected kernel output — likely the kernel mock script or the kernel-venv lifecycle inside sandboxes).
- Cost: sandbox hours sunk ~$6-9 (9 initial + 3 retry sandboxes, most killed by their own caps). The live retry sandbox was destroyed at teardown; no sandbox of ours remains.
