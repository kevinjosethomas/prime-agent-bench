"""Core abstractions: adapters, registry, config, measurement, environment.

Everything the orchestrator wires together is declared here as an ABC:
ProductAdapter, Benchmark, HarnessDriver/Session, Fixture, plus the
registry that auto-discovers concrete adapters from ``bench.adapters``.
"""
