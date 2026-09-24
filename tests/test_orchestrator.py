"""Orchestrator: planning, reference outliers, and the run loop mechanics."""
from __future__ import annotations

import json
import tarfile
from pathlib import Path

from bench.core.config import load_config
from bench.drivers.orchestrator.backend import SandboxBackend, SandboxHandle
from bench.drivers.orchestrator.plan import load_parallel_config, plan_sandboxes
from bench.drivers.orchestrator.reference import compare_references
from bench.drivers.orchestrator.run import run_parallel

PARALLEL_YAML = """
backend: fake
aa_trials: 4
reference:
  outlier_pct: 5.0
  outlier_policy: replace
  max_replacements: 2
retry:
  max_retries: 1
sandbox_defaults:
  image: python:3.11-slim
  cpu_cores: 2
  memory_gb: 4
  disk_gb: 10
  timeout_minutes: 30
  bootstrap: null
"""


def _cfg(tmp_path):
    cfg = load_config(None)
    cfg["bench_root"] = str(tmp_path / "bench")
    cfg["results_dir"] = str(tmp_path / "bench" / "results")
    return cfg


def test_plan_one_sandbox_per_benchmark(tmp_path):
    pcfg = load_parallel_config(None)
    specs = plan_sandboxes(_cfg(tmp_path), pcfg,
                           ["compare.cold_start", "compare.msg_send"],
                           ["rust", "ts"])
    assert [s["name"] for s in specs] == ["compare_cold_start", "compare_msg_send"]
    assert specs[0]["benchmarks"] == ["compare.cold_start"]
    assert specs[0]["products"] == ["rust", "ts"]
    assert specs[1]["mock_port"] != specs[0]["mock_port"]


def test_plan_groupings(tmp_path):
    pcfg = load_parallel_config(None)
    pcfg["groupings"] = {"kernel_pair": ["kernel.cold_start", "kernel.cell_exec"]}
    specs = plan_sandboxes(_cfg(tmp_path), pcfg,
                           ["kernel.cold_start", "kernel.cell_exec",
                            "compare.cold_start"],
                           ["rust", "ts"])
    by_name = {s["name"]: s for s in specs}
    assert by_name["kernel_pair"]["benchmarks"] == ["kernel.cold_start",
                                                     "kernel.cell_exec"]
    assert by_name["compare_cold_start"]["benchmarks"] == ["compare.cold_start"]


def test_reference_outliers():
    times = {"a": 100.0, "b": 102.0, "c": 130.0}
    out = compare_references(times, threshold_pct=5.0)
    assert out["median_ms"] == 102.0
    assert "c" in out["outliers"] and "a" not in out["outliers"]


class FakeBackend(SandboxBackend):
    """In-memory backend: records calls, simulates exec results."""

    name = "fake"
    calls: list = []

    def __init__(self, cfg, pcfg):
        super().__init__(cfg, pcfg)
        self.calls = []
        self.results_tar = None

    def harness_dir(self, handle):
        return f"/fake/{handle.name}/harness"

    def bench_root(self, handle):
        return f"/fake/{handle.name}/bench-root"

    def provision(self, name, spec):
        self.calls.append(("provision", name))
        return SandboxHandle(name=name, spec=spec)

    def deploy(self, handle, harness_tar):
        self.calls.append(("deploy", handle.name))

    def exec_cmd(self, handle, cmd, timeout=None):
        self.calls.append(("exec", handle.name, cmd))
        if "REFERENCE-MS" in cmd:
            return 0, "REFERENCE-MS 100.0 42"
        if "pip install" in cmd:
            return 0, "PIP-DONE"
        if "wave_chain" in cmd:
            return 0, "wave ok"
        return 0, ""

    def upload(self, handle, local, remote):
        self.calls.append(("upload", handle.name, str(remote)))

    def download(self, handle, remote, local):
        self.calls.append(("download", handle.name, str(remote)))
        # a real tiny tarball so collection exercises the extract path
        member = Path(str(local).replace(".tar.gz", ""))
        Path(local).parent.mkdir(parents=True, exist_ok=True)
        src = Path(local).with_suffix(".src")
        src.parent.mkdir(parents=True, exist_ok=True)
        inner = src.parent / "results"
        inner.mkdir(exist_ok=True)
        (inner / "trials-w1.jsonl").write_text(json.dumps({"ok": 1}) + "\n")
        with tarfile.open(local, "w:gz") as tar:
            tar.add(inner, arcname="results")

    def destroy(self, handle):
        self.calls.append(("destroy", handle.name))


