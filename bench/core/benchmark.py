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

#: Spec §F comparability levels, shown per cross-product row. Only
#: ``not_comparable`` rows are never ranked (they carry a status, no numbers).
COMPARABILITY_LEVELS = ("equivalent", "qualified", "not_comparable")


class Benchmark(ABC):
    """A scenario measured against one product per trial.

    ``measure`` fills ``record["metrics"]`` (plus validation/resource
    evidence); the runner owns isolation, ordering, and JSONL writes.
    """

    name: str = ""
    default_trials: int = 10
    applicable_products: list[str] | None = None  # None = every product
    applicability_note: str = ""  # why non-applicable products are excluded (status rows)
    requires_fixture: str | None = None            # registry fixture name
    # Metrics that must be truthy for the trial to count as completed
    # (the analysis validity gate excludes rows whose completeness keys
    # are falsy, e.g. scroll_typing's typing_ok after a dropped key).
    completeness_keys: tuple[str, ...] = ()
    # Additional metrics (beyond the primary) that must pass the A/A
    # noise floor whenever they are published (the analysis stability
    # gate refuses to rank a product whose A/A spread fails).
    aa_metrics: tuple[str, ...] = ()

    def __init__(self, cfg: dict):
        self.cfg = cfg

    def applicable(self, product_name: str) -> bool:
        """Whether this benchmark applies to the product."""
        return self.applicable_products is None or product_name in self.applicable_products

    def comparability(self, product: ProductAdapter,
                      fixture: Path | None = None) -> tuple[str, str]:
        """(level, reason) for this benchmark x product per spec §F.

        ``equivalent``: identical PTY + user action, the fixture semantically
        verified (sha256/rows/sentinel evidence on every trial row).
        ``qualified``: equivalent user intent, distinct product UI/daemon.
        ``not_comparable``: unsupported here — the product cannot consume the
        fixture (its argv ignores resume_fixture and no vendor-native fixture
        exists yet). The trial engine records such rows as status, never as
        numbers, and nothing ranks them.
        """
        if self.requires_fixture:
            if not product.resume_fixture_capable:
                return ("not_comparable",
                        f"{product.name} has no native {self.requires_fixture} fixture: its argv "
                        "ignores resume_fixture, and spec §F large-session rows require a "
                        "vendor-native fixture (sentinel + message count equivalence)")
            return ("equivalent",
                    "identical PTY + user action; fixture sha256/rows/sentinel verified per trial")
        return ("qualified", "equivalent user intent; distinct product UI/daemon (spec §F)")

    def setup(self, product: ProductAdapter, ctx: TrialContext,
              fixture: Path | None = None) -> None:
        """Prepare the trial before measurement (default: nothing)."""

    @abstractmethod
    def measure(self, product: ProductAdapter, ctx: TrialContext, record: dict,
                driver: HarnessDriver, fixture: Path | None = None) -> None:
        """Run one trial and fill the record."""

    def validate(self, record: dict) -> bool:
        """Whether the trial's evidence block proves the measurement.

        A scored row must carry its evidence: a missing or empty validation
        block is NOT valid (the audit's missing-validation class — kernel.*
        and daemon.boot rows passed with no proof at all). Every scenario
        must record a validation block; the analysis gate additionally
        rejects rows whose ``validated`` is absent.
        """
        evidence = record.get("validation")
        return bool(evidence) and all(bool(v) for v in evidence.values())
