"""Plugin registry: auto-discovers adapters from the package structure.

Products live one folder per product (``bench/adapters/products/<name>/
{adapter.py, product.yaml, README.md}``); benchmarks, harness drivers, and
fixtures stay one file each. Adapter classes (subclasses of the core ABCs
defined in that module) register by their ``name``. No registration file
to maintain: adding a product = adding one folder, adding any other
adapter = adding one file.
"""
from __future__ import annotations

import importlib
import pkgutil

from bench.core.benchmark import Benchmark
from bench.core.config import product_config
from bench.core.env import BenchLayout
from bench.core.fixture import Fixture
from bench.core.harness import HarnessDriver
from bench.core.product import ProductAdapter

ADAPTER_KINDS: dict[str, type] = {
    "products": ProductAdapter,
    "benchmarks": Benchmark,
    "harnesses": HarnessDriver,
    "fixtures": Fixture,
}


class Registry:
    """The discovered, instantiated adapter sets for one config."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.layout = BenchLayout.from_config(cfg)
        self.products: dict[str, ProductAdapter] = {}
        self.benchmarks: dict[str, Benchmark] = {}
        self.harnesses: dict[str, HarnessDriver] = {}
        self.fixtures: dict[str, Fixture] = {}

    # typed accessor helpers ------------------------------------------------
    def product(self, name: str) -> ProductAdapter:
        return self.products[name]

    def benchmark(self, name: str) -> Benchmark:
        return self.benchmarks[name]

    def fixture(self, name: str) -> Fixture:
        return self.fixtures[name]

    def driver(self, name: str | None = None) -> HarnessDriver:
        return self.harnesses[name or self.cfg["driver"]]

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


def discover(cfg: dict) -> Registry:
    """Import every adapter and instantiate the adapters it defines.

    Products live one folder per product (``bench/adapters/products/
    <name>/adapter.py`` + ``product.yaml``); the other kinds stay
    one file per adapter."""
    reg = Registry(cfg)
    for kind, base in ADAPTER_KINDS.items():
        package = importlib.import_module(f"bench.adapters.{kind}")
        for info in pkgutil.iter_modules(package.__path__):
            if info.name.startswith("_"):
                continue
            if kind == "products" and info.ispkg:
                module = importlib.import_module(
                    f"bench.adapters.products.{info.name}.adapter")
                _register_module(reg, cfg, kind, base, module)
                continue
            if kind == "products":
                continue  # flat product files are gone: folders only
            module = importlib.import_module(f"bench.adapters.{kind}.{info.name}")
            _register_module(reg, cfg, kind, base, module)
    return reg
