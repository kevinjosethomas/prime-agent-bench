"""A scripted mini-TUI for probe-semantics tests (not a benchmark).

Raw mode from the start (a real TUI never kernel-echoes), a banner for
first paint, then one of three readiness behaviors:

- buffered: sleep R, then echo everything already queued (the kernel PTY
  buffer held pre-ready probes; the echo renders them all at mount time)
- dropped: sleep R, tcflush the queue, then echo (pre-ready probes are
  discarded; only post-ready probes echo)
- dialog: print an onboarding marker, sleep, remove it, then echo (the
  probe must answer the dialog inline and exclude its time from the gap)
- cooked: paint the banner while the tty is still cooked (the kernel
  would echo typed bytes itself), sleep R, then go raw and echo
"""
import os
import sys
import termios
import time
import tty

mode = sys.argv[1]
delay = float(sys.argv[2]) if len(sys.argv) > 2 else 0.3
MARKER = "Share agent traces with Prime Intellect?"

fd = sys.stdin.fileno()
banner = "\r\n  FAKE-TUI READY\r\n"
if mode != "cooked":
    tty.setraw(fd)  # raw from the start: no kernel echo of typed probes
if mode == "cooked":
    sys.stdout.write(banner); sys.stdout.flush()
    time.sleep(delay)
    termios.tcflush(fd, termios.TCIFLUSH)
    tty.setraw(fd)
elif mode == "dialog":
    sys.stdout.write("\r\n  " + MARKER + "\r\n"); sys.stdout.flush()
    time.sleep(delay)
    # remove the marker's own line (the cursor sits one row below it)
    sys.stdout.write("\x1b[1A\r\x1b[K"); sys.stdout.flush()
else:
    sys.stdout.write(banner); sys.stdout.flush()
    time.sleep(delay)
if mode == "dropped":
    termios.tcflush(fd, termios.TCIFLUSH)  # discard the queued probes
try:
    while True:
        data = os.read(fd, 4096)
        if not data:
            break
        os.write(1, data)  # echo back exactly what was read
        sys.stdout.flush()
finally:
    termios.tcsetattr(fd, termios.TCSADRAIN, termios.tcgetattr(fd))
