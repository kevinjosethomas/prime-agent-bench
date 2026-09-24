"""Concrete adapters, auto-discovered by bench.core.registry.discover().

One self-contained folder per harness -- bench/adapters/<name>/ with
adapter.py, product.yaml, and README.md -- plus the generic kind
packages: benchmarks/, fixtures/, terminals/ (one adapter per file).
The kind names are reserved: a harness folder must not share one.
Adding a harness = one folder; adding any other adapter = one file.
"""
