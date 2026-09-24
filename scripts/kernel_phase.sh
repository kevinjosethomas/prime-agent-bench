#!/usr/bin/env bash
# Kernel phase (Section G P0): venv bootstrap, raw substrate probe, E2E grid,
# rust bridge probe. Sequential; the runner's load gate enforces idle trials.
# Usage: bash scripts/kernel_phase.sh <harness-checkout>
set -u
HARNESS=${1:?harness checkout path}
cd "$HARNESS"
RUN=~/bench/venv/bin/python
LOG=~/bench/logs
export PRIME_AGENT_KERNEL_VENV_RUST=/home/ubuntu/bench/global/rust/kernel-venv
export PRIME_AGENT_KERNEL_VENV_TS=/home/ubuntu/bench/global/ts/kernel-venv

echo "kernel phase start" >> $LOG/chain.log

# 0. mock restart with the kernel script
pkill -f bench.drivers.mock_provider; sleep 1
$RUN -c "from bench.adapters.benchmarks.kernel import kernel_script; from bench.core.config import load_config; from bench.runner import write_mock_script; write_mock_script(load_config(None), kernel_script())"
nohup $RUN -m bench.drivers.mock_provider ~/bench/harness/mock-script.json 8788 > $LOG/mock-service.log 2>&1 < /dev/null &
sleep 1

# 1. venv bootstrap (network-bound install; single timed run per product)
rm -rf ~/bench/global/rust/kernel-venv && mkdir -p ~/bench/global/rust/kernel-venv
( time env -i HOME=/home/ubuntu/bench/global/rust/prewarm-home TMPDIR=/home/ubuntu/bench/global/rust/tmp     PRIME_AGENT_KERNEL_VENV=$PRIME_AGENT_KERNEL_VENV_RUST UV_CACHE_DIR=/home/ubuntu/bench/global/rust/uv-cache     PATH=/usr/bin:/bin:/home/ubuntu/.local/bin     /home/ubuntu/.cargo/bin/cargo run --release --example kernel_bench --manifest-path /home/ubuntu/bench/repos/prime-agent-rust/Cargo.toml -- ensure-python ) > $LOG/rust-venv-bootstrap.log 2>&1
echo "rust venv bootstrap done" >> $LOG/chain.log

rm -rf ~/bench/global/ts/kernel-venv && mkdir -p ~/bench/global/ts/kernel-venv
( time env -i HOME=/home/ubuntu/bench/global/ts/prewarm-home TMPDIR=/home/ubuntu/bench/global/ts/tmp     PRIME_AGENT_KERNEL_VENV=$PRIME_AGENT_KERNEL_VENV_TS UV_CACHE_DIR=/home/ubuntu/bench/global/ts/uv-cache     PATH=/usr/bin:/bin:/home/ubuntu/.local/bin     node /home/ubuntu/bench/repos/prime-agent-ts/packages/coding-agent/dist/core/kernel/bootstrap-cli.js ) > $LOG/ts-venv-bootstrap.log 2>&1
echo "ts venv bootstrap done" >> $LOG/chain.log

# 2. raw substrate probes (10 independent kernels per product)
$RUN -m bench.drivers.kernel_raw rust 10 > $LOG/raw-rust.log 2>&1
$RUN -m bench.drivers.kernel_raw ts 10 > $LOG/raw-ts.log 2>&1
echo "raw probes done" >> $LOG/chain.log

# 3. E2E kernel grid (TUI-mediated, ABBA)
$RUN -m bench run --benchmarks kernel.cold_start --products rust,ts --trials 10 --phase k1 --skip-versions > $LOG/kernel-cold.log 2>&1
echo "k cold done" >> $LOG/chain.log
$RUN -m bench run --benchmarks kernel.cell_exec --products rust,ts --trials 10 --phase k2 --skip-versions > $LOG/kernel-cells.log 2>&1
echo "k cells done" >> $LOG/chain.log
$RUN -m bench run --benchmarks kernel.state_snapshot_1MB,kernel.state_snapshot_10MB,kernel.state_snapshot_50MB --products rust,ts --trials 5 --phase k3 --skip-versions > $LOG/kernel-state.log 2>&1
echo "k state done" >> $LOG/chain.log
$RUN -m bench run --benchmarks kernel.restart_restore_10MB --products rust,ts --trials 5 --phase k4 --skip-versions > $LOG/kernel-restart.log 2>&1
echo "k restart done" >> $LOG/chain.log
$RUN -m bench run --benchmarks kernel.multi_kernel_1,kernel.multi_kernel_3 --products rust,ts --trials 3 --phase k5 --skip-versions > $LOG/kernel-multi.log 2>&1
$RUN -m bench run --benchmarks kernel.multi_kernel_10 --products rust,ts --trials 1 --phase k6 --skip-versions > $LOG/kernel-multi10.log 2>&1
echo "k multi done" >> $LOG/chain.log

# 4. rust bridge probe: boot + snapshot-restore through the Rust manager
env -i HOME=/home/ubuntu/bench/global/rust/prewarm-home TMPDIR=/home/ubuntu/bench/global/rust/tmp     PRIME_AGENT_KERNEL_VENV=$PRIME_AGENT_KERNEL_VENV_RUST UV_CACHE_DIR=/home/ubuntu/bench/global/rust/uv-cache     PATH=/usr/bin:/bin:/home/ubuntu/.local/bin     /home/ubuntu/.cargo/bin/cargo run --release --example kernel_bench --manifest-path /home/ubuntu/bench/repos/prime-agent-rust/Cargo.toml -- boot > $LOG/rust-bridge-boot.log 2>&1
env -i HOME=/home/ubuntu/bench/global/rust/prewarm-home TMPDIR=/home/ubuntu/bench/global/rust/tmp     PRIME_AGENT_KERNEL_VENV=$PRIME_AGENT_KERNEL_VENV_RUST UV_CACHE_DIR=/home/ubuntu/bench/global/rust/uv-cache     PATH=/usr/bin:/bin:/home/ubuntu/.local/bin     /home/ubuntu/.cargo/bin/cargo run --release --example kernel_bench --manifest-path /home/ubuntu/bench/repos/prime-agent-rust/Cargo.toml -- snapshot-restore > $LOG/rust-bridge-snapshot.log 2>&1
echo "KERNEL PHASE COMPLETE" >> $LOG/chain.log
