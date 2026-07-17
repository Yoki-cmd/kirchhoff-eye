# -*- coding: utf-8 -*-
"""Human/Agent review and approval are explicit production states."""
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
GOLDEN_A = ROOT / "tests" / "golden" / "A" / "ir.json"
SOURCE_A = ROOT / "tests" / "golden" / "A" / "golden.png"


def _write_clean_review(path, round_number=1):
    ir = json.loads(GOLDEN_A.read_text(encoding="utf-8"))
    report = {
        "round": round_number,
        "regions": [
            {"name": region["name"], "conclusion": "no_difference", "summary": "无差异"}
            for region in ir["regions"]
        ],
        "differences": [],
    }
    path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")


def _write_difference_review(path, round_number=1, count=1):
    ir = json.loads(GOLDEN_A.read_text(encoding="utf-8"))
    report = {
        "round": round_number,
        "regions": [
            {
                "name": region["name"],
                "conclusion": "differences" if index == 0 else "no_difference",
                "summary": "见差异 D1" if index == 0 else "无差异",
            }
            for index, region in enumerate(ir["regions"])
        ],
        "differences": [
            {
                "id": f"D{index + 1}",
                "location": "网格 (2, 2)",
                "category": "wrong_position",
                "description": "R1 需要右移",
                "patch_operation": "MOVE",
                "ir_path": "/components/1",
            }
            for index in range(count)
        ],
    }
    path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")


def _write_patches(path, operations):
    path.write_text(json.dumps({
        "operations": [
            {**operation, "difference_id": operation.get("difference_id", "D1")}
            for operation in operations
        ]
    }, ensure_ascii=False), encoding="utf-8")


def _moved_r1_ir(path):
    ir = json.loads(GOLDEN_A.read_text(encoding="utf-8"))
    ir["components"][1]["label_at"] = [2.5, 3.5]
    path.write_text(json.dumps(ir, ensure_ascii=False), encoding="utf-8")
    return path


def test_clean_review_requires_explicit_approval(tmp_path):
    from kirchhoff_eye.cli import main

    job = tmp_path / "job"
    assert main(["build", str(GOLDEN_A), "--source", str(SOURCE_A), "--out", str(job), "--dpi", "72"]) == 0
    round_review = tmp_path / "round-review.json"
    _write_clean_review(round_review)

    assert main(["review", str(job), str(round_review)]) == 0
    state = json.loads((job / "review.json").read_text(encoding="utf-8"))
    assert state["status"] == "needs_review"
    assert state["ready_for_approval"] is True
    assert state["rounds"][0]["reviewed"] is True
    assert state["rounds"][0]["differences"] == []

    assert main(["approve", str(job), "--note", "逐区确认通过"]) == 0
    approved = json.loads((job / "review.json").read_text(encoding="utf-8"))
    delivery = (job / "DELIVERY.md").read_text(encoding="utf-8")
    assert approved["status"] == "approved"
    assert approved["approval"]["note"] == "逐区确认通过"
    assert "Status: **approved**" in delivery
    assert "source | 无差异" in delivery


def test_render_only_valid_delivery_does_not_claim_pending_source_review(tmp_path):
    from kirchhoff_eye.cli import main

    job = tmp_path / "job"
    assert main(["build", str(GOLDEN_A), "--out", str(job), "--dpi", "72"]) == 0
    state = json.loads((job / "review.json").read_text(encoding="utf-8"))
    delivery = (job / "DELIVERY.md").read_text(encoding="utf-8")
    assert state["status"] == "valid"
    assert state["review_required"] is False
    assert "等待审读" not in delivery
    assert "不适用" in delivery


def test_review_rejects_missing_region_without_mutating_state(tmp_path):
    from kirchhoff_eye.cli import main

    job = tmp_path / "job"
    assert main(["build", str(GOLDEN_A), "--source", str(SOURCE_A), "--out", str(job), "--dpi", "72"]) == 0
    before = (job / "review.json").read_bytes()
    invalid_review = tmp_path / "invalid-review.json"
    invalid_review.write_text(json.dumps({
        "round": 1,
        "regions": [{"name": "source", "conclusion": "no_difference", "summary": "无差异"}],
        "differences": [],
    }), encoding="utf-8")

    assert main(["review", str(job), str(invalid_review)]) == 2
    assert (job / "review.json").read_bytes() == before


