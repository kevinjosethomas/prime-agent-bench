#!/bin/bash
set -uo pipefail
BIN=/root/prime-agent-rust/target/release/prime-agent
FX=/root/rpc-fixtures/session-10mib-compacted.jsonl
OUT=/root/rpc-coldkernel-results
mkdir -p $OUT
echo "=== BATTERY START $(date -u +%FT%TZ)"
sha256sum $BIN
echo "--- mock provider check"
head -2 /root/rpc-mock/mock.log || true

echo "--- IO PREFLIGHT $(date -u +%T)"
python3 /root/probe-fresh-v3.py /root/io-pre 40 | tee $OUT/io-pre.txt
python3 /root/probe-fsync-v2.py /root/io-pre-fsync 50 | tee -a $OUT/io-pre.txt

echo "--- LEG A warm-census n=6 $(date -u +%T)"
MOCK_BASE=http://127.0.0.1:8890/v1 python3 /root/rpc_coldkernel_probe.py warm-census 6 $BIN $OUT/legA.json 2>&1 | tee $OUT/legA.log

echo "--- IO MID-1 $(date -u +%T)"
python3 /root/probe-fresh-v3.py /root/io-mid1 40 | tee $OUT/io-mid1.txt
python3 /root/probe-fsync-v2.py /root/io-mid1-fsync 50 | tee -a $OUT/io-mid1.txt

echo "--- LEG B warm-immediate n=6 $(date -u +%T)"
MOCK_BASE=http://127.0.0.1:8890/v1 python3 /root/rpc_coldkernel_probe.py warm-immediate 6 $BIN $FX $OUT/legB.json 2>&1 | tee $OUT/legB.log

echo "--- IO MID-2 $(date -u +%T)"
python3 /root/probe-fresh-v3.py /root/io-mid2 40 | tee $OUT/io-mid2.txt
python3 /root/probe-fsync-v2.py /root/io-mid2-fsync 50 | tee -a $OUT/io-mid2.txt

echo "--- LEG C-LATE cold-late n=2 $(date -u +%T)"
MOCK_BASE=http://127.0.0.1:8890/v1 python3 /root/rpc_coldkernel_probe.py cold-late 2 $BIN $FX $OUT/legC-late.json 2>&1 | tee $OUT/legC-late.log

echo "--- IO MID-3 $(date -u +%T)"
python3 /root/probe-fresh-v3.py /root/io-mid3 40 | tee $OUT/io-mid3.txt
python3 /root/probe-fsync-v2.py /root/io-mid3-fsync 50 | tee -a $OUT/io-mid3.txt

echo "--- LEG C-EARLY cold-early n=3 $(date -u +%T)"
MOCK_BASE=http://127.0.0.1:8890/v1 python3 /root/rpc_coldkernel_probe.py cold-early 3 $BIN $FX $OUT/legC-early.json 2>&1 | tee $OUT/legC-early.log

echo "--- IO POST $(date -u +%T)"
python3 /root/probe-fresh-v3.py /root/io-post 40 | tee $OUT/io-post.txt
python3 /root/probe-fsync-v2.py /root/io-post-fsync 50 | tee -a $OUT/io-post.txt

echo "--- CENSUS TRIALS (strace; structure-only, timing INVALID) $(date -u +%T)"
mkdir -p /root/rpc-coldkernel-census
RPC_CENSUS_DIR=/root/rpc-coldkernel-census RPC_CENSUS_TAG=ce0 MOCK_BASE=http://127.0.0.1:8890/v1 python3 /root/rpc_coldkernel_probe.py cold-early 1 $BIN $FX $OUT/census-ce0.json 2>&1 | tail -3
RPC_CENSUS_DIR=/root/rpc-coldkernel-census RPC_CENSUS_TAG=cl0 MOCK_BASE=http://127.0.0.1:8890/v1 python3 /root/rpc_coldkernel_probe.py cold-late 1 $BIN $FX $OUT/census-cl0.json 2>&1 | tail -3
RPC_CENSUS_DIR=/root/rpc-coldkernel-census RPC_CENSUS_TAG=cw0 MOCK_BASE=http://127.0.0.1:8890/v1 python3 /root/rpc_coldkernel_probe.py warm-census 1 $BIN $OUT/census-cw0.json 2>&1 | tail -3
RPC_CENSUS_DIR=/root/rpc-coldkernel-census RPC_CENSUS_TAG=ci0 MOCK_BASE=http://127.0.0.1:8890/v1 python3 /root/rpc_coldkernel_probe.py warm-immediate 1 $BIN $FX $OUT/census-ci0.json 2>&1 | tail -3
RPC_CENSUS_DIR=/root/rpc-coldkernel-census RPC_CENSUS_TAG=ce1 MOCK_BASE=http://127.0.0.1:8890/v1 python3 /root/rpc_coldkernel_probe.py cold-early 1 $BIN $FX $OUT/census-ce1.json 2>&1 | tail -3

echo "--- binary sha re-assert $(date -u +%T)"
sha256sum $BIN
echo "=== BATTERY DONE $(date -u +%FT%TZ)"
