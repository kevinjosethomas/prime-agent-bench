"""The Fixture ABC: deterministic, byte-exact session/state generators.

generate/validate/path per fixture type; every build records a sha256
manifest so trials are reproducible. Adding a fixture = one file under
bench/adapters/fixtures/.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path


class Fixture(ABC):
    """A deterministic benchmark input (session corpora, state trees)."""

    name: str = ""

    def __init__(self, cfg: dict):
        """cfg keys: layout (BenchLayout), fixture (this fixture's spec
        slice from configs: n/active/depth/size_mib/seed...)."""
        self.cfg = cfg
        self.spec: dict = dict(cfg.get("fixture") or {})
        self.layout = cfg["layout"]

    @abstractmethod
    def path(self) -> Path:
        """The on-disk artifact path (file or directory)."""

    @abstractmethod
    def generate(self, spec: dict) -> Path:
        """Build the fixture deterministically and return its path."""

    @abstractmethod
    def validate(self, expected_sha256: str) -> bool:
        """Re-hash the artifact and compare against the manifest hash."""

    def ensure(self) -> dict:
        """Build if missing; returns the manifest record. Fixtures with
        staleness detection override this (e.g. spec changes)."""
        if not self.path().exists():
            self.generate(self.spec)
        return self.manifest()

    def manifest(self) -> dict:
        """The build manifest (bytes, rows, sha256) for evidence."""
        raise NotImplementedError