def test_reviewed_round_is_immutable_and_cannot_erase_recorded_differences(tmp_path):
    from kirchhoff_eye.cli import main

    job = tmp_path / "job"
    assert main(["build", str(GOLDEN_A), "--source", str(SOURCE_A), "--out", str(job), "--dpi", "72"]) == 0
    difference_review = tmp_path / "difference-review.json"
    _write_difference_review(difference_review)
    assert main(["review", str(job), str(difference_review)]) == 0
    before = (job / "review.json").read_bytes()
    clean_review = tmp_path / "clean-review.json"
    _write_clean_review(clean_review)

    assert main(["review", str(job), str(clean_review)]) == 2
    assert (job / "review.json").read_bytes() == before
    assert main(["approve", str(job)]) == 2


def test_difference_review_and_repair_preserve_round_history_and_patch_log(tmp_path):
    from kirchhoff_eye.cli import main

    job = tmp_path / "job"
    assert main(["build", str(GOLDEN_A), "--source", str(SOURCE_A), "--out", str(job), "--dpi", "72"]) == 0
    round_review = tmp_path / "round-review.json"
    _write_difference_review(round_review)
    assert main(["review", str(job), str(round_review)]) == 0

    patches = tmp_path / "patches.json"
    patches.write_text(json.dumps({
        "operations": [{
            "operation": "MOVE",
            "ir_path": "/components/1",
            "description": "按 D1 调整 R1",
            "difference_id": "D1",
        }]
    }, ensure_ascii=False), encoding="utf-8")
    assert main([
        "repair", str(job), str(_moved_r1_ir(tmp_path / "repaired.json")), "--patches", str(patches), "--dpi", "72",
    ]) == 0

    state = json.loads((job / "review.json").read_text(encoding="utf-8"))
    assert state["status"] == "needs_review"
    assert state["current_round"] == 2
    assert len(state["rounds"]) == 2
    assert state["rounds"][0]["differences"][0]["patch_operation"] == "MOVE"
    assert state["rounds"][1]["applied_patches"][0]["operation"] == "MOVE"
    assert (job / "cmp_round1.png").is_file()
    assert (job / "cmp_round2.png").is_file()
    assert (job / "rounds" / "round-01" / "circuit.ir.json").is_file()
    assert (job / "rounds" / "round-02" / "circuit.ir.json").is_file()
    assert state["rounds"][0]["artifacts"]["circuit_ir"] == str(
        (job / "rounds" / "round-01" / "circuit.ir.json").resolve()
    )
    assert state["rounds"][1]["artifacts"]["circuit_ir"] == str(
        (job / "rounds" / "round-02" / "circuit.ir.json").resolve()
    )


def test_max_rounds_transitions_unresolved_review_to_needs_human(tmp_path, monkeypatch):
    import kirchhoff_eye.pipeline as pipeline
    from kirchhoff_eye.cli import main

    monkeypatch.setattr(pipeline, "_load_max_rounds", lambda: 2)
    job = tmp_path / "job"
    assert main(["build", str(GOLDEN_A), "--source", str(SOURCE_A), "--out", str(job), "--dpi", "72"]) == 0
    first_review = tmp_path / "review-1.json"
    _write_difference_review(first_review, round_number=1, count=2)
    assert main(["review", str(job), str(first_review)]) == 0
    patches = tmp_path / "patches.json"
    patches.write_text(json.dumps({
        "operations": [{"operation": "MOVE", "ir_path": "/components/1", "description": "调整", "difference_id": "D1"}]
    }), encoding="utf-8")
    assert main(["repair", str(job), str(_moved_r1_ir(tmp_path / "repaired.json")), "--patches", str(patches), "--dpi", "72"]) == 0
    second_review = tmp_path / "review-2.json"
    _write_difference_review(second_review, round_number=2, count=1)

    assert main(["review", str(job), str(second_review)]) == 0
    state = json.loads((job / "review.json").read_text(encoding="utf-8"))
    assert state["status"] == "needs_human"
    assert "max_rounds_reached" in state["reason_codes"]
    assert state["ready_for_approval"] is False
    assert main(["approve", str(job)]) == 2


