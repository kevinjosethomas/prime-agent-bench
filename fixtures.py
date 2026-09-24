#!/usr/bin/env python3
"""Deterministic Prime session fixtures (S grid) for the benchmark suite.

Row schema is the parity-proven scale_corpus.py family: session header,
message rows (user/assistant/toolResult), custom_message harness-digest
rows. Extended with realistic markdown-scale payloads and a visible tail
sentinel. Exact on-disk bytes per tier; sha256 manifest.

Not part of any product. Benchmark harness only.
"""
from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

T0 = 1789584016603


def _ts(index: int) -> str:
    return "2026-09-16T18:%02d:%02d.%03dZ" % ((index // 60) % 60, index % 60, index % 1000)


_WORDS = (
    "session kernel daemon roster streaming latency benchmark transcript compaction "
    "viewport scroll keystroke echo render frame terminal protocol catalog resume "
    "fixture corpus sentinel parity throughput snapshot restore venv bootstrap "
    "process memory settle jitter burst pacing cadence markdown thinking tools "
).split()


def _paragraph(rng: random.Random, sentences: int) -> str:
    out = []
    for _ in range(sentences):
        n = rng.randint(9, 22)
        words = [rng.choice(_WORDS) for _ in range(n)]
        out.append(" ".join(words).capitalize() + ".")
    return " ".join(out)


def _markdown_block(rng: random.Random, paras: int) -> str:
    parts = []
    for i in range(paras):
        parts.append(_paragraph(rng, rng.randint(3, 7)))
        if i % 2 == 1:
            parts.append("```python\nresult = [f(x) for x in range(20)]\nprint(sorted(result))\n```")
        if i % 3 == 2:
            parts.append("- " + "\n- ".join(_paragraph(rng, 1) for _ in range(4)))
    return "\n\n".join(parts)


def _ipython_code(turn: int) -> str:
    return (
        "import subprocess\n"
        f"result = subprocess.run(['echo', 'corpus {turn}'], capture_output=True, text=True)\n"
        "print(result.stdout.strip())\n"
        "files = [f for f in range(3)]\n"
        "print(sorted(files))\n"
    )


def _usage(extra: int = 0) -> dict:
    return {
        "input": 100 + extra,
        "output": 20 + extra,
        "cacheRead": 10,
        "cacheWrite": 0,
        "totalTokens": 130 + extra,
        "cost": {"input": 0.1, "output": 0.02, "cacheRead": 0, "cacheWrite": 0, "total": 0.12},
    }


def generate_rows(turns: int, cwd: str, seed: int = 1234, big_markdown: bool = True):
    """The corpus entries for `turns` turns (session header included)."""
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
                    "timestamp": T0 + turn,
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
                    "timestamp": T0 + turn,
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
                    "timestamp": T0 + turn,
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


def append_tail_sentinel(lines, cwd, sentinel: str):
    """The final user + assistant pair carrying the visible tail sentinel."""
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
        {"message": {"role": "user", "content": [{"type": "text", "text": "final marker request"}], "timestamp": T0}},
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
                "timestamp": T0,
            }
        },
        next_id(),
        1,
    )
    lines.append(record)
    return lines


def build_session(size_mib: float, out_path: Path, cwd: str, seed: int = 1234) -> dict:
    """Write the deterministic session fixture of exactly `size_mib` MiB."""
    target = int(round(size_mib * (1 << 20)))
    sentinel = "CORPUS-TAIL-9f3a1c70"
    rng = random.Random(seed)

    def serialize(rows):
        return ("\n".join(json.dumps(r) for r in rows) + "\n").encode()

    # stage 1: size the turn count from a 64-turn probe (per-turn bytes are
    # uniform enough for one proportional step, then exact pad closes the gap)
    probe = generate_rows(64, cwd, seed=seed)
    per_turn = len(serialize(probe)) / 64.0
    turns = max(64, int(target * 0.90 / per_turn))
    lines = generate_rows(turns, cwd, seed=seed)
    lines = append_tail_sentinel(lines, cwd, sentinel)
    data = serialize(lines)

    # stage 2: pad the sentinel row with safe single-byte chars to the exact
    # target (JSON-escape-free text: word padding then 'x' correction)
    for _ in range(6):
        delta = target - len(data)
        if delta == 0:
            break
        for row in lines:
            content = (row.get("message") or {}).get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                text = part.get("text", "")
                if "PAD_PLACEHOLDER" in text:
                    if delta > 0:
                        words = " ".join(rng.choice(_WORDS) for _ in range(delta // 6 + 2))[:delta]
                        part["text"] = "PAD_PLACEHOLDER " + words + " " + sentinel + " end of corpus."
                    else:
                        part["text"] = "PAD_PLACEHOLDER " + sentinel + " end of corpus."
        if delta < 0:
            # oversized: shrink turns proportionally and rebuild
            turns = max(1, int(turns * (target * 0.88) / len(data)))
            lines = generate_rows(turns, cwd, seed=seed)
            lines = append_tail_sentinel(lines, cwd, sentinel)
        data = serialize(lines)
    # final exact correction with unambiguous 'x'
    delta = target - len(data)
    if delta > 0:
        for row in lines:
            content = (row.get("message") or {}).get("content")
            if isinstance(content, list):
                for part in content:
                    if "PAD_PLACEHOLDER" in part.get("text", ""):
                        part["text"] = ("x" * (delta - 1)) + " " + part["text"]
        data = serialize(lines)

    out_path.write_bytes(data)
    n = 0
    with open(out_path) as f:
        for line in f:
            json.loads(line)
            n += 1
    return {
        "path": str(out_path),
        "bytes": out_path.stat().st_size,
        "sha256": hashlib.sha256(data).hexdigest(),
        "rows": n,
        "sentinel": sentinel,
        "generator_seed": seed,
        "target_mib": size_mib,
    }


if __name__ == "__main__":
    import sys

    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/scale-corpus-10mib.jsonl")
    mib = float(sys.argv[2]) if len(sys.argv) > 2 else 10.0
    info = build_session(mib, out, cwd="/home/ubuntu/bench/fixtures/work")
    print(json.dumps(info, indent=1))
    assert info["bytes"] == int(mib * (1 << 20)), info["bytes"]
    print("EXACT-BYTES-OK")
