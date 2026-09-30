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
