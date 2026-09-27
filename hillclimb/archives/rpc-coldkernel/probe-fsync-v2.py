#!/usr/bin/env python3
"""4KB repeat-fsync latency probe (repeat-durability class), fleet interim
gate sizing: 50 samples, stall-rate + verdict reported alongside p50."""
import os, statistics, sys, time

n = int(sys.argv[2]) if len(sys.argv) > 2 else 50
path = sys.argv[1] if len(sys.argv) > 1 else "/root/fsync-probe.bin"
lat = []
data = os.urandom(4096)
with open(path, "wb+") as f:
    for _ in range(n):
        f.seek(0)
        f.write(data)
        t0 = time.perf_counter()
        os.fsync(f.fileno())
        lat.append((time.perf_counter() - t0) * 1000.0)
os.unlink(path)
lat.sort()
stall20 = sum(1 for x in lat if x > 20.0)
big = sum(1 for x in lat if x > 50.0)
rate20 = 100.0 * stall20 / len(lat)
verdict = "REGIME-DEGRADED" if (rate20 > 2.0 or big > 0) else "REGIME-HEALTHY"
print("FSYNC_MS n=%d min=%.2f p50=%.2f p90=%.2f max=%.2f stall20=%d gt50=%d rate20=%.1f%% verdict=%s" % (
    len(lat), lat[0], statistics.median(lat), lat[int(len(lat)*0.9)-1], lat[-1],
    stall20, big, rate20, verdict))
