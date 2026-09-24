"""The Analyzer ABC: one results artifact format = one adapter.

compute_stats shares one stats model (analysis.aggregate) across formats,
so JSON, markdown, and Notion analyzers never recompute; format_output
renders it. Adding a format = one file under analysis/output/.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class Analyzer(ABC):
    """A results-artifact builder over the shared summary model."""

    name: str = ""

    def __init__(self, cfg: dict):
        """cfg keys: product_order, display, aa (threshold), results_dir."""
        self.cfg = cfg

    def compute_stats(self, rows: list) -> dict:
        """The shared stats model: {"summary": ..., "aa": ...}."""
        from bench.analysis.aggregate import summarize_rows
        return summarize_rows(rows, self.cfg)

    @abstractmethod
    def format_output(self, stats: dict) -> str:
        """The rendered artifact (written by the caller)."""
