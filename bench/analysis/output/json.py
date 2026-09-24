"""The JSON results analyzer (summary.json)."""
from __future__ import annotations

import json

from bench.core.analyzer import Analyzer


class JsonAnalyzer(Analyzer):
    """Serializes the stats model verbatim."""

    name = "json"

    def format_output(self, stats: dict) -> str:
        """The indented JSON artifact."""
        return json.dumps(stats, indent=1)
