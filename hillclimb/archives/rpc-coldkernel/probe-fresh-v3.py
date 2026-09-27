#!/usr/bin/env python3
"""Fleet I/O advisory v1.0 fresh-write class probe: >=40 ISOLATED
fresh+sync_all+rename ops at 0.5s spacing (isolated windows), stall-rate
and max reported host-relative."""
import os, statistics, sys, time

n = int(sys.argv[2]) if len(sys.argv) > 2 else 40
base = sys.argv[1] if len(sys.argv) > 1 else "/root/fresh-probe"
stable = base + ".stable"
data = os.urandom(4096)
lat = []
for i in range(n):
    tmp = base + ".tmp"
    t0 = time.perf_counter()
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.rename(tmp, stable)
    os.stat(stable)
    lat.append((time.perf_counter() - t0) * 1000.0)
    time.sleep(0.5)
try:
    os.unlink(stable)
except OSError:
    pass
lat.sort()
stall20 = sum(1 for x in lat if x > 20.0)
stall15 = sum(1 for x in lat if x > 15.0)
big = sum(1 for x in lat if x > 50.0)
rate20 = 100.0 * stall20 / len(lat)
print("FRESH_ISOLATED_MS n=%d min=%.2f p50=%.2f p90=%.2f max=%.2f stall15=%d stall20=%d gt50=%d rate20=%.1f%%" % (
    len(lat), lat[0], statistics.median(lat), lat[int(len(lat)*0.9)-1], lat[-1],
    stall15, stall20, big, rate20))
