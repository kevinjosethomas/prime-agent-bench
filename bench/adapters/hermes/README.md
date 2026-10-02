# Hermes Agent adapter

The Nous Research agent (github.com/NousResearch/hermes-agent), added to the
comparison set at the operator's request (the blog's 6th product).

## Install (the pin)

The release tag v2026.9.24 (v0.21.5), commit f97608f17, installed by the tag's
own `scripts/install.sh` (the installer that shipped WITH that release; the
live `install.sh` on the website is the pm-era main and cannot install the
release tag - it fails at `python -m pm.cli`). Root FHS layout:
code+venv `/usr/local/lib/hermes-agent`, command `/usr/local/bin/hermes`
(a bash shim exec'ing the venv python on the checked-in `hermes` entrypoint),
uv-managed CPython at `/usr/local/share/uv/python`. The install ran in the
prep sandbox (HOME=/root) so every absolute path in the payload resolves
identically in the benchmark sandboxes; the payload is shipped verbatim via
the vendor tarball (the `.git` dir excluded).

## Routing (the mock regime)

Hermes speaks any OpenAI-compatible endpoint ("custom" provider: `model.provider:
custom` + `base_url` + `api_key` in ~/.hermes/config.yaml, or the
`--provider custom --base-url ... --model ... --api-key ...` flags). The
adapter pins the same offline SSE mock (port 8788) the other mock-routed
products use, with the same dummy key; the per-trial config.yaml lives in the
trial home (~/.hermes), so session/state isolation follows the harness's
per-trial HOME contract.

## TUI interaction

prompt_toolkit-based; Enter always submits (`_bind_prompt_submit_keys`:
"Enter always submits"; multiline is opt-in via ctrl-j / escape-enter, off by
default for submits); typed text echoes in the composer (the probe/readiness
contract). Settle detection: the mock's scripted reply renders in the stream
(same DEFAULT_REPLY match as the other mock products).


## Trustworthy-suite additions (2026-10-02, the publishable suite)

- **No daemon.** The chat CLI is a single interactive process (the gateway/
  serve/desktop modes are separate products' surfaces, not the TUI's own
  daemon), so `compare.warm_start` measures the native repeat launch
  (`warm_mode=repeat_launch`) and `daemon.boot` does not apply.
- **Ready = the typed token on the ``❯`` input row.** `input_prompt:
  '\s*❯\s*'` pins the default skin's composer glyph
  (`hermes_cli/cli_tui_mixin.py: _get_tui_prompt_symbols` ->
  `skin_engine.get_active_prompt_symbol("❯ ")`), so the trustworthy
  input-row validator accepts the echo only on the prompt line; the
  token-persistence check (0.5 s) and the raw-tty probe apply as for
  every product.
- **Version evidence is machine-collected where trials run.** In-sandbox
  `/usr/local/bin/hermes --version` answers from the fast path (before
  the config/network import wall) and `binary_sha256` is a digest of the
  installed code tree (sorted (path, sha256), `.git`/`__pycache__`
  excluded) pinned in product.yaml — a swapped or modified payload fails
  loudly at every pass's version collection, and a mid-run change fails
  the end-of-pass check. On the node (no FHS install) the staging tree
  answers instead.
- **No self-update.** The per-trial ~/.hermes/config.yaml pins
  `updates.check: false` — v0.21.5's own switch for the banner's passive
  GitHub-API check (cached at ~/.hermes/.update_check); there is no
  HERMES_NO_UPDATE_CHECK env in this release (the env var rides inert).
  Updates are user-initiated (`hermes update`), never taken by a trial.
- **First-run dialogs: none.** The pre-provisioned config.yaml (custom
  provider -> mock) settles the composer; `first_run_dialogs: []` stays.