def test_run_parallel_end_to_end(tmp_path, monkeypatch):
    pdir = tmp_path / "parallel.yaml"
    pdir.write_text(PARALLEL_YAML)
    cfg = _cfg(tmp_path)
    made = {}

    def fake_make_backend(_cfg, pcfg, name=None):
        made["backend"] = FakeBackend(_cfg, pcfg)
        return made["backend"]

    monkeypatch.setattr("bench.drivers.orchestrator.run.make_backend",
                        fake_make_backend)
    monkeypatch.setattr("bench.drivers.orchestrator.run.harness_bundle",
                        lambda repo_root=None: Path("/tmp/bundle.tar.gz"))
    monkeypatch.setattr("bench.drivers.orchestrator.run.bundle_identity",
                        lambda repo_root, bundle: {"git_rev": "deadbee", "dirty": False,
                                                   "bundle_sha256": "cafe" * 16})
    manifest = run_parallel(cfg, str(pdir),
                            ["compare.cold_start", "compare.msg_send"],
                            ["rust", "ts"], trials=3, aa=True,
                            keep_sandboxes=False)
    backend = made["backend"]
    provisions = [c for c in backend.calls if c[0] == "provision"]
    execs = [c for c in backend.calls if c[0] == "exec"]
    waves = [c for c in execs if "wave_chain" in c[2]]
    refs = [c for c in execs if "REFERENCE-MS" in c[2]]
    assert len(provisions) == 2
    assert len(refs) == 2
    assert len(waves) == 2
    assert all("wave_chain" in c[2] and "trials 3" in c[2] for c in waves)
    destroys = [c for c in backend.calls if c[0] == "destroy"]
    assert len(destroys) == 2   # teardown after collection
    assert len(manifest["sandboxes"]) == 2
    assert all(s["status"] == "done" for s in manifest["sandboxes"])
    assert manifest["sandboxes"][0]["reference_ms"] == 100.0
    out_dir = Path(cfg["results_dir"]) / "parallel" / manifest["run_id"]
    assert (out_dir / "manifest.json").exists()
    collected = json.loads((out_dir / "manifest.json").read_text())
    assert collected["run_id"] == manifest["run_id"]
    # provenance gates (audit F7/F8/F9): the manifest names the deploy
    # bundle identity, the wave parameters carry the run label, reference
    # calibration is a timestamped record set, and every sandbox upload
    # wrote the harness-identity.json the wave chain stamps rows with
    assert manifest["harness"] == {"git_rev": "deadbee", "dirty": False,
                                  "bundle_sha256": "cafe" * 16}
    assert manifest["wave"]["run_label"] == manifest["run_id"]
    assert all("--run-label" in c[2] and manifest["run_id"] in c[2]
               for c in waves)
    uploads = [c for c in backend.calls if c[0] == "upload"]
    identity_uploads = [c for c in uploads if c[2].endswith("harness-identity.json")]
    assert len(identity_uploads) == 2
    records = manifest["reference"]["records"]
    assert len(records) == 2
    assert all(r["sandbox"] and r["collected_at"] and r["ms"] == 100.0
               for r in records)
    assert manifest["reference"]["per_sandbox_ms"] == {"compare_cold_start": 100.0,
                                                       "compare_msg_send": 100.0}
    assert manifest["created_at"] and manifest["updated_at"]
