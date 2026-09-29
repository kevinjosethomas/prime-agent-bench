
import os, sys, termios, tty, time, select

def probe(query: bytes, wait_s: float, label: str, out_path: str):
    fd = 0
    # raw mode on the controlling tty
    old = termios.tcgetattr(fd)
    tty.setraw(fd)
    results = []
    try:
        for trial in range(10):
            # drain
            while select.select([fd], [], [], 0)[0]:
                os.read(fd, 65536)
            t0 = time.monotonic()
            os.write(1, query)  # stdout == the same tty
            reply = b""
            deadline = t0 + wait_s
            while time.monotonic() < deadline:
                r, _, _ = select.select([fd], [], [], max(0, deadline - time.monotonic()))
                if r:
                    chunk = os.read(fd, 65536)
                    reply += chunk
                    if reply.endswith(b"c") or reply.endswith(b"u"):
                        break
            dt_ms = (time.monotonic() - t0) * 1000.0
            results.append((round(dt_ms, 3), reply))
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    with open(out_path, "w") as f:
        for dt, reply in results:
            f.write(f"{label}\t{dt}\t{reply!r}\n")

if __name__ == "__main__":
    mode = sys.argv[1]
    out = sys.argv[2]
    if mode == "da1":
        probe(b"\x1b[c", 1.0, "da1", out)
    elif mode == "kitty":
        probe(b"\x1b[?u", 1.0, "kitty_flags", out)
    elif mode == "both":
        probe(b"\x1b[?u\x1b[c", 1.0, "both", out)