def test_review_rejects_duplicate_regions_and_region_difference_disagreement(tmp_path):
    from kirchhoff_eye.cli import main

    job = tmp_path / "job"
    assert main(["build", str(GOLDEN_A), "--source", str(SOURCE_A), "--out", str(job), "--dpi", "72"]) == 0
    before = (job / "review.json").read_bytes()
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(json.dumps({
        "round": 1,
        "regions": [
            {"name": "source", "conclusion": "no_difference", "summary": "无差异"},
            {"name": "source", "conclusion": "no_difference", "summary": "无差异"},
            {"name": "output", "conclusion": "no_difference", "summary": "无差异"},
        ],
        "differences": [],
    }), encoding="utf-8")
    assert main(["review", str(job), str(duplicate)]) == 2
    assert (job / "review.json").read_bytes() == before

    disagreement = tmp_path / "disagreement.json"
    _write_clean_review(disagreement)
    report = json.loads(disagreement.read_text(encoding="utf-8"))
    report["regions"][0]["conclusion"] = "differences"
    report["regions"][0]["summary"] = "有差异"
    disagreement.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    assert main(["review", str(job), str(disagreement)]) == 2
    assert (job / "review.json").read_bytes() == before


def test_review_rejects_duplicate_difference_ids_without_mutating_state(tmp_path):
    from kirchhoff_eye.cli import main

    job = tmp_path / "job"
    assert main(["build", str(GOLDEN_A), "--source", str(SOURCE_A), "--out", str(job), "--dpi", "72"]) == 0
    before = (job / "review.json").read_bytes()
    duplicate = tmp_path / "duplicate-differences.json"
    _write_difference_review(duplicate, count=2)
    report = json.loads(duplicate.read_text(encoding="utf-8"))
    report["differences"][1]["id"] = "D1"
    duplicate.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")

    assert main(["review", str(job), str(duplicate)]) == 2
    assert (job / "review.json").read_bytes() == before


def test_repair_rejects_more_than_five_patch_operations_without_mutating_job(tmp_path):
    from kirchhoff_eye.cli import main

    job = tmp_path / "job"
    assert main(["build", str(GOLDEN_A), "--source", str(SOURCE_A), "--out", str(job), "--dpi", "72"]) == 0
    round_review = tmp_path / "round-review.json"
    _write_difference_review(round_review)
    assert main(["review", str(job), str(round_review)]) == 0
    before = (job / "review.json").read_bytes()
    patches = tmp_path / "too-many-patches.json"
    patches.write_text(json.dumps({
        "operations": [
            {"operation": "MOVE", "ir_path": "/components/1", "description": f"调整 {index}", "difference_id": "D1"}
            for index in range(6)
        ]
    }), encoding="utf-8")

    assert main([
        "repair", str(job), str(GOLDEN_A), "--patches", str(patches), "--dpi", "72",
    ]) == 2
    assert (job / "review.json").read_bytes() == before
    assert not (job / "cmp_round2.png").exists()


def test_repair_invalid_ir_is_transactional_and_preserves_current_job(tmp_path):
    from kirchhoff_eye.cli import main

    job = tmp_path / "job"
    assert main(["build", str(GOLDEN_A), "--source", str(SOURCE_A), "--out", str(job), "--dpi", "72"]) == 0
    round_review = tmp_path / "round-review.json"
    _write_difference_review(round_review)
    assert main(["review", str(job), str(round_review)]) == 0
    patches = tmp_path / "patches.json"
    patches.write_text(json.dumps({
        "operations": [{"operation": "MOVE", "ir_path": "/components/1", "description": "调整", "difference_id": "D1"}]
    }), encoding="utf-8")
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{}", encoding="utf-8")
    before = {
        name: (job / name).read_bytes()
        for name in ("circuit.ir.json", "circuit.png", "validation.json", "review.json", "DELIVERY.md")
    }

    assert main(["repair", str(job), str(invalid), "--patches", str(patches), "--dpi", "72"]) == 2
    for name, content in before.items():
        assert (job / name).read_bytes() == content
    assert not (job / "cmp_round2.png").exists()
    assert not (job / "rounds" / "round-02").exists()


