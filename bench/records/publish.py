"""The publishable campaign records bundle: ``records/campaigns/<label>/``.

One campaign's results tree is turned into the minimal committed record:

    rows/<benchmark>/trials-<phase>.jsonl   eligible rows only (see below)
    settle.jsonl                           settle evidence, screen text
                                           redacted to auth-marker labels
    summary.json / summary.md               the strict-gate analysis over
                                           exactly the bundled rows
    provenance.json                        run identity + row accounting +
                                           privacy audit report (machine)
    NOTES.md                               the human record (provenance,
                                           invalid-row notes, privacy)
    SHASUMS.txt                            sha256 of every file above

Row eligibility (a row enters the bundle only when ALL hold):

- existing shape — the current row schema (``schema_version`` 1, the
  current core fields, a ``run`` provenance stamp) and no field this
  publisher does not know (unknown fields quarantine the row: a bundle
  is published by the harness revision that knows its rows, never a
  newer/foreign shape passed through unexamined);
- campaign identity — the row's ``run.label`` matches the bundle label
  (a mixed-identity tree is the audit-F7/F8 failure class: rows from
  other labels are excluded and reported, never bundled silently);
- privacy audit — screen text and machine paths are dropped/redacted
  (key rules below), and no remaining string exceeds MAX_TEXT_CHARS
  (an oversize string is a quarantined row, not a silent truncation).

The privacy contract (excluded from every bundle, by construction):

- raw PTY screens and screen tails (settle ``screen_tail`` keeps only the
  auth-marker labels it matched, never the text);
- raw logs, trial homes/templates, fixtures and any session/file payloads;
- vendor payloads (binaries, auth, toolchain) — never read at all;
- machine paths — dropped as keys (fixture/clone/native ``path``) and
  redacted inside strings (``<path>``);
- typed probe tokens (synthetic, but screen-derived — counts stay);
- any string over MAX_TEXT_CHARS chars.

Kept in rows: metrics, resource/probe/validation evidence, gate and
comparability marks, run provenance, and harness-generated error strings
(truncated at capture, ≤400 chars) — the validity gate's reason codes
(auth_error, probe_deadline, …) are derived from them and must survive.

Ranks: the bundle never invents them. The summary comes from
``bench analyze``'s strict path (``analysis.aggregate.summarize_rows``)
under the campaign config's rank policy — ``aa.required=false`` (the
default) publishes validation-only stats with NO ranks; a strict campaign
(``aa.required=true`` + explicit ``aa.expected_products``) ranks only a
complete, A/A-calibrated, spread/drift-stable cohort. The bundler never
overrides the policy in either direction.

Everything here is offline: no product launches, no cloud, no uploads.
"""
from __future__ import annotations

import glob
import hashlib
import json
import re
import time
from collections import defaultdict
from pathlib import Path

from bench.analysis.validity import auth_markers_in, is_status_row

#: the bundle contract version stamped on provenance.json
BUNDLE_SCHEMA = "bench-records-bundle/1"
#: the row schema this publisher knows (the current trials.py shape)
ROW_SCHEMA_VERSION = 1
#: no bundled string longer than this (harness strings are ≤400 at capture)
MAX_TEXT_CHARS = 400

#: keys dropped wherever they appear (screen text, typed tokens, paths)
PRIVACY_DROP_KEYS = frozenset({
    "settle_miss_screen", "screen_tail", "last_screen", "screens",
    "probe_tokens", "probe_token", "dialogs", "path", "cwd",
})
#: key names matching this pattern are screen/tail text: dropped too
_PRIVACY_DROP_RE = re.compile(r"screen|_tail$|^screens")
#: a POSIX/home path inside a string: redacted, never published
_ABS_PATH_RE = re.compile(r"(?<![\w.:/~-])~?/[\w.~@+/-]+")

