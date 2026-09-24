"""Deterministic Prime session-row generators (the parity-proven schema).

Row schema: session header, message rows (user/assistant/toolResult),
custom_message harness-digest rows. Shared by the session-size and
subagent-tree fixtures.
"""
from __future__ import annotations

from bench.adapters.fixtures.corpus_text import (_ipython_code, _markdown_block,
                                                 _paragraph, _ts, _usage)

#: The canonical session-header cwd recorded inside every generated fixture
#: (audit 2026-09-24: the recorded cwd was the host's absolute fixtures/work
#: path, so the fixture bytes — and the golden sha256 — changed with every
#: sandbox root; the smoke run produced 8f8979d9... where the campaign
#: canonical was f8d7fba0...). A fixed logical path makes the corpus
#: byte-identical on every host; the directory is created at build time so
#: products resuming the transcript never see a recorded cwd that does
#: not exist.
FIXTURE_SESSION_CWD = "/tmp/prime-agent-bench-session"


def ensure_fixture_cwd(cwd: str = FIXTURE_SESSION_CWD) -> None:
    """Create the recorded session cwd so resume semantics stay honest."""
    from pathlib import Path
    Path(cwd).mkdir(parents=True, exist_ok=True)


def digest_row_fields(note: str, digest_display: bool | None) -> dict:
    """The harness_digest custom_message fields for one corpus note.

    ``digest_display=None`` (fixture v2) omits the visibility keys: the
    product renderers fall back to visible for a missing key, so v2
    digest rows render as panels. Any other value (fixture v3 passes
    ``False``) mirrors what BOTH real products persist — TS
    ``createHarnessDigestMessage`` (messages.ts:141-153) and Rust
    ``harness_digest_prompt_row``/``persist_digest``
    (harness_digest.rs:117-145) write ``display: false`` plus the raw
    digest in ``details`` — so the rows replay hidden exactly like real
    session files.
    """
    fields = {
        "customType": "harness_digest",
        "content": f"[harness-digest] {note}",
    }
    if digest_display is None:
        return fields
    return {**fields, "display": digest_display, "details": {"digest": note}}


def generate_rows(turns: int, cwd: str, seed: int = 1234, big_markdown: bool = True,
                  digest_display: bool | None = None) -> list:
    """The corpus entries for ``turns`` turns (session header included).

    ``cwd`` must be the canonical ``FIXTURE_SESSION_CWD`` (or an explicit
    test override): a host-specific path bakes into the header row and
    breaks byte reproducibility across bench roots and sandboxes.

    ``digest_display`` selects the harness-digest row schema (see
    ``digest_row_fields``): ``None`` (the default) builds the byte-stable
    v2 corpus; ``False`` builds the display-corrected v3 corpus
    (session-size/3)."""
    import random

    rng = random.Random(seed)
    lines = [
        {
            "type": "session",
            "id": "scale-corpus",
            "version": 3,
            "timestamp": "2026-09-16T18:40:16.600Z",
            "cwd": cwd,
            "rlmDepth": 0,
        }
    ]
    parent = None

    def entry(entry_type, fields, entry_id, index):
        record = dict(fields)
        record["type"] = entry_type
        record["id"] = entry_id
        record["parentId"] = parent
        record["timestamp"] = _ts(index)
        return record

    counter = 0

    def next_id():
        nonlocal counter
        counter += 1
        return f"{counter:08x}"[:8]

    for base in range(11):
        record = entry(
            "custom_message",
            digest_row_fields(f"base note {base}: persistent state summary for the scale corpus.",
                              digest_display),
            next_id(),
            counter,
        )
        lines.append(record)
        parent = record["id"]

    for turn in range(turns):
        record = entry(
            "message",
            {
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": f"please do task number {turn}"}],
                    "timestamp": 1789584016603 + turn,
                }
            },
            next_id(),
            counter,
        )
        lines.append(record)
        parent = record["id"]

        assistant_text = (
            _markdown_block(rng, rng.randint(2, 5)) if big_markdown and turn % 3 == 0
            else f"Running the tool for task {turn}. " + _paragraph(rng, rng.randint(2, 5))
        )
        record = entry(
            "message",
            {
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "thinking", "thinking": f"task {turn}: run the corpus command"},
                        {"type": "text", "text": assistant_text},
                    ],
                    "toolCalls": [
                        {
                            "id": f"call_{turn:06d}",
                            "name": "ipython",
                            "arguments": {"code": _ipython_code(turn)},
                        }
                    ],
                    "api": "openai-completions",
                    "provider": "prime-inference",
                    "model": "mock-1",
                    "usage": _usage(),
                    "stopReason": "tool_calls",
                    "timestamp": 1789584016603 + turn,
                }
            },
            next_id(),
            counter,
        )
        lines.append(record)
        parent = record["id"]

        record = entry(
            "message",
            {
                "message": {
                    "role": "toolResult",
                    "toolCallId": f"call_{turn:06d}",
                    "content": [{"type": "text", "text": f"corpus {turn}\n[0, 1, 2]\n"}],
                    "isError": False,
                    "timestamp": 1789584016603 + turn,
                }
            },
            next_id(),
            counter,
        )
        lines.append(record)
        parent = record["id"]

        if (turn + 1) % 20 == 0:
            record = entry(
                "custom_message",
                digest_row_fields(f"note {turn}: persistent state summary for the scale corpus.",
                                  digest_display),
                next_id(),
                counter,
            )
            lines.append(record)
            parent = record["id"]

    return lines


def append_tail_sentinel(lines: list, cwd: str, sentinel: str) -> list:
    """Append the final user + assistant pair carrying the visible tail sentinel."""
    parent = lines[-1]["id"]

    def entry(entry_type, fields, entry_id, index):
        record = dict(fields)
        record["type"] = entry_type
        record["id"] = entry_id
        record["parentId"] = parent
        record["timestamp"] = _ts(index + 1000)
        return record

    counter = 100000

    def next_id():
        nonlocal counter
        counter += 1
        return f"{counter:08x}"[:8]

    record = entry(
        "message",
        {"message": {"role": "user", "content": [{"type": "text", "text": "final marker request"}], "timestamp": 1789584016603}},
        next_id(),
        0,
    )
    lines.append(record)
    parent = record["id"]

    record = entry(
        "message",
        {
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "final marker"},
                    {"type": "text", "text": "PAD_PLACEHOLDER " + sentinel + " end of corpus."},
                ],
                "api": "openai-completions",
                "provider": "prime-inference",
                "model": "mock-1",
                "usage": _usage(),
                "stopReason": "stop",
                "timestamp": 1789584016603,
            }
        },
        next_id(),
        1,
    )
    lines.append(record)
    return lines