def test_repair_rejects_unchanged_ir_and_unverifiable_patch_log(tmp_path):
    from kirchhoff_eye.cli import main

    job = tmp_path / "job"
    assert main(["build", str(GOLDEN_A), "--source", str(SOURCE_A), "--out", str(job), "--dpi", "72"]) == 0
    round_review = tmp_path / "round-review.json"
    _write_difference_review(round_review)
    assert main(["review", str(job), str(round_review)]) == 0
    before = (job / "review.json").read_bytes()
    patches = tmp_path / "patches.json"
    patches.write_text(json.dumps({
        "operations": [{
            "operation": "MOVE",
            "ir_path": "/components/999",
            "description": "伪造的修改记录",
            "difference_id": "D1",
        }]
    }), encoding="utf-8")

    assert main(["repair", str(job), str(GOLDEN_A), "--patches", str(patches), "--dpi", "72"]) == 2
    assert (job / "review.json").read_bytes() == before
    assert not (job / "rounds" / "round-02").exists()


def test_repair_requires_difference_id_in_every_patch_operation(tmp_path):
    from kirchhoff_eye.cli import main

    job = tmp_path / "job"
    assert main(["build", str(GOLDEN_A), "--source", str(SOURCE_A), "--out", str(job), "--dpi", "72"]) == 0
    round_review = tmp_path / "round-review.json"
    _write_difference_review(round_review)
    assert main(["review", str(job), str(round_review)]) == 0
    patches = tmp_path / "patches.json"
    patches.write_text(json.dumps({
        "operations": [{
            "operation": "MOVE",
            "ir_path": "/components/1",
            "description": "缺少差异引用",
        }]
    }), encoding="utf-8")

    assert main(["repair", str(job), str(GOLDEN_A), "--patches", str(patches), "--dpi", "72"]) == 2


def test_patch_evidence_tracks_array_insertions_and_removals_by_semantic_index():
    from kirchhoff_eye.pipeline import _validate_patch_manifest

    cases = [
        (
            "ADD_COMPONENT",
            {"components": [{"id": "B"}]},
            {"components": [{"id": "A"}, {"id": "B"}]},
        ),
        (
            "REMOVE_COMPONENT",
            {"components": [{"id": "A"}, {"id": "B"}]},
            {"components": [{"id": "B"}]},
        ),
    ]
    for operation, before, after in cases:
        state = {"rounds": [{"differences": [{
            "id": "D1",
            "patch_operation": operation,
            "ir_path": "/components/0",
        }]}]}
        patch_doc = {"operations": [{
            "difference_id": "D1",
            "operation": operation,
            "ir_path": "/components/0",
            "description": "调整元件列表",
        }]}

        evidence = _validate_patch_manifest(before, after, state, patch_doc)

        assert evidence["changed_paths"] == ["/components/0"]
        recorded = patch_doc["operations"][0]
        assert recorded["before_exists"] is (operation == "REMOVE_COMPONENT")
        assert recorded["after_exists"] is (operation == "ADD_COMPONENT")
        assert recorded["before"] == ({"id": "A"} if operation == "REMOVE_COMPONENT" else None)
        assert recorded["after"] == ({"id": "A"} if operation == "ADD_COMPONENT" else None)


def test_patch_evidence_rejects_extra_array_changes_outside_declared_insert():
    from kirchhoff_eye.pipeline import _validate_patch_manifest

    before = {"components": [{"id": "B"}]}
    after = {"components": [{"id": "A"}, {"id": "CHANGED"}]}
    state = {"rounds": [{"differences": [{
        "id": "D1",
        "patch_operation": "ADD_COMPONENT",
        "ir_path": "/components/0",
    }]}]}
    patch_doc = {"operations": [{
        "difference_id": "D1",
        "operation": "ADD_COMPONENT",
        "ir_path": "/components/0",
        "description": "新增元件 A",
    }]}

    with pytest.raises(ValueError, match="declared change"):
        _validate_patch_manifest(before, after, state, patch_doc)


def test_patch_evidence_rejects_operation_that_does_not_match_changed_fields():
    from kirchhoff_eye.pipeline import _validate_patch_manifest

    before = {"components": [{"id": "R1", "type": "resistor", "label_at": [1, 1]}]}
    after = {"components": [{"id": "R1", "type": "capacitor", "label_at": [1, 1]}]}
    state = {"rounds": [{"differences": [{
        "id": "D1",
        "patch_operation": "MOVE",
        "ir_path": "/components/0",
    }]}]}
    patch_doc = {"operations": [{
        "difference_id": "D1",
        "operation": "MOVE",
        "ir_path": "/components/0",
        "description": "移动 R1",
    }]}

    with pytest.raises(ValueError, match="does not match changed fields"):
        _validate_patch_manifest(before, after, state, patch_doc)


