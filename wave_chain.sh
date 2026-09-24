#!/usr/bin/env bash
# Benchmark wave chain: B (warm), C (msg_send), D (scroll+10mib open), E (daemon boot) + install disk.
# Each wave waits for the previous; the runner's internal load gate enforces idle between trials.
set -u
cd /home/ubuntu/bench/harness
RUN=~/bench/venv/bin/python
LOG=~/bench/logs

# Wave B: warm start, all 5
$RUN runner.py --benchmarks compare.warm_start --products rust,ts,claude,codex,pi --trials 10 --phase w2 > $LOG/wave-b-warm.log 2>&1
echo "B done" >> $LOG/chain.log

# Wave C: msg send, all 5
$RUN runner.py --benchmarks compare.msg_send --products rust,ts,claude,codex,pi --trials 10 --phase w3 > $LOG/wave-c-msg.log 2>&1
echo "C done" >> $LOG/chain.log

# Wave D: scroll+typing on 10MiB (RT), cold open 10MiB (RT)
$RUN runner.py --benchmarks compare.scroll_typing --products rust,ts --trials 10 --phase w4 > $LOG/wave-d-scroll.log 2>&1
echo "D1 done" >> $LOG/chain.log
$RUN runner.py --benchmarks session.cold_open_10mib --products rust,ts --trials 10 --phase w4 > $LOG/wave-d-open.log 2>&1
echo "D2 done" >> $LOG/chain.log

# Wave E: daemon boot (RT)
$RUN runner.py --benchmarks daemon.boot --products rust,ts --trials 10 --phase w5 > $LOG/wave-e-daemon.log 2>&1
echo "E done" >> $LOG/chain.log

# Install disk (one-shot)
$RUN install_disk.py > $LOG/install-disk.log 2>&1
echo "DISK done" >> $LOG/chain.log
echo "CHAIN COMPLETE" >> $LOG/chain.log