#: the current top-level row fields (trials.py + the scenario adapters).
#: Anything else quarantines the row as unknown_fields.
KNOWN_ROW_KEYS = frozenset({
    "schema_version", "run_id", "run", "benchmark", "product", "phase",
    "trial", "round", "abba_position", "wall_ts", "driver", "comparability",
    "env_gate", "status", "reason", "error", "fixture", "metrics",
    "validated", "validation", "duration_s", "msg_routing",
    "dialog_autodismissed", "consent_baseline_breach", "probe",
    "resource", "daemon", "wire_error",
    # known-but-unpublishable: dropped by the privacy scrub, never a
    # shape quarantine (the row itself is current-shape)
    "settle_miss_screen",
})

#: inputs a bundle is generated from; everything else in a results tree
#: is out of scope by contract (never read, never copied)
READ_SCOPES = ["*/trials-*.jsonl", "settle.jsonl", "versions.json"]
NEVER_READ_SCOPES = [
    "logs/ (raw PTY logs)", "homes/ (trial homes + templates)",
    "fixtures/ (fixture corpora)", "vendor payloads (binaries/auth/toolchain)",
    "diagnose/ (screen evidence bundles)", "sandbox-runs/",
    "noop-control.json", "install-disk.json",
]


class BundleError(RuntimeError):
    """A publishable bundle cannot be built from these inputs."""


def redact_paths(text: str) -> str:
    """Every absolute/home path inside ``text`` becomes ``<path>``."""
    return _ABS_PATH_RE.sub("<path>", text)


def _scrub(value, drops: defaultdict):
    """Recursively drop/redact unsafe content; ``drops`` counts keys."""
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if key in PRIVACY_DROP_KEYS or _PRIVACY_DROP_RE.search(key):
                drops[key] += 1
                continue
            out[key] = _scrub(item, drops)
        return out
    if isinstance(value, list):
        return [_scrub(v, drops) for v in value]
    if isinstance(value, str):
        return redact_paths(value)
    return value


def _oversize_strings(value, prefix: str = "") -> list:
    """Paths to string values longer than MAX_TEXT_CHARS (privacy guard)."""
    if isinstance(value, dict):
        out = []
        for key, item in value.items():
            out += _oversize_strings(item, f"{prefix}.{key}" if prefix else key)
        return out
    if isinstance(value, list):
        return [s for s in (f"{prefix}[{i}]"
                for i in _oversize_strings(v, prefix) for v in [0])]
    if isinstance(value, str) and len(value) > MAX_TEXT_CHARS:
        return [prefix]
    return []


def row_shape_error(row) -> str | None:
    """Why this row is not the current publishable shape, or None.

    Shape = the current trials.py schema: schema_version 1, the core
    identity fields, and the audit-F7/F8/F9 ``run`` provenance stamp
    (label + harness revision). Unstamped legacy rows are excluded
    loudly — a publishable row must name the code that measured it —
    and so are rows carrying fields this publisher does not know."""
    if not isinstance(row, dict):
        return "not_object"
    if row.get("schema_version") != ROW_SCHEMA_VERSION:
        return "schema_version"
    for key in ("benchmark", "product", "phase"):
        if not isinstance(row.get(key), str) or not row.get(key):
            return f"missing_field:{key}"
    run = row.get("run")
    if not isinstance(run, dict) or not run.get("label") \
            or not isinstance(run.get("harness"), dict):
        return "missing_run_stamp"
    if is_status_row(row):
        if not isinstance(row.get("status"), str) \
                or not isinstance(row.get("reason"), str):
            return "status_row_shape"
    elif not isinstance(row.get("trial"), int):
        return "missing_trial_index"
    unknown = sorted(set(row) - KNOWN_ROW_KEYS)
    if unknown:
        return "unknown_fields:" + ",".join(unknown)
    return None


def scrub_row(row: dict) -> tuple[dict, dict]:
    """(scrubbed row, privacy report) — the row is already shape-valid."""
    drops: defaultdict = defaultdict(int)
    clean = _scrub(row, drops)
    oversize = _oversize_strings(clean)
    report = {"dropped_keys": dict(drops), "oversize": oversize}
    return clean, report


