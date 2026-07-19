"""Evidence-producing bounded perception job orchestration."""
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

from .. import pipeline as canonical_pipeline
from .evidence import validate_evidence_document
from .intersections import detect_intersection_candidates
from .models import PerceptionJobResult
from .preprocess import preprocess_image
from .scope import assess_image_scope
from .solve import solve_candidates
from .symbols import generate_symbol_candidates
from .wire_graph import extract_wire_graph


ROOT = Path(__file__).resolve().parents[3]
CATALOG = ROOT / "catalog" / "components.json"


def _canonical_hash(document: Any) -> str:
    payload = json.dumps(
        document, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _write_json(path: Path, document: Dict[str, Any]) -> None:
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def _candidate_payload(item, affected_paths):
    alternatives = []
    for alternative in item.alternatives:
        if hasattr(alternative, "component_type"):
            label = alternative.component_type
            payload = {"rotate": alternative.rotate, "mirror": alternative.mirror}
            alt_id = alternative.id
        else:
            label = alternative.label
            payload = {}
            alt_id = alternative.id
        record = {"id": alt_id, "label": label, "score": alternative.score}
        if payload:
            record["payload"] = payload
        alternatives.append(record)
    if item.resolution_status == "selected":
        resolution = {
            "status": "selected",
            "selected_alternative_id": item.selected_alternative_id,
        }
    else:
        resolution = {
            "status": "unresolved",
            "blocking_reason_code": item.blocking_reason_code,
        }
    kind = "symbol" if item.id.startswith("SYM") else "junction_crossing"
    stage = "symbols" if kind == "symbol" else "intersections"
    return {
        "id": item.id,
        "kind": kind,
        "crop": list(item.crop),
        "marker_px": list(getattr(item, "at_px", (item.crop[0], item.crop[1]))),
        "provenance": {"stage": stage, "detector": f"{stage}/1"},
        "confidence": item.confidence,
        "alternatives": alternatives,
        "resolution": resolution,
        "affected_ir_paths": affected_paths,
        "priority": "blocking" if item.blocking_reason_code else "normal",
    }


def _base_evidence(source: Path, report, candidate_ir_hash: str):
    return {
        "version": "kirchhoff-perception-evidence/1.0",
        "source": {
            "sha256": report.source_sha256,
            "width_px": report.width_px,
            "height_px": report.height_px,
            "mime_type": "image/png" if source.suffix.lower() == ".png" else "image/unknown",
        },
        "transform": {
            "pixel_to_ir": report.source_to_normalized.as_list(),
            "ir_to_pixel": report.normalized_to_source.as_list(),
        },
        "candidate_ir_sha256": candidate_ir_hash,
        "candidates": [],
        "review_queue": [],
    }


def _write_needs_human_state(out: Path, reasons, evidence) -> None:
    state = {
        "report_version": "kirchhoff-review/1.0",
        "status": "needs_human",
        "task": {"kind": "redraw-image"},
        "validation_status": "ok",
        "layout_status": "ok",
        "current_round": 1,
        "max_rounds": 3,
        "review_required": False,
        "ready_for_approval": False,
        "reason_codes": list(reasons),
        "rounds": [{
            "round": 1, "reviewed": False, "regions": [], "differences": [],
            "applied_patches": [], "artifacts": {},
            "ir_sha256": evidence["candidate_ir_sha256"],
        }],
        "artifacts": {
            "review_json": str((out / "review.json").resolve()),
            "perception_evidence_json": str((out / "perception-evidence.json").resolve()),
        },
    }
    _write_json(out / "review.json", state)


def perceive(image, out_dir, seed_ir: Optional[Path] = None, dpi: int = 300) -> PerceptionJobResult:
    source = Path(image).resolve()
    out = Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    for name in ("candidate.ir.json", "perception-evidence.json", "review.json"):
        (out / name).unlink(missing_ok=True)
    shutil.rmtree(out / "preprocess", ignore_errors=True)

    assessment = assess_image_scope(source)
    if assessment.status == "input_error":
        _write_json(out / "review.json", {
            "report_version": "kirchhoff-review/1.0", "status": "needs_human",
            "reason_codes": assessment.reason_codes,
        })
        return PerceptionJobResult("needs_human", out, assessment.reason_codes)

    report = preprocess_image(source, out / "preprocess")
    seed_document = {}
    if seed_ir is not None:
        seed_document = json.loads(Path(seed_ir).read_text(encoding="utf-8"))
    candidate_hash = _canonical_hash(seed_document)
    evidence = _base_evidence(source, report, candidate_hash)

    if assessment.status == "needs_human":
        reasons = list(assessment.reason_codes)
        for index, reason in enumerate(reasons, start=1):
            candidate_id = f"SCOPE{index}"
            evidence["candidates"].append({
                "id": candidate_id,
                "kind": "annotation",
                "crop": [0, 0, report.width_px, report.height_px],
                "provenance": {"stage": "preprocess", "detector": "scope/1"},
                "confidence": 1.0,
                "alternatives": [{"id": "needs_human", "label": reason, "score": 1.0}],
                "resolution": {"status": "unresolved", "blocking_reason_code": reason},
                "affected_ir_paths": ["/meta/source_image"],
                "priority": "blocking",
            })
            evidence["review_queue"].append({
                "candidate_id": candidate_id, "priority": "blocking", "reason_code": reason,
            })
        _write_json(out / "perception-evidence.json", evidence)
        _write_needs_human_state(out, reasons, evidence)
        return PerceptionJobResult("needs_human", out, reasons)

    graph = extract_wire_graph(report)
    intersections = detect_intersection_candidates(report, graph)
    symbols = generate_symbol_candidates(report, CATALOG)
    result = solve_candidates(seed_document, symbols=symbols, intersections=intersections)
    for item in symbols:
        evidence["candidates"].append(_candidate_payload(item, ["/components"]))
    for item in intersections:
        evidence["candidates"].append(_candidate_payload(item, ["/junctions", "/crossings"]))
    evidence["review_queue"] = result.review_queue
    errors = validate_evidence_document(evidence)
    if errors:
        raise ValueError("invalid perception evidence: " + "; ".join(errors))
    _write_json(out / "perception-evidence.json", evidence)

    if seed_ir is None or result.status == "needs_human":
        reasons = result.reason_codes or ["CANDIDATE_IR_REQUIRES_REVIEW"]
        if not evidence["review_queue"]:
            evidence["candidates"].append({
                "id": "IR1", "kind": "annotation", "crop": [0, 0, report.width_px, report.height_px],
                "provenance": {"stage": "solver", "detector": "candidate-ir/1"},
                "confidence": 1.0,
                "alternatives": [{"id": "author_ir", "label": "author/review canonical IR", "score": 1.0}],
                "resolution": {"status": "unresolved", "blocking_reason_code": reasons[0]},
                "affected_ir_paths": ["/components"], "priority": "blocking",
            })
            evidence["review_queue"].append({
                "candidate_id": "IR1", "priority": "blocking", "reason_code": reasons[0],
            })
            _write_json(out / "perception-evidence.json", evidence)
        _write_needs_human_state(out, reasons, evidence)
        return PerceptionJobResult("needs_human", out, reasons)

    candidate_path = out / "candidate.ir.json"
    _write_json(candidate_path, result.candidate_ir)
    rc = canonical_pipeline.build(
        str(candidate_path), str(out), source=str(source), dpi=dpi, task_kind="redraw-image"
    )
    if rc != 0:
        return PerceptionJobResult("needs_human", out, ["CANONICAL_BUILD_FAILED"])
    # canonical build clears generated artifacts, so persist sidecar after it returns.
    evidence["candidate_ir_sha256"] = canonical_pipeline._json_file_hash(out / "circuit.ir.json")
    _write_json(out / "perception-evidence.json", evidence)
    state = json.loads((out / "review.json").read_text(encoding="utf-8"))
    return PerceptionJobResult(state["status"], out, list(state.get("reason_codes", [])))
