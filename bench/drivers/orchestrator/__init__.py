"""The multi-sandbox parallel orchestrator (iteration mode).

One Prime VM sandbox per benchmark type, all products sequentially within
each sandbox (cross-product fairness on identical hardware), a canonical
reference benchmark compared across sandboxes to catch stragglers, and a
per-sandbox A/A pass before the real waves. The single-node sequential
runner stays the gold standard for published numbers.
"""
from bench.drivers.orchestrator.backend import (PrimeSandboxBackend,
                                                SandboxBackend, SandboxHandle)
from bench.drivers.orchestrator.backend_local import LocalSandboxBackend
from bench.drivers.orchestrator.plan import (load_parallel_config, make_backend,
                                             plan_sandboxes)
from bench.drivers.orchestrator.reference import (REFERENCE_CODE,
                                                  compare_references,
                                                  run_reference)
from bench.drivers.orchestrator.run import run_parallel

__all__ = ["SandboxBackend", "SandboxHandle", "PrimeSandboxBackend",
           "LocalSandboxBackend", "load_parallel_config",
           "make_backend", "plan_sandboxes", "REFERENCE_CODE", "run_reference",
           "compare_references", "run_parallel"]
