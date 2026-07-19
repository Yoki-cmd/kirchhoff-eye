# -*- coding: utf-8 -*-
"""The perception evidence sidecar is strict, drift-resistant, and separate from IR."""
import copy
import json
from pathlib import Path

from jsonschema import Draft7Validator

from kirchhoff_eye.perception.evidence import validate_evidence_document


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_SCHEMA = ROOT / "schemas" / "perception-evidence.schema.json"
IR_SCHEMA = ROOT / "schemas" / "ir.schema.json"


def _validator(path):
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft7Validator.check_schema(schema)
    return Draft7Validator(schema)


def _valid_evidence():
    return {
        "version": "kirchhoff-perception-evidence/1.0",
        "source": {
            "sha256": "a" * 64,
            "width_px": 1200,
            "height_px": 800,
            "mime_type": "image/png",
        },
        "transform": {
            "pixel_to_ir": [0.01, 0.0, 0.0, -0.01, 0.0, 8.0],
            "ir_to_pixel": [100.0, 0.0, 0.0, -100.0, 0.0, 800.0],
        },
        "candidate_ir_sha256": "b" * 64,
        "candidates": [
            {
                "id": "cand-j1",
                "kind": "junction_crossing",
                "crop": [380, 260, 460, 340],
                "provenance": {
                    "stage": "intersections",
                    "detector": "orthogonal-branches/1",
                    "artifact_sha256": "c" * 64,
                },
                "confidence": 0.62,
                "alternatives": [
                    {"id": "connected", "label": "connected junction", "score": 0.62},
                    {"id": "crossing", "label": "unconnected crossing", "score": 0.38},
                ],
                "resolution": {
                    "status": "unresolved",
                    "blocking_reason_code": "AMBIGUOUS_JUNCTION_CROSSING",
                },
                "affected_ir_paths": ["/junctions/0", "/crossings/0"],
                "priority": "blocking",
            }
        ],
        "review_queue": [
            {
                "candidate_id": "cand-j1",
                "priority": "blocking",
                "reason_code": "AMBIGUOUS_JUNCTION_CROSSING",
            }
        ],
    }


def test_schema_accepts_unresolved_finite_choice_with_source_and_ir_hashes():
    errors = validate_evidence_document(_valid_evidence(), schema_path=EVIDENCE_SCHEMA)
    assert errors == []


def test_unresolved_candidate_requires_blocking_reason_and_review_queue_entry():
    evidence = _valid_evidence()
    del evidence["candidates"][0]["resolution"]["blocking_reason_code"]
    evidence["review_queue"] = []

    messages = validate_evidence_document(evidence, schema_path=EVIDENCE_SCHEMA)
    assert any("blocking_reason_code" in message for message in messages)
    assert any("review_queue" in message for message in messages)


def test_selected_resolution_must_reference_one_declared_alternative():
    evidence = _valid_evidence()
    evidence["candidates"][0]["resolution"] = {
        "status": "selected",
        "selected_alternative_id": "not-declared",
    }
    evidence["review_queue"] = []

    errors = validate_evidence_document(evidence, schema_path=EVIDENCE_SCHEMA)
    assert errors, "schema/semantic contract must reject undeclared selected hypotheses"
    assert any("not-declared" in message for message in errors)


def test_canonical_ir_rejects_embedded_perception_evidence(golden_a):
    ir = copy.deepcopy(golden_a)
    ir["perception_evidence"] = _valid_evidence()

    errors = list(_validator(IR_SCHEMA).iter_errors(ir))
    assert errors
    assert any("perception_evidence" in error.message for error in errors)


def test_wheel_contract_bundles_perception_schema_and_reference():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"schemas" = "kirchhoff_eye/schemas"' in pyproject
    assert '"references" = "kirchhoff_eye/references"' in pyproject
    assert EVIDENCE_SCHEMA.is_file()
    assert (ROOT / "references" / "perception-evidence-contract.md").is_file()
