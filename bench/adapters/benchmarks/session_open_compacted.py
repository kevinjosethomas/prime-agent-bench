"""session.cold_open_10mib_compacted: cold open of the compacted-boundary fixture.

Same driver and ready contract as session.cold_open_10mib (typed-echo
ready, tail-sentinel proof); the fixture differs only by one
byte-plausible compaction boundary row whose retained window is the
~100KiB tail, so the pair isolates the product's windowed fast path
from the no-boundary full-parse path at the same corpus size. The
stock suite's semantics are unchanged (spec §A: session.* is RT-only).
"""
from __future__ import annotations

from bench.adapters.benchmarks.session_open import SessionColdOpen


class SessionColdOpenCompacted(SessionColdOpen):
    """Cold open of the compacted-boundary 10MiB fixture -> interactive."""

    name = "session.cold_open_10mib_compacted"
    requires_fixture = "session-10mib-compacted"
    applicability_note = ("resumes the compacted-boundary Prime session fixture; "
                          "BENCHMARK_SUITE_SPEC §A scopes session.* to Prime Agent Rust/TS")
