"""Deterministic Prime session-row generators (the parity-proven schema).

Row schema: session header, message rows (user/assistant/toolResult),
custom_message harness-digest rows. Shared by the session-size and
subagent-tree fixtures.
"""
from __future__ import annotations

from bench.adapters.fixtures.corpus_text import (_ipython_code, _markdown_block,
                                                 _paragraph, _ts, _usage)


def generate_rows(turns: int, cwd: str, seed: int = 1234, big_markdown: bool = True) -> list:
    """The corpus entries for ``turns`` turns (session header included)."""
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
            {
                "customType": "harness_digest",
                "content": f"[harness-digest] base note {base}: persistent state summary for the scale corpus.",
            },
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
                {
                    "customType": "harness_digest",
                    "content": f"[harness-digest] note {turn}: persistent state summary for the scale corpus.",
                },
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
