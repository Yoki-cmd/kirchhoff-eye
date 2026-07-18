#!/usr/bin/env python
"""Repeatable source-backed pipeline micro-benchmark with per-stage timings."""
import argparse
import json
import statistics
import tempfile
import time
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from kirchhoff_eye.pipeline import build


DEFAULT_IR = ROOT / "tests" / "golden" / "A" / "ir.json"
DEFAULT_SOURCE = ROOT / "tests" / "golden" / "A" / "golden.png"


def percentile(values, q):
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((len(ordered) - 1) * q))
    return ordered[index]


def run_once(ir_path, source_path, dpi):
    with tempfile.TemporaryDirectory(prefix="kirchhoff-perf-") as temp_dir:
        out = Path(temp_dir) / "job"
        started = time.perf_counter()
        rc = build(str(ir_path), str(out), source=str(source_path), dpi=dpi)
        elapsed = time.perf_counter() - started
        if rc != 0:
            raise RuntimeError("pipeline build failed with exit code %d" % rc)
        state = json.loads((out / "review.json").read_text(encoding="utf-8"))
        return elapsed, state["timings"]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Benchmark Kirchhoff-eye pipeline")
    parser.add_argument("--ir", type=Path, default=DEFAULT_IR)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--dpi", type=int, default=120)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.runs < 1 or args.warmup < 0:
        parser.error("--runs must be >=1 and --warmup must be >=0")

    for _ in range(args.warmup):
        run_once(args.ir, args.source, args.dpi)

    samples = [run_once(args.ir, args.source, args.dpi) for _ in range(args.runs)]
    totals = [sample[0] for sample in samples]
    stage_names = sorted({name for _, stages in samples for name in stages})
    report = {
        "runs": args.runs,
        "dpi": args.dpi,
        "total_seconds": {
            "p50": statistics.median(totals),
            "p95": percentile(totals, 0.95),
            "min": min(totals),
            "max": max(totals),
        },
        "stage_seconds_p50": {
            name: statistics.median([stages.get(name, 0.0) for _, stages in samples])
            for name in stage_names
        },
    }
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print("pipeline p50={p50:.3f}s p95={p95:.3f}s".format(**report["total_seconds"]))
        for name, value in report["stage_seconds_p50"].items():
            print("  %-14s %.3fs" % (name, value))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
