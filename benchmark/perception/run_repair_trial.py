#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Exercise build -> review -> repair -> clean review -> approve on public Golden A."""
import argparse
import copy
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from kirchhoff_eye.pipeline import approve, build, repair, review  # noqa: E402


def write(path, doc):
    Path(path).write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def region_review(ir, round_number, difference=None):
    regions = []
    for region in ir["regions"]:
        has = difference is not None and difference["region"] == region["name"]
        regions.append({
            "name": region["name"],
            "conclusion": "differences" if has else "no_difference",
            "summary": "Public Golden A workflow trial; compared source, circuit, and round image.",
        })
    return {"round": round_number, "regions": regions, "differences": [difference] if difference else []}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    parser.add_argument("--dpi", type=int, default=72)
    args = parser.parse_args(argv)
    out = Path(args.out).resolve()
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True, exist_ok=True)
    source_ir_path = ROOT / "tests" / "golden" / "A" / "ir.json"
    source_image = ROOT / "tests" / "golden" / "A" / "golden.png"
    truth = json.loads(source_ir_path.read_text(encoding="utf-8"))
    wrong = copy.deepcopy(truth)
    wrong["components"][1]["label"] = "R_X"
    wrong_path = out.parent / "trial-wrong.ir.json"
    repaired_path = out.parent / "trial-repaired.ir.json"
    patch_path = out.parent / "trial-patches.json"
    round1_review = out.parent / "trial-review-round1.json"
    round2_review = out.parent / "trial-review-round2.json"
    write(wrong_path, wrong)
    difference = {
        "id": "D1", "region": "divider", "location": "R1", "category": "label",
        "description": "Restore the R1 label to the public truth.",
        "patch_operation": "SET_LABEL", "ir_path": "/components/1/label",
        "evidence": "Golden A source and canonical truth label R_1.",
    }
    started = time.perf_counter()
    steps = []
    rc = build(str(wrong_path), str(out), source=str(source_image), dpi=args.dpi, task_kind="redraw-image")
    steps.append(["build", rc])
    write(round1_review, region_review(wrong, 1, difference))
    rc = review(str(out), str(round1_review)); steps.append(["review_round1", rc])
    write(repaired_path, truth)
    write(patch_path, {"operations": [{
        "operation": "SET_LABEL", "ir_path": "/components/1/label",
        "description": difference["description"], "difference_id": "D1",
        "before_exists": True, "after_exists": True, "before": "R_X", "after": "R_1",
    }]})
    rc = repair(str(out), str(repaired_path), str(patch_path), dpi=args.dpi); steps.append(["repair", rc])
    write(round2_review, region_review(truth, 2))
    rc = review(str(out), str(round2_review)); steps.append(["review_round2", rc])
    rc = approve(str(out), note="Public end-to-end workflow trial"); steps.append(["approve", rc])
    state = json.loads((out / "review.json").read_text(encoding="utf-8"))
    report = {
        "version": "kirchhoff-perception-repair-trial/1.0",
        "case": "tests/golden/A",
        "status": state["status"],
        "steps": [{"name": name, "exit_code": code} for name, code in steps],
        "round_count": len(state["rounds"]),
        "correction_operations": 1,
        "manual_json_edits": 0,
        "ui_clicks": None,
        "elapsed_seconds": round(time.perf_counter() - started, 4),
        "blockers_before": ["D1:SET_LABEL"],
        "blockers_after": list(state.get("reason_codes", [])),
        "failure_notes": "This is a public software-exported workflow trial, not a real-image accuracy claim.",
    }
    report_path = out / "repair-trial-report.json"
    write(report_path, report)
    for path in (wrong_path, repaired_path, patch_path, round1_review, round2_review):
        path.unlink(missing_ok=True)
    print(json.dumps({"report": str(report_path), "status": state["status"]}))
    return 0 if state["status"] == "approved" and all(code in (0, 1) for _, code in steps) else 2


if __name__ == "__main__":
    raise SystemExit(main())
