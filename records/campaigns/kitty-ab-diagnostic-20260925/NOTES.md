# Kitty keyboard A/B diagnostic - root cause proof (2026-09-25)

Pinned Rust fa9395128 / binary e61c5ca7. 6/6 clean trials, wire-nonce receipts + visible scripted replies.
One anomalous unanswered trial (167.9ms, 4-trial preliminary run, no query tracking) EXCLUDED with caveat.

## The result
| Journey leg | Unanswered PTY | Answered (kitty CSI?1u) |
|---|---|---|
| Keyboard probe settle | ~2000ms (timeout burn) | 54.7-55.1ms |
| First typed key rendered | 1997-2008ms | 0.9ms |
| Enter -> provider wire | 2034-2059ms | 153.8-175.9ms |
| Launch -> full reply rendered | 2116.2-2119.5ms | 427.0-449.3ms |

Mechanism: crossterm supports_keyboard_enhancement() polls 2000ms for CSI?u; while waiting,
its shared internal event reader blocks ALL app key reads. Field evidence: Kevin Ghostty
screen recording (chrome 250ms, typed text visible as typed, submit ~1.1s) matches the
answered path. Campaign cmp5b readiness rows (rust 2068/2045ms cold/warm) measured the
unanswered-PTY worst case.

Implications: (1) the current 150ms fallback does NOT unblock crossterm's shared reader
(only the library poll returning unblocks it) - a genuinely bounded query or crossterm
upgrade is a PROPOSED product change whose recovery must be proven by its own A/B;
(2) harness needs terminal-realism mode (answered-PTY driver) and a re-measure of
readiness rows in both worlds; (3) Kevin experience validated by lab + field;
(4) the answered-vs-unanswered legs also differ in key encoding (CSI-u vs legacy) and
carry +200ms deliberate pacing on the answered leg - report exact boundaries, do not
attribute the launch-to-reply delta solely to the probe timeout.
