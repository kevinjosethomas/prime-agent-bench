# Hillclimb orchestrator workspace (this box = orchestrator only, NO cargo builds here)

- Product repo clone: /home/ubuntu/prime-agent-rust (origin/rust @ 7152746b99f6767843bb40b4674a23a5a501fdc0)
- Bench harness repo: /home/ubuntu/prime-agent-bench (branch hillclimb; carries Kevin's WIP — do not add/commit WIP files; commit only data/hillclimb/**)
- Bench harness bundle (deployable to any Prime VM): /home/ubuntu/hillclimb/hillclimb-bench-bundle.tar.gz
  - Contains bench/, configs/, requirements.txt, pyproject.toml, vendor/ (products.tar.gz w/ rust runtime+uv toolchain)
  - bench/adapters/rust/product.yaml pins binary=/root/bench/repos/prime-agent-rust/target/release/prime-agent
- Baseline sandbox: hillclimb-baseline-rust (16c/32GB VM); suite phase label: baseline-7152746b
- Baseline results land in /home/ubuntu/hillclimb/baseline-results/ after collection
- Suites: compare.cold_start, compare.warm_start, compare.msg_send, compare.scroll_typing,
  compare.memory_idle_load, session.cold_open_10mib, session.agent_view_roundtrip, daemon.boot
- Sandbox VM exec: prime --plain sandbox run <id> --timeout <s> -- bash -lc '<cmd>' (fresh shell each time)
- VM create MUST use the python SDK (prime CLI cannot create VMs):
  /home/ubuntu/prime-agent-bench/.venv/bin/python with prime_sandboxes CreateSandboxRequest(..., vm=True, start_command=StartCommand(executable="tail", args=["-f","/dev/null"]))
- Delete your VMs when done: prime --plain sandbox delete <id> -y
