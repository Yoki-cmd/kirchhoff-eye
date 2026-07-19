# -*- coding: utf-8 -*-
"""Machine-readable contracts for deterministic and AI electrical review evidence."""
import copy
import json
from pathlib import Path

import jsonschema
import pytest


ROOT = Path(__file__).resolve().parents[1]
AUDIT_SCHEMA = ROOT / "schemas" / "electrical-audit.schema.json"
ASSESSMENT_SCHEMA = ROOT / "schemas" / "electrical-assessment.schema.json"
ASSESSMENT_TEMPLATE = ROOT / "templates" / "electrical-assessment.json"
SHA = "a" * 64


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _audit():
    return {
        "version": "kirchhoff-electrical-audit/1.0",
        "candidate_ir_sha256": SHA,
        "verdict": "warn",
        "summary": {
            "blockers": 0,
            "warnings": 1,
            "info": 0,
            "recognized_motifs": 1,
            "statement": "No contradiction found; one engineering warning requires review.",
        },
        "coverage": {
            "net_graph": "complete",
            "ideal_voltage_constraints": "known-independent-sources-only",
            "dc_bias_paths": "heuristic",
            "nonlinear_operating_point": "not_analyzed",
            "frequency_response": "not_analyzed",
            "transient": "not_analyzed",
            "external_context": "not_inferred",
            "known_numeric_values": 2,
            "missing_numeric_values": 0,
            "unparsed_numeric_values": 0,
            "limitations": [],
        },
        "findings": [{
            "id": "EA106-1",
            "code": "EA106",
            "severity": "warning",
            "basis": "device_semantics",
            "message": "A control input has no deterministic DC path.",
            "ir_paths": ["/components/4/pins/0"],
            "component_ids": ["M1"],
            "net_names": ["N_GATE"],
            "assumptions": ["No omitted external source drives this net."],
            "confidence": 1.0,
            "suggested_checks": ["Reinspect the source around the gate pin."],
        }],
        "motifs": [{
            "id": "M001-1",
            "code": "M001",
            "kind": "voltage_divider",
            "confidence": 1.0,
            "component_ids": ["R1", "R2"],
            "net_names": ["N_IN", "N_MID", "GND"],
            "evidence": "R1 and R2 share one midpoint and have distinct outer nets.",
        }],
    }


def _assessment():
    return {
        "version": "kirchhoff-electrical-assessment/1.0",
        "candidate_ir_sha256": SHA,
        "audit_sha256": "b" * 64,
        "verdict": "warn",
        "summary": "该 warning 在当前外部驱动假设下可接受。",
        "claims": [{
            "id": "AIC1",
            "severity": "warning",
            "basis": "audit_finding",
            "audit_finding_id": "EA106-1",
            "ir_paths": ["/components/4/pins/0"],
            "description": "M1 gate has no visible deterministic DC bias path.",
            "assumptions": ["The external terminal is intended to drive this input."],
            "confidence": 0.91,
            "disposition": "confirm_source_intended",
            "rationale": "原图明确画出了该控制输入来自图外。",
        }],
    }


def test_electrical_contract_files_exist_and_are_valid_draft7():
    for path in (AUDIT_SCHEMA, ASSESSMENT_SCHEMA, ASSESSMENT_TEMPLATE):
        assert path.is_file(), path
    jsonschema.Draft7Validator.check_schema(_load(AUDIT_SCHEMA))
    jsonschema.Draft7Validator.check_schema(_load(ASSESSMENT_SCHEMA))


def test_audit_schema_accepts_complete_report_and_rejects_contract_drift():
    schema = _load(AUDIT_SCHEMA)
    jsonschema.validate(_audit(), schema)

    for field, value in (
        ("version", "kirchhoff-electrical-audit/9.9"),
        ("verdict", "approved"),
        ("candidate_ir_sha256", "not-a-hash"),
    ):
        invalid = _audit()
        invalid[field] = value
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(invalid, schema)

    extra = _audit()
    extra["unexpected"] = True
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(extra, schema)


def test_audit_schema_rejects_invalid_finding_and_motif_fields():
    schema = _load(AUDIT_SCHEMA)
    cases = []
    invalid = _audit()
    invalid["findings"][0]["ir_paths"] = ["components/4"]
    cases.append(invalid)
    invalid = _audit()
    invalid["findings"][0]["confidence"] = float("inf")
    cases.append(invalid)
    invalid = _audit()
    invalid["motifs"][0]["confidence"] = -0.1
    cases.append(invalid)
    invalid = _audit()
    invalid["findings"][0]["extra"] = "forbidden"
    cases.append(invalid)

    for document in cases:
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(document, schema)


def test_assessment_schema_accepts_claims_and_rejects_invalid_hash_enum_or_extra():
    schema = _load(ASSESSMENT_SCHEMA)
    jsonschema.validate(_assessment(), schema)

    invalid = _assessment()
    invalid["audit_sha256"] = "bad"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(invalid, schema)
    invalid = _assessment()
    invalid["claims"][0]["disposition"] = "silently_rewire"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(invalid, schema)
    invalid = _assessment()
    invalid["claims"][0]["ir_paths"] = []
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(invalid, schema)
    invalid = _assessment()
    invalid["claims"][0]["extra"] = True
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(invalid, schema)


def test_assessment_schema_requires_linked_difference_for_repair_disposition():
    schema = _load(ASSESSMENT_SCHEMA)
    repair = _assessment()
    repair["verdict"] = "requires_repair"
    repair["claims"][0]["disposition"] = "repair_ir"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(repair, schema)

    repair["claims"][0]["linked_difference_id"] = "D1"
    jsonschema.validate(repair, schema)


def test_assessment_template_is_schema_valid_and_contains_placeholders():
    template = _load(ASSESSMENT_TEMPLATE)
    jsonschema.validate(template, _load(ASSESSMENT_SCHEMA))
    assert template["version"] == "kirchhoff-electrical-assessment/1.0"
    assert template["candidate_ir_sha256"] == "0" * 64
    assert template["audit_sha256"] == "0" * 64
    assert template["claims"] == []


def test_contract_documents_cannot_be_serialized_with_nonfinite_numbers():
    for document in (_audit(), _assessment()):
        broken = copy.deepcopy(document)
        target = broken["findings"][0] if "findings" in broken else broken["claims"][0]
        target["confidence"] = float("nan")
        with pytest.raises(ValueError):
            json.dumps(broken, allow_nan=False)
