"""Seeded prose generators for the deterministic session corpus.

Word salad paragraphs, markdown blocks, code cells, and usage records —
all deterministic under a fixed seed so fixtures are byte-reproducible.
"""
from __future__ import annotations

import random

T0 = 1789584016603

_WORDS = (
    "session kernel daemon roster streaming latency benchmark transcript compaction "
    "viewport scroll keystroke echo render frame terminal protocol catalog resume "
    "fixture corpus sentinel parity throughput snapshot restore venv bootstrap "
    "process memory settle jitter burst pacing cadence markdown thinking tools "
).split()


def _ts(index: int) -> str:
    """A deterministic ISO timestamp for row ``index``."""
    return "2026-09-16T18:%02d:%02d.%03dZ" % ((index // 60) % 60, index % 60, index % 1000)


def _paragraph(rng: random.Random, sentences: int) -> str:
    """A seeded word-salad paragraph of ``sentences`` sentences."""
    out = []
    for _ in range(sentences):
        n = rng.randint(9, 22)
        words = [rng.choice(_WORDS) for _ in range(n)]
        out.append(" ".join(words).capitalize() + ".")
    return " ".join(out)


def _markdown_block(rng: random.Random, paras: int) -> str:
    """A seeded markdown block: paragraphs, code fences, bullet lists."""
    parts = []
    for i in range(paras):
        parts.append(_paragraph(rng, rng.randint(3, 7)))
        if i % 2 == 1:
            parts.append("```python\nresult = [f(x) for x in range(20)]\nprint(sorted(result))\n```")
        if i % 3 == 2:
            parts.append("- " + "\n- ".join(_paragraph(rng, 1) for _ in range(4)))
    return "\n\n".join(parts)


def _ipython_code(turn: int) -> str:
    """The seeded tool-call code cell for ``turn``."""
    return (
        "import subprocess\n"
        f"result = subprocess.run(['echo', 'corpus {turn}'], capture_output=True, text=True)\n"
        "print(result.stdout.strip())\n"
        "files = [f for f in range(3)]\n"
        "print(sorted(files))\n"
    )


def _usage(extra: int = 0) -> dict:
    """A deterministic token-usage record."""
    return {
        "input": 100 + extra,
        "output": 20 + extra,
        "cacheRead": 10,
        "cacheWrite": 0,
        "totalTokens": 130 + extra,
        "cost": {"input": 0.1, "output": 0.02, "cacheRead": 0, "cacheWrite": 0, "total": 0.12},
    }