def redact_settle_row(rec: dict) -> dict:
    """One settle record with the screen text reduced to marker labels.

    ``screen_tail`` is raw rendered screen (up to 1500 chars): it is
    replaced by the auth-marker labels it matched (the only consumer)
    plus its original length. ``settle_auth_products`` reads the labels
    (``screen_markers``), so the redacted bundle re-analyzes identically.
    The error string keeps its harness-truncated text with paths redacted."""
    out = dict(rec)
    tail = out.pop("screen_tail", None)
    markers = auth_markers_in(str(tail)) if tail else []
    if tail is not None:
        out["screen_markers"] = markers
        out["screen_tail_chars"] = len(str(tail))
    out.pop("screen", None)
    if isinstance(out.get("error"), str):
        out["error"] = redact_paths(out["error"])
    return out


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_label(label: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", label or ""):
        raise BundleError(f"run label {label!r} is not a safe bundle "
                          "directory name ([A-Za-z0-9._-] only)")
    return label


def _load_trial_rows(results_dir: Path):
    """(per-file rows, line-level errors) from */trials-*.jsonl.

    The reader touches exactly the trials JSONLs (load_all's glob): no
    logs, homes, fixtures, screens, or vendor material is ever opened."""
    files = sorted(glob.glob(str(results_dir / "*" / "trials-*.jsonl")))
    rows_by_file, bad_lines = {}, []
    for path in files:
        rel = str(Path(path).parent.name) + "/" + Path(path).name
        rows = []
        with open(path) as f:
            for i, line in enumerate(f, 1):
                if not line.strip():
                    continue
                try:
                    rows.append(json.loads(line))
                except ValueError as e:
                    bad_lines.append({"file": rel, "line": i,
                                      "reason": "unparseable_line",
                                      "detail": str(e)[:120]})
        rows_by_file[rel] = rows
    return rows_by_file, bad_lines


def _scrub_versions(versions: dict) -> dict:
    """versions.json minus machine paths (binary paths), provenance kept."""
    out = {"_meta": versions.get("_meta", {}), "products": {}}
    for name, info in (versions.get("products") or {}).items():
        entry = dict(info)
        entry.pop("binary", None)
        out["products"][name] = entry
    return out


def build_records_bundle(results_dir, cfg: dict, *, label: str | None = None,
                         out_root=None, phases: list | None = None,
                         force: bool = False) -> dict:
    """Build the publishable bundle for one campaign; returns the report.

    cfg: the campaign config (as ``bench analyze`` resolves it), carrying
    ``gate_benchmarks`` (per-benchmark gate metadata from the registry)
    and the rank policy (``aa``) — the bundle inherits both unchanged.
    label: the campaign run label; required when the tree mixes labels.
    out_root: default ``<repo>/records/campaigns``. phases: the published
    denominator (``--phase``), default every non-aa phase."""
    import glob as _glob  # noqa: F401  (kept local: the glob import above)
    from bench.analysis.aggregate import summarize_rows
    from bench.analysis.output.json import JsonAnalyzer
    from bench.analysis.output.markdown import MarkdownAnalyzer
    from bench.core.config import REPO_ROOT
    from bench.core.identity import harness_identity

    results_dir = Path(results_dir).expanduser()
    if not results_dir.is_dir():
        raise BundleError(f"results dir not found: {results_dir}")
    if "gate_benchmarks" not in cfg:
        raise BundleError("cfg lacks gate_benchmarks (the registry map "
                          "cmd_analyze injects) — per-benchmark gate "
                          "checks must not be silently skipped")
    out_root = Path(out_root) if out_root else REPO_ROOT / "records" / "campaigns"

    rows_by_file, bad_lines = _load_trial_rows(results_dir)
    if not rows_by_file:
        raise BundleError(f"no trials-*.jsonl under {results_dir}")

    # campaign identity: one label per bundle (audit F7/F8)
    labels = sorted({str((r.get("run") or {}).get("label"))
                     for rows in rows_by_file.values() for r in rows
                     if isinstance(r, dict) and isinstance(r.get("run"), dict)
                     and r.get("run", {}).get("label")})
    if label is None:
        if len(labels) > 1:
            raise BundleError("mixed-label results tree (audit F7/F8): "
                              f"labels {labels} — pass one explicitly; "
                              "rows of other labels are excluded + noted")
        if not labels:
            raise BundleError("no run.label stamps found — cannot name a "
                              "campaign bundle from an unstamped tree")
        label = labels[0]
    _safe_label(label)

    kept_by_file: dict = {}
    excluded: list = list(bad_lines)
    drops: defaultdict = defaultdict(int)
    redactions = 0
    for rel, rows in sorted(rows_by_file.items()):
        kept = []
        for i, row in enumerate(rows, 1):
            where = {"file": rel, "line": i}
            shape = row_shape_error(row)
            if shape:
                excluded.append({**where, "reason": shape,
                                 "benchmark": row.get("benchmark") if isinstance(row, dict) else None,
                                 "product": row.get("product") if isinstance(row, dict) else None,
                                 "detail": "not the current publishable row shape"})
                continue
            if str(row["run"].get("label")) != label:
                excluded.append({**where, "reason": "run_label_mismatch",
                                 "benchmark": row["benchmark"],
                                 "product": row["product"],
                                 "detail": f"row label {row['run'].get('label')!r} != bundle label {label!r}"})
                continue
            clean, report = scrub_row(row)
            if report["oversize"]:
                excluded.append({**where, "reason": "oversize_text",
                                 "benchmark": row["benchmark"],
                                 "product": row["product"],
                                 "detail": "string over "
                                 f"{MAX_TEXT_CHARS} chars: "
                                 + ", ".join(report["oversize"][:3])})
                continue
            drops.update(report["dropped_keys"])
            redactions += sum(1 for v in _iter_strings(clean)
                              if "<path>" in v)
            kept.append(clean)
        if kept:
            kept_by_file[rel] = kept

    settle_raw = []
    settle_path = results_dir / "settle.jsonl"
    if settle_path.exists():
        with open(settle_path) as f:
            for line in f:
                if line.strip():
                    settle_raw.append(json.loads(line))
    settle_rows = [redact_settle_row(r) for r in settle_raw
                   if isinstance(r, dict)]

    versions = None
    versions_path = results_dir / "versions.json"
    if versions_path.exists():
        versions = _scrub_versions(json.loads(versions_path.read_text()))

    kept_rows = [r for kept in kept_by_file.values() for r in kept]

    # the summary is the analyze artifact over EXACTLY the bundled rows
    analyze_cfg = dict(cfg)
    analyze_cfg["analyze"] = {"results_dir": redact_paths(str(results_dir)),
                             "phases": phases}
    stats = summarize_rows(kept_rows, analyze_cfg, settle_rows=settle_rows,
                           phases=phases)

    # ---- write the bundle ----
    bundle_dir = out_root / _safe_label(label)
    if bundle_dir.exists():
        if not force:
            raise BundleError(f"bundle dir exists: {bundle_dir} "
                              "(pass force=True to rebuild)")
        import shutil
        shutil.rmtree(bundle_dir)
    rows_dir = bundle_dir / "rows"
    rows_dir.mkdir(parents=True)
    for rel, kept in sorted(kept_by_file.items()):
        dest = rows_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "w") as f:
            for row in kept:
                f.write(json.dumps(row) + "\n")
    if settle_rows:
        with open(bundle_dir / "settle.jsonl", "w") as f:
            for row in settle_rows:
                f.write(json.dumps(row) + "\n")

    excluded_summary: defaultdict = defaultdict(int)
    for e in excluded:
        excluded_summary[str(e["reason"]).split(":")[0]] += 1
    rank_status = {}
    for bench, entry in stats["summary"].items():
        rank_status[bench] = {
            "ranks": bool(entry.get("ranks")),
            "withheld": entry.get("ranks_withheld"),
        }
    provenance = {
        "schema": BUNDLE_SCHEMA,
        "run_label": label,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "publisher": harness_identity(),
        "source": {
            "results_dir": redact_paths(str(results_dir)),
            "read": READ_SCOPES,
            "never_read": NEVER_READ_SCOPES,
            "versions": versions,
        },
        "campaign": {
            "run_labels": labels,
            "harness_revs": sorted({str((r.get("run") or {}).get("harness", {}).get("git_rev"))
                                     for r in kept_rows}),
            "benchmarks": sorted({r["benchmark"] for r in kept_rows}),
            "phases": sorted({str(r.get("phase")) for r in kept_rows}),
        },
        "rows": {
            "kept_total": len(kept_rows),
            "kept_by_file": {rel: len(kept) for rel, kept in sorted(kept_by_file.items())},
            "excluded": excluded,
            "excluded_summary": dict(excluded_summary),
        },
        "privacy": {
            "dropped_keys": dict(drops),
            "path_redactions": redactions,
            "settle_rows": {"source": len(settle_raw), "bundled": len(settle_rows)},
            "oversize_limit_chars": MAX_TEXT_CHARS,
            "contract": [
                "no raw screens: PTY/screen/tail text keys dropped; settle "
                "screen_tail reduced to auth-marker labels + char count",
                "no raw logs, homes, fixtures, session payloads, vendor "
                "material: never read (see source.never_read)",
                "no machine paths: path/cwd keys dropped, strings redacted",
                "no typed probe tokens (synthetic but screen-derived); counts stay",
                f"no string over {MAX_TEXT_CHARS} chars (rows quarantine)",
                "harness-generated error strings kept (≤400 chars at capture, "
                "paths redacted) — the validity gate's reason codes derive "
                "from them",
            ],
        },
        "gate": {
            "policy": "bench.analysis.validity (strict) over the bundled rows; "
                      "ranks only per the campaign aa policy "
                      "(validation-only default: no ranks)",
            "valid_rows_total": sum(
                n for b in stats["summary"].values()
                for p in (b.get("trials") or {}).values() for n in p.values()),
            "excluded": {b: e.get("excluded") for b, e in stats["summary"].items()
                         if e.get("excluded")},
            "status_rows": {b: e.get("status") for b, e in stats["summary"].items()
                            if e.get("status")},
            "settle_auth": stats["settle"],
            "rank_status": rank_status,
        },
    }
    (bundle_dir / "summary.json").write_text(JsonAnalyzer(analyze_cfg).format_output(stats))
    (bundle_dir / "summary.md").write_text(MarkdownAnalyzer(analyze_cfg).format_output(stats))
    (bundle_dir / "provenance.json").write_text(json.dumps(provenance, indent=1))
    (bundle_dir / "NOTES.md").write_text(notes_md(provenance, stats))

    write_shasums(bundle_dir)
    return {"bundle_dir": bundle_dir, "provenance": provenance, "stats": stats}


