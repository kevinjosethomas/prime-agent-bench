"""Plugin registry: auto-discovers adapters from the package structure.

Each harness lives in one self-contained folder directly under
bench/adapters/ (``bench/adapters/<name>/{adapter.py, product.yaml,
README.md}``); the generic kinds -- benchmark scenarios, fixtures,
terminal drivers -- stay one adapter per file in their kind package
(benchmarks/, fixtures/, terminals/). Adapter classes (subclasses of the
core ABCs) register by their ``name``. No registration file to
maintain: adding a harness = adding one folder, adding any other
adapter = adding one file.
"""
from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

from bench.core.benchmark import Benchmark
from bench.core.config import product_config
from bench.core.env import BenchLayout
from bench.core.fixture import Fixture
from bench.core.harness import HarnessDriver
from bench.core.product import ProductAdapter

#: the generic adapter kinds: one package under bench/adapters/, one
#: adapter per module inside it; kind names are reserved for harness
#: folders
ADAPTER_KINDS: dict[str, type] = {
    "benchmarks": Benchmark,
    "fixtures": Fixture,
    "terminals": HarnessDriver,
}

#: the file that makes a bench/adapters/<name>/ folder a harness
HARNESS_ENTRY = "adapter.py"


class Registry:
    """The discovered, instantiated adapter sets for one config."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.layout = BenchLayout.from_config(cfg)
        self.products: dict[str, ProductAdapter] = {}
        self.benchmarks: dict[str, Benchmark] = {}
        self.terminals: dict[str, HarnessDriver] = {}
        self.fixtures: dict[str, Fixture] = {}

    # typed accessor helpers ------------------------------------------------
    def product(self, name: str) -> ProductAdapter:
        return self.products[name]

    def benchmark(self, name: str) -> Benchmark:
        return self.benchmarks[name]

    def fixture(self, name: str) -> Fixture:
        return self.fixtures[name]

    def driver(self, name: str | None = None) -> HarnessDriver:
        """The terminal driver (default: cfg["driver"])."""
        return self.terminals[name or self.cfg["driver"]]

    # registration -----------------------------------------------------------
    def _register(self, kind: str, instance) -> None:
        table = getattr(self, kind)
        if not getattr(instance, "name", ""):
            raise ValueError(f"{kind} adapter {type(instance).__name__} has no name")
        if instance.name in table:
            raise ValueError(f"duplicate {kind} adapter name: {instance.name}")
        table[instance.name] = instance


def adapter_cfg(cfg: dict, kind: str, name: str) -> dict:
    """The constructor config slice for one adapter."""
    layout = BenchLayout.from_config(cfg)
    slice_ = {"layout": layout, "product": product_config(name),
              "mock": cfg.get("mock", {})}
    if kind == "fixtures":
        slice_["fixture"] = cfg.get("fixtures", {}).get(name, {})
    if kind == "benchmarks":
        # per-benchmark overrides (configs/default.yaml ``benchmarks:``)
        # must reach the adapter __init__s, which slice their own entry
        # by name (ready_timeout_s, sentinel_timeout_s, ...)
        slice_["benchmarks"] = cfg.get("benchmarks", {})
    return slice_


def _register_module(reg: Registry, cfg: dict, kind: str, base: type,
                      module) -> None:
    """Instantiate every adapter class a module defines."""
    for obj in vars(module).values():
        if (isinstance(obj, type) and obj is not base
                and obj.__module__ == module.__name__
                and issubclass(obj, base)):
            instance = obj(adapter_cfg(cfg, kind, obj.name))
            reg._register(kind, instance)


def _discover_kind(reg: Registry, cfg: dict, kind: str, base: type) -> None:
    """One kind package: register every adapter module inside it."""
    package = importlib.import_module(f"bench.adapters.{kind}")
    for info in pkgutil.iter_modules(package.__path__):
        if info.name.startswith("_"):
            continue
        module = importlib.import_module(f"bench.adapters.{kind}.{info.name}")
        _register_module(reg, cfg, kind, base, module)


def discover(cfg: dict) -> Registry:
    """Import every adapter and instantiate the adapters it defines.

    Harnesses live one folder per harness directly under bench/adapters/
    (``<name>/adapter.py`` + ``<name>/product.yaml``); the generic kinds
    stay one adapter per file in their kind package. Anything else under
    bench/adapters/ fails loudly: the tree is self-policing."""
    reg = Registry(cfg)
    adapters = importlib.import_module("bench.adapters")
    root = Path(next(iter(adapters.__path__)))
    for info in sorted(pkgutil.iter_modules([str(root)]),
                       key=lambda entry: entry.name):
        if info.name.startswith("_"):
            continue
        if info.name in ADAPTER_KINDS:
            _discover_kind(reg, cfg, info.name, ADAPTER_KINDS[info.name])
        elif info.ispkg and (root / info.name / HARNESS_ENTRY).exists():
            module = importlib.import_module(f"bench.adapters.{info.name}.adapter")
            _register_module(reg, cfg, "products", ProductAdapter, module)
        else:
            raise ValueError(
                f"bench/adapters/{info.name}: expected a harness folder with "
                f"{HARNESS_ENTRY} or one of the kind packages "
                f"{sorted(ADAPTER_KINDS)}")
    return reg
