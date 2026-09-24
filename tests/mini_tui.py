"""A scripted mini-TUI for probe-semantics tests (not a benchmark).

Raw mode from the start (a real TUI never kernel-echoes), a banner for
first paint, then one of the readiness behaviors:

- buffered: sleep R, then echo everything already queued (the kernel PTY
  buffer held pre-ready probes; the echo renders them all at mount time)
- dropped: sleep R, tcflush the queue, then echo (pre-ready probes are
  discarded; only post-ready probes echo)
- dialog: print an onboarding marker, sleep, remove it, then echo (the
  probe must answer the dialog inline and exclude its time from the gap)
- editor-residue: the editor-residue shape — a "transcript" row holding
  probe fragments renders ABOVE the editor (the live nav diagnostic's
  state: a polluted submit left token text in the transcript while the
  editor itself is clean); used to pin the erase gate's scope.
- editor / editor-cu / editor-stuck: sleep R, then a real line editor —
  a buffer with a full-region redraw at the true terminal width
  (wrapped rows included), DEL/backspace pops one char and redraws,
  and this editor never submits. Pre-ready input stays queued in the
  PTY buffer and lands in the editor at mount (the buffered-products
  shape). "editor" leaves Ctrl-U unbound (the products do not share
  that binding): erase must fall back to the DEL burst. "editor-cu" is
  the Pi counterexample shape: DEL is ignored but Ctrl-U kills the
  line, so the Ctrl-U-first order is what clears it. "editor-stuck"
  ignores both: erase must report failure there, never a false success.
- dialog-script: a product's OWN onboarding walk, offline. argv:
  [mode, spec.json] where spec is {"steps": [{"marker": str,
  "keys": [str, ...]}]} — the resolved dialog_steps of an adapter
  (markers + keystroke-resolved bytes). The TUI shows each marker row,
  consumes exactly the expected key sequence in order (a wrong byte
  resets the sequence — the dialog never advances on wrong keys), then
  clears the row and shows the next; after the last it echoes (ready).
  Editor-qualification tests drive this with claude/codex/pi dialog
  configs: the harness dialog walk must reach ready against the
  product's own markers and keys, with zero product involvement.
"""
import os
import sys
import termios
import time
import tty

mode = sys.argv[1]


def _arg(idx, default, cast):
    # dialog-script takes a spec path in argv[2]: numeric-only slots fall
    # back to their default instead of raising (existing modes always
    # pass numerics, so their behavior is unchanged)
    try:
        return cast(sys.argv[idx])
    except (ValueError, IndexError):
        return default


delay = _arg(2, 0.3, float)
width = _arg(3, 120, int)
MARKER = "Share agent traces with Prime Intellect?"

fd = sys.stdin.fileno()
tty.setraw(fd)  # raw from the start: no kernel echo of typed probes
banner = "\r\n  FAKE-TUI READY\r\n"
if mode == "dialog":
    sys.stdout.write("\r\n  " + MARKER + "\r\n"); sys.stdout.flush()
    time.sleep(delay)
    # remove the marker's own line (the cursor sits one row below it)
    sys.stdout.write("\x1b[1A\r\x1b[K"); sys.stdout.flush()
elif mode == "dialog-script":
    import json
    spec = json.loads(open(sys.argv[2]).read())
    steps = [(s["marker"],
              b"".join(k.encode("latin-1") for k in s["keys"]))
             for s in spec.get("steps", [])]
    if steps:
        sys.stdout.write("\r\n  " + steps[0][0] + "\r\n"); sys.stdout.flush()
    expected, pos, cur = (steps[0][1] if steps else b""), 0, 0
    while cur < len(steps):
        data = os.read(fd, 4096)
        if not data:
            break
        for b in data:
            if pos < len(expected) and b == expected[pos]:
                pos += 1
            else:
                pos = 0  # wrong key resets the sequence; the dialog waits
            if expected and pos >= len(expected):
                # answered: remove the marker's own line, show the next
                sys.stdout.write("\x1b[1A\r\x1b[K"); sys.stdout.flush()
                cur += 1
                pos = 0
                if cur < len(steps):
                    sys.stdout.write("\r\n  " + steps[cur][0] + "\r\n")
                    sys.stdout.flush()
                    expected = steps[cur][1]
                else:
                    expected = b""
                break
    sys.stdout.write(banner); sys.stdout.flush()
else:
    sys.stdout.write(banner); sys.stdout.flush()
    time.sleep(delay)
if mode == "dropped":
    termios.tcflush(fd, termios.TCIFLUSH)  # discard the queued probes
if mode == "editor-residue":
    # a polluted submitted message above the editor (probe fragments in
    # the "transcript" region; the editor itself is clean below)
    sys.stdout.write("\r\n  user: Zq7r03Zq7r04 hello agents view please\r\n")
    sys.stdout.flush()

try:
    if mode.startswith("editor"):
        PROMPT = "> "
        buf = ""
        prev_rows = 1
        stuck = mode == "editor-stuck"
        del_ignored = mode in ("editor-cu", "editor-stuck")

        def redraw():
            global prev_rows
            out = "\r"
            if prev_rows > 1:
                out += "\x1b[%dA" % (prev_rows - 1)
            out += "\x1b[J" + PROMPT + buf  # clear the region, print the line
            sys.stdout.write(out)
            sys.stdout.flush()
            prev_rows = max(1, -(-(len(PROMPT) + len(buf)) // width))

        while True:
            data = os.read(fd, 4096)
            if not data:
                break
            for b in data:
                if b == 0x7F:  # DEL/backspace
                    if not del_ignored and buf:
                        buf = buf[:-1]
                elif b == 0x15:  # Ctrl-U: kill-line (bound unless plain)
                    if not stuck:
                        buf = ""
                elif 0x20 <= b < 0x7F:
                    buf += chr(b)
                # every other byte (escape sequences, \r, ...) is ignored:
                # this editor never submits and binds no extras
            redraw()
    else:
        while True:
            data = os.read(fd, 4096)
            if not data:
                break
            os.write(1, data)  # echo back exactly what was read
            sys.stdout.flush()
finally:
    termios.tcsetattr(fd, termios.TCSADRAIN, termios.tcgetattr(fd))