def _iter_strings(value):
    if isinstance(value, dict):
        for v in value.values():
            yield from _iter_strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _iter_strings(v)
    elif isinstance(value, str):
        yield value


def write_shasums(bundle_dir: Path) -> Path:
    """SHASUMS.txt: sha256 of every bundle file except itself (sorted)."""
    files = sorted(p for p in bundle_dir.rglob("*")
                   if p.is_file() and p.name != "SHASUMS.txt")
    lines = [f"{_sha256(p)}  {p.relative_to(bundle_dir).as_posix()}"
             for p in files]
    out = bundle_dir / "SHASUMS.txt"
    out.write_text("\n".join(lines) + "\n")
    return out


def check_bundle(bundle_dir) -> dict:
    """Verify one bundle: required files present + SHASUMS match.

    Returns {ok, checked, missing, mismatched, unlisted}."""
    bundle_dir = Path(bundle_dir)
    required = ["summary.json", "summary.md", "provenance.json", "NOTES.md",
                "SHASUMS.txt"]
    missing = [n for n in required if not (bundle_dir / n).is_file()]
    shasums = bundle_dir / "SHASUMS.txt"
    if missing or not shasums.is_file():
        return {"ok": False, "checked": 0, "missing": missing,
                "mismatched": [], "unlisted": []}
    listed = {}
    for line in shasums.read_text().splitlines():
        digest, rel = line.split("  ", 1)
        listed[rel] = digest
    actual = {p.relative_to(bundle_dir).as_posix(): _sha256(p)
              for p in bundle_dir.rglob("*")
              if p.is_file() and p.name != "SHASUMS.txt"}
    mismatched = sorted(rel for rel in listed if actual.get(rel) != listed[rel])
    unlisted = sorted(set(actual) - set(listed))
    return {"ok": not (mismatched or unlisted or missing),
            "checked": len(listed), "missing": missing,
            "mismatched": mismatched, "unlisted": unlisted}


