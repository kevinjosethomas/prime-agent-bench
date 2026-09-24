"""The Benchmark ABC: one benchmark scenario = one self-contained file.

Measurement semantics stay the suite spec: launch = exec boundary; first
paint = first non-blank rendered frame; interactive-ready = typed token
echoed AND accepted AND erased (no submit); wall clock = monotonic
controller-side seconds (ms reported). Adding a benchmark = one file under
bench/adapters/benchmarks/.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

from bench.core.product import ProductAdapter, TrialContext

if TYPE_CHECKING:  # pragma: no cover
    from bench.core.harness import HarnessDriver


class Benchmark(ABC):
    """A scenario measured against one product per trial.

    ``measure`` fills ``record["metrics"]`` (plus validation/resource
    evidence); the runner owns isolation, ordering, and JSONL writes.
    """

    name: str = ""
    default_trials: int = 10
    applicable_products: list[str] | None = None  # None = every product
    requires_fixture: str | None = None            # registry fixture name

    def __init__(self, cfg: dict):
        self.cfg = cfg

    def applicable(self, product_name: str) -> bool:
        """Whether this benchmark applies to the product."""
        return self.applicable_products is None or product_name in self.applicable_products

    def setup(self, product: ProductAdapter, ctx: TrialContext,
              fixture: Path | None = None) -> None:
        """Prepare the trial before measurement (default: nothing)."""

    @abstractmethod
    def measure(self, product: ProductAdapter, ctx: TrialContext, record: dict,
                driver: HarnessDriver, fixture: Path | None = None) -> None:
        """Run one trial and fill the record."""

    def validate(self, record: dict) -> bool:
        """Whether the trial's evidence block proves the measurement."""
        return all(bool(v) for v in (record.get("validation") or {}).values())