def test_previous_review_state_shape_is_rejected_with_controlled_input_error(tmp_path):
    from kirchhoff_eye.cli import main

    job = tmp_path / "old-job"
    job.mkdir()
    (job / "review.json").write_text(json.dumps({
        "status": "ok",
        "validation_status": "ok",
        "layout_status": "ok",
        "artifacts": {},
    }), encoding="utf-8")
    patches = tmp_path / "patches.json"
    patches.write_text(json.dumps({"operations": []}), encoding="utf-8")

    assert main(["repair", str(job), str(GOLDEN_A), "--patches", str(patches)]) == 2


def test_malformed_review_and_patch_json_are_input_errors(tmp_path):
    from kirchhoff_eye.cli import main

    job = tmp_path / "job"
    assert main(["build", str(GOLDEN_A), "--source", str(SOURCE_A), "--out", str(job), "--dpi", "72"]) == 0
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{", encoding="utf-8")
    assert main(["review", str(job), str(malformed)]) == 2

    round_review = tmp_path / "round-review.json"
    _write_difference_review(round_review)
    assert main(["review", str(job), str(round_review)]) == 0
    assert main(["repair", str(job), str(GOLDEN_A), "--patches", str(malformed), "--dpi", "72"]) == 2


def test_two_reviewed_rounds_without_difference_reduction_stop_for_human(tmp_path):
    from kirchhoff_eye.cli import main

    job = tmp_path / "job"
    assert main(["build", str(GOLDEN_A), "--source", str(SOURCE_A), "--out", str(job), "--dpi", "72"]) == 0
    review_1 = tmp_path / "review-1.json"
    _write_difference_review(review_1, round_number=1, count=1)
    assert main(["review", str(job), str(review_1)]) == 0
    patches = tmp_path / "patches.json"
    patches.write_text(json.dumps({
        "operations": [{"operation": "MOVE", "ir_path": "/components/1", "description": "调整", "difference_id": "D1"}]
    }), encoding="utf-8")
    assert main(["repair", str(job), str(_moved_r1_ir(tmp_path / "repaired.json")), "--patches", str(patches), "--dpi", "72"]) == 0
    review_2 = tmp_path / "review-2.json"
    _write_difference_review(review_2, round_number=2, count=1)

    assert main(["review", str(job), str(review_2)]) == 0
    state = json.loads((job / "review.json").read_text(encoding="utf-8"))
    assert state["status"] == "needs_human"
    assert "difference_count_not_decreasing" in state["reason_codes"]
    assert main(["repair", str(job), str(GOLDEN_A), "--patches", str(patches), "--dpi", "72"]) == 2


def test_third_patch_to_same_ir_path_freezes_job_for_human(tmp_path):
    from kirchhoff_eye.cli import main

    job = tmp_path / "job"
    assert main(["build", str(GOLDEN_A), "--source", str(SOURCE_A), "--out", str(job), "--dpi", "72"]) == 0
    review_1 = tmp_path / "review-1.json"
    _write_difference_review(review_1)
    assert main(["review", str(job), str(review_1)]) == 0
    patches = tmp_path / "repeated-patches.json"
    patches.write_text(json.dumps({
        "operations": [
            {"operation": "MOVE", "ir_path": "/components/1", "description": f"调整 {index}", "difference_id": "D1"}
            for index in range(3)
        ]
    }), encoding="utf-8")

    assert main(["repair", str(job), str(_moved_r1_ir(tmp_path / "repaired.json")), "--patches", str(patches), "--dpi", "72"]) == 0
    state = json.loads((job / "review.json").read_text(encoding="utf-8"))
    assert state["status"] == "needs_human"
    assert "patch_path_frozen:/components/1" in state["reason_codes"]
    assert state["ready_for_approval"] is False
    assert main(["repair", str(job), str(GOLDEN_A), "--patches", str(patches), "--dpi", "72"]) == 2