def notes_md(provenance: dict, stats: dict) -> str:
    """NOTES.md: the human record — provenance, invalid-row notes,
    the privacy audit, and the rank-policy status."""
    rows = provenance["rows"]
    gate = provenance["gate"]
    lines = [
        f"# Campaign record: {provenance['run_label']}",
        "",
        f"_Records bundle `{BUNDLE_SCHEMA}`; generated "
        f"{provenance['generated_at']} by harness rev "
        f"{provenance['publisher'].get('git_rev')} "
        f"(dirty={provenance['publisher'].get('dirty')})._",
        "",
        "## Provenance",
        "",
        f"- campaign run label: **{provenance['run_label']}** "
        f"(labels seen in the source tree: {provenance['campaign']['run_labels']})",
        f"- harness revisions that measured the rows: "
        f"{provenance['campaign']['harness_revs']}",
        f"- benchmarks: {', '.join(provenance['campaign']['benchmarks'])}",
        f"- phases: {', '.join(provenance['campaign']['phases'])}",
        f"- source results tree: `{provenance['source']['results_dir']}` "
        "(machine paths redacted)",
    ]
    versions = provenance["source"].get("versions")
    if versions:
        lines.append("- pinned product versions: see `versions` in "
                      "provenance.json (binary paths scrubbed)")
    lines += ["", "## Row accounting", "",
              f"- bundled rows: **{rows['kept_total']}** "
              f"({json.dumps(rows['kept_by_file'])})",
              f"- publisher-excluded rows: {len(rows['excluded'])} "
              f"— {json.dumps(rows['excluded_summary'])}"]
    if rows["excluded"]:
        lines += ["", "| file | line | reason |", "|---|---|---|"]
        for e in rows["excluded"][:40]:
            lines.append(f"| {e['file']} | {e['line']} | "
                         f"{e['reason']} |")
        if len(rows["excluded"]) > 40:
            lines.append(f"| … | … | {len(rows['excluded']) - 40} more "
                         "(see provenance.json) |")
    lines += ["", "## Validity gate (over the bundled rows)", ""]
    if gate["excluded"]:
        lines.append("gate-excluded trials (never in stats/ranks): "
                     + json.dumps(gate["excluded"]))
    else:
        lines.append("- no gate exclusions among the bundled rows")
    if gate["status_rows"]:
        lines.append("engine status rows (not exclusions): "
                     + json.dumps(gate["status_rows"]))
    if gate["settle_auth"]:
        lines.append("settle auth failures: "
                     + json.dumps(gate["settle_auth"]))
    lines += ["", "## Ranks", ""]
    for bench, status in sorted(gate["rank_status"].items()):
        if status["ranks"]:
            lines.append(f"- `{bench}`: ranked (strict cohort complete)")
        else:
            reason = (status.get("withheld") or {}).get("reason", "none")
            lines.append(f"- `{bench}`: ranks withheld ({reason})")
    lines += ["", "## Privacy audit", ""]
    lines += [f"- {rule}" for rule in provenance["privacy"]["contract"]]
    lines += ["", f"- dropped keys: {json.dumps(provenance['privacy']['dropped_keys'])}; "
              f"redacted path strings: {provenance['privacy']['path_redactions']}",
              f"- settle rows bundled: {provenance['privacy']['settle_rows']['bundled']} "
              f"of {provenance['privacy']['settle_rows']['source']} "
              "(screen text reduced to auth-marker labels)",
              "",
              "Caveat: harness-generated error/diagnostic strings are kept "
              "truncated (≤400 chars, paths redacted). Product screens, "
              "session text, homes, fixtures and vendor payloads are not in "
              "this bundle by construction.",
              "",
              "Verify: `python scripts/publish_records.py --check " 
              f"{provenance['run_label']}` (or pass the bundle dir).",
              ""]
    return "\n".join(lines)
