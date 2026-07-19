#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Run the public bounded-perception benchmark without overstating accuracy.

Synthetic rows measure deterministic proposal/refusal behavior. Real-image rows are
reported separately and require a distributable manifest; an empty manifest is an honest
"not yet measured", not a zero or a synthetic proxy.
"""
import argparse
import json
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from kirchhoff_eye.perception.pipeline import perceive  # noqa: E402


def _percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _synthetic_rows(manifest_path, workspace, upscale=4):
    manifest_path = Path(manifest_path).resolve()
    fixture_root = manifest_path.parent
    workspace.mkdir(parents=True, exist_ok=True)
    rows = []
    for case in _load(manifest_path)["cases"]:
        source = fixture_root / case["image"]
        large = workspace / f"{case['id']}-large.png"
        with Image.open(source) as image:
            factor = max(upscale, (600 + min(image.size) - 1) // min(image.size))
            image.resize((image.width * factor, image.height * factor)).save(large)
        out = workspace / case["id"]
        started = time.perf_counter()
        result = perceive(large, out)
        elapsed = time.perf_counter() - started
        evidence = _load(out / "perception-evidence.json")
        candidates = evidence.get("candidates", [])
        symbol_candidates = [item for item in candidates if item.get("kind") == "symbol"]
        intersection_candidates = [item for item in candidates if item.get("kind") == "junction_crossing"]
        unresolved = [item for item in candidates if item.get("resolution", {}).get("status") == "unresolved"]
        rows.append({
            "id": case["id"],
            "family": case["family"],
            "variant": case["image_variant"],
            "status": result.status,
            "reason_codes": result.reason_codes,
            "runtime_seconds": round(elapsed, 4),
            "component_candidate_count": len(symbol_candidates),
            "intersection_candidate_count": len(intersection_candidates),
            "unresolved_candidate_count": len(unresolved),
            "blocking_items": len(evidence.get("review_queue", [])),
            "candidate_ir_emitted": (out / "candidate.ir.json").exists(),
            "scope_refusal_expected": False,
        })
    # Explicit out-of-scope row validates refusal correctness independently.
    small_source = fixture_root / _load(manifest_path)["cases"][0]["image"]
    out = workspace / "out-of-scope-short-edge"
    started = time.perf_counter()
    result = perceive(small_source, out)
    elapsed = time.perf_counter() - started
    rows.append({
        "id": "out-of-scope-short-edge",
        "family": "refusal",
        "variant": "short_edge_below_600",
        "status": result.status,
        "reason_codes": result.reason_codes,
        "runtime_seconds": round(elapsed, 4),
        "component_candidate_count": 0,
        "intersection_candidate_count": 0,
        "unresolved_candidate_count": 1,
        "blocking_items": 1,
        "candidate_ir_emitted": False,
        "scope_refusal_expected": True,
    })
    return rows


def _real_rows(manifest_path, workspace):
    manifest = _load(manifest_path)
    workspace.mkdir(parents=True, exist_ok=True)
    rows = []
    for case in manifest.get("cases", []):
        source = (Path(manifest_path).parent / case["image"]).resolve()
        out = workspace / f"real-{case['id']}"
        started = time.perf_counter()
        result = perceive(source, out)
        elapsed = time.perf_counter() - started
        evidence = _load(out / "perception-evidence.json")
        rows.append({
            "id": case["id"],
            "license": case.get("license", "unspecified"),
            "status": result.status,
            "reason_codes": result.reason_codes,
            "runtime_seconds": round(elapsed, 4),
            "blocking_items": len(evidence.get("review_queue", [])),
            "correction_operations": case.get("correction_operations"),
            "correction_seconds": case.get("correction_seconds"),
            "manual_json_edits": case.get("manual_json_edits"),
            "failure_notes": case.get("failure_notes", ""),
        })
    return rows


def summarize(rows):
    runtimes = [row["runtime_seconds"] for row in rows]
    refusal_rows = [row for row in rows if row.get("scope_refusal_expected")]
    refusal_correct = [
        row for row in refusal_rows
        if row["status"] == "needs_human" and "SHORT_EDGE_BELOW_600" in row["reason_codes"]
    ]
    return {
        "case_count": len(rows),
        "runtime_p50_seconds": _percentile(runtimes, 0.50),
        "runtime_p95_seconds": _percentile(runtimes, 0.95),
        "blocking_items_mean": round(statistics.mean(row["blocking_items"] for row in rows), 4) if rows else None,
        "candidate_ir_emission_count": sum(bool(row.get("candidate_ir_emitted")) for row in rows),
        "refusal_cases": len(refusal_rows),
        "refusal_correct": len(refusal_correct),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic-manifest", default=str(ROOT / "tests" / "fixtures" / "synthetic_manifest.json"))
    parser.add_argument("--real-manifest", default=str(Path(__file__).with_name("real_manifest.json")))
    parser.add_argument("--output", required=True)
    parser.add_argument("--work-dir")
    args = parser.parse_args(argv)
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    owned = args.work_dir is None
    workspace = Path(args.work_dir).resolve() if args.work_dir else Path(tempfile.mkdtemp(prefix="kirchhoff-perception-bench-"))
    workspace.mkdir(parents=True, exist_ok=True)
    try:
        synthetic = _synthetic_rows(args.synthetic_manifest, workspace / "synthetic")
        real = _real_rows(args.real_manifest, workspace / "real")
        report = {
            "version": "kirchhoff-perception-benchmark/1.0",
            "disclaimer": "Synthetic and real-image results are separate. Empty real_image means real accuracy is not measured.",
            "synthetic": {"summary": summarize(synthetic), "rows": synthetic},
            "real_image": {"summary": summarize(real), "rows": real},
        }
        output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps({"output": str(output), "synthetic": len(synthetic), "real_image": len(real)}))
        return 0
    finally:
        if owned:
            shutil.rmtree(workspace, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
