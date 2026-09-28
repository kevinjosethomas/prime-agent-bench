# Gate evidence — build, preflight, pins (recorded 2026-09-28)

## Gate 1 — Linux binary from the frozen pin (built, verified)

- Source: `b5bf28f1d752ca9bea0ab1d3d24b572e682d69e5` (origin/rust frozen at campaign start 2026-09-28T16:36:59Z; origin/rust has since advanced by exactly one unrelated commit `b89b8ffdd` landed 16:49Z — AFTER campaign start, so the freeze holds).
- Built on Prime VM sandbox `hv8hn1ejxt6slfqkw1arudmi` (bench-build-cmp5, 16c/32GB Ubuntu 22.04.5, glibc 2.35), replicating the pinned commit's `continuous.yml` Linux x86_64 recipe: rustc 1.98.1, `cargo build --release --locked --target x86_64-unknown-linux-gnu`, `split_debug.py` (shipped binary + decoder), GLIBC 2.35 gate, `bundle_catalog.py --fixture`, `assemble_artifacts.py --sha b5bf28f1d...`.
- Artifact tarball `prime-agent-0.1.0-linux-x64.tar.gz` (19,385,942 bytes): SHA-256 `a4b8bb115527318f4268c42fecf48e9f80724ac56752960f72fd1b8abeffdfaf` (SHA256SUMS verified inside the VM and again on the bench box after download).
- Shipped binary `prime-agent` (57,108,704 bytes): SHA-256 `5b1042ecfc495b8e51b3661c3b1c874c04834abcd6499b563fe6a512a430f40f`. Debug decoder `prime-agent-0.1.0-linux-x64.debug.gz`: SHA-256 `904daf9fa59adc1cec5895440e6253bf07e05006b2cfed5925af23ca3746d094`.
- GLIBC gate: highest GLIBC symbol required `GLIBC_2.34` (≤ 2.35 floor) — PASS.
- `--version` inside the VM: `0.1.0-continuous.b5bf28f1d752ca9bea0ab1d3d24b572e682d69e5`.
- Installed on the bench box into the campaign-private prefix `~/bench-cmp5/pa-rust-prefix` with the pinned commit's takeover layout (`share/prime-agent` payload + `bin/prime-agent` launcher extracted verbatim from the pinned commit's install-rust.sh); launcher `--version` answers the same string; payload SHA-256 re-verified post-install. CI artifact for this commit was still pending at campaign start — the sandbox build path was used per the campaign task; no cargo ran on the bench box or the Mac.

## Gate 2 — native preflight on a fresh Ubuntu 22.04 sandbox (PASSED)

- VM `klr9p9g6vayebsojgaoh3rk5` (bench-preflight-cmp5, ubuntu:22.04 fresh, glibc 2.35, no prior state).
- `--version`: `0.1.0-continuous.b5bf28f1d752ca9bea0ab1d3d24b572e682d69e5` (exit 0).
- Headless session boot (daemon wire chain, protocol 7 / schema 30): spawn→socket accept 20.2 ms, accept→hello 0.2 ms, hello→first `create` response `{"success": true, data.id "29147fc054f0", lifecycle "draft"}` 28.8 ms — `create_ok: true`, clean terminate.
- Payload SHA-256 inside the preflight VM matches the frozen pin (`5b1042ec...`).

## Gate 3 — five-product pins (latest stable, recorded in configs)

| product | pin | evidence |
|---|---|---|
| Prime Agent Rust | `b5bf28f1d...` (frozen origin/rust) | this build; payload SHA-256 `5b1042ec...` pinned in `bench/adapters/rust/product.yaml` (`binary_sha256`) |
| Prime Agent TS | `0.9.6` (official stable, GitHub release v0.9.6 2026-09-24 — latest non-prerelease) | unchanged; installed at `~/.local/share/prime-agent` (release payload sha `69e5bb91...` per versions evidence) |
| Claude Code | `2.1.283` (npm `@anthropic-ai/claude-code@latest` = installed) | unchanged |
| Codex CLI | `0.158.0` (updated from 0.157.0 via `sudo npm install -g`; package dir permissions fixed with `chmod a+rX` after the sudo install) | `codex --version` = `codex-cli 0.158.0` |
| Pi Mono | `11894012dd461232eb075bc890538b6866860a10` (origin/master HEAD 2026-09-28, rebuilt from source; reports 0.87.1) | bundle tree tar SHA-256 `96cf0668b6de99764d3591948b3aa089394331f17669565619a8db82a1b1c6a9`; note: `dist/bundle/cli.js` is a 160-byte launcher whose sha (`e79626f2...`) is stable across builds — the tree sha above is the payload identity |

- Routing: strictly mock for every product/benchmark — new `configs/campaign-cmp5.yaml` sets `benchmarks: compare.msg_send: {msg_routing: mock}` (beats codex's product-level real-api declaration); the previous campaign config (real-api msg_send) is NOT reused.
- Offline suite qualification: full harness pytest on the bench box after all pin/config edits — **128 passed** (tests/ 2026-09-28).
- Adapter path fix (campaign-harness only): rust vendor dsts now mirror the pinned binary's `~`-path under `/root` (`root/bench-cmp5/pa-rust-prefix/...`) so the sandbox-side adapter resolves the same layout without the previous campaign's in-sandbox `cp -a` mirror hack; `vendor/bootstrap.sh` version-check path updated to match; adapter payload resolution handles both the pinned takeover layout (`share/prime-agent`) and the legacy one.
