# -*- coding: utf-8 -*-
"""Human/Agent review and approval are explicit production states."""
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
GOLDEN_A = ROOT / "tests" / "golden" / "A" / "ir.json"
SOURCE_A = ROOT / "tests" / "golden" / "A" / "golden.png"


pytestmark = pytest.mark.tex


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
                "region": ir["regions"][0]["name"],
                "location": "网格 (2, 2)",
                "category": "wrong_position",
                "description": "R1 需要右移",
                "patch_operation": "MOVE",
                "ir_path": "/components/1/label_at",
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


def _job_bytes(job):
    return {
        path.relative_to(job).as_posix(): path.read_bytes()
        for path in job.rglob("*")
        if path.is_file() and not path.name.startswith(".")
    }


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


def test_approve_rederives_invariants_and_binds_review_to_live_ir(tmp_path):
    from kirchhoff_eye.cli import main

    forged_job = tmp_path / "forged-job"
    assert main([
        "build", str(GOLDEN_A), "--source", str(SOURCE_A),
        "--out", str(forged_job), "--dpi", "72",
    ]) == 0
    forged = json.loads((forged_job / "review.json").read_text(encoding="utf-8"))
    forged["ready_for_approval"] = True
    (forged_job / "review.json").write_text(json.dumps(forged), encoding="utf-8")
    assert main(["approve", str(forged_job)]) == 2

    changed_job = tmp_path / "changed-job"
    assert main([
        "build", str(GOLDEN_A), "--source", str(SOURCE_A),
        "--out", str(changed_job), "--dpi", "72",
    ]) == 0
    clean = tmp_path / "clean-review.json"
    _write_clean_review(clean)
    assert main(["review", str(changed_job), str(clean)]) == 0
    altered = json.loads((changed_job / "circuit.ir.json").read_text(encoding="utf-8"))
    altered["components"][1]["label_at"] = [9, 9]
    (changed_job / "circuit.ir.json").write_text(json.dumps(altered), encoding="utf-8")
    assert main(["approve", str(changed_job)]) == 2

    evidence_job = tmp_path / "evidence-job"
    assert main([
        "build", str(GOLDEN_A), "--source", str(SOURCE_A),
        "--out", str(evidence_job), "--dpi", "72",
    ]) == 0
    assert main(["review", str(evidence_job), str(clean)]) == 0
    comparison = evidence_job / "cmp_round1.png"
    comparison.write_bytes(comparison.read_bytes() + b"tampered")
    assert main(["approve", str(evidence_job)]) == 2


@pytest.mark.parametrize("command", ["review", "approve"])
def test_review_and_approve_delivery_failure_rolls_back_every_job_file(
        tmp_path, monkeypatch, command):
    import kirchhoff_eye.pipeline as pipeline
    from kirchhoff_eye.cli import main

    job = tmp_path / "job"
    assert main([
        "build", str(GOLDEN_A), "--source", str(SOURCE_A),
        "--out", str(job), "--dpi", "72",
    ]) == 0
    clean = tmp_path / "clean-review.json"
    _write_clean_review(clean)
    if command == "approve":
        assert main(["review", str(job), str(clean)]) == 0
    before = _job_bytes(job)
    monkeypatch.setattr(
        pipeline, "_write_delivery",
        lambda *_args: (_ for _ in ()).throw(OSError("injected delivery failure")),
    )

    args = ["review", str(job), str(clean)] if command == "review" else ["approve", str(job)]
    assert main(args) == 3
    assert _job_bytes(job) == before


def test_repeated_approve_rechecks_live_evidence(tmp_path):
    from kirchhoff_eye.cli import main

    job = tmp_path / "job"
    clean = tmp_path / "clean-review.json"
    _write_clean_review(clean)
    assert main([
        "build", str(GOLDEN_A), "--source", str(SOURCE_A),
        "--out", str(job), "--dpi", "72",
    ]) == 0
    assert main(["review", str(job), str(clean)]) == 0
    assert main(["approve", str(job)]) == 0
    altered = json.loads((job / "circuit.ir.json").read_text(encoding="utf-8"))
    altered["meta"]["title"] = "tampered after approval"
    (job / "circuit.ir.json").write_text(json.dumps(altered), encoding="utf-8")

    assert main(["approve", str(job)]) == 2


def test_w103_blocks_approval_without_warning_disposition(tmp_path):
    from kirchhoff_eye.cli import main

    ir = json.loads((ROOT / "tests" / "golden" / "B" / "ir.json").read_text(encoding="utf-8"))
    q1 = next(component for component in ir["components"] if component["id"] == "Q1")
    q1["pins"][0]["at"] = [8, 8]
    ir_path = tmp_path / "pose-warning.json"
    ir_path.write_text(json.dumps(ir), encoding="utf-8")
    job = tmp_path / "job"
    assert main([
        "build", str(ir_path), "--source", str(SOURCE_A),
        "--out", str(job), "--dpi", "72",
    ]) == 0
    review_file = tmp_path / "review.json"
    review_file.write_text(json.dumps({
        "round": 1,
        "regions": [
            {"name": region["name"], "conclusion": "no_difference", "summary": "verified"}
            for region in ir["regions"]
        ],
        "differences": [],
    }), encoding="utf-8")

    assert main(["review", str(job), str(review_file)]) == 0
    state = json.loads((job / "review.json").read_text(encoding="utf-8"))
    assert "blocking_pose_warning" in state["reason_codes"]
    assert main(["approve", str(job)]) == 2


def test_source_backed_empty_regions_cannot_be_reviewed_or_approved(tmp_path):
    from kirchhoff_eye.cli import main

    ir = json.loads(GOLDEN_A.read_text(encoding="utf-8"))
    ir["regions"] = []
    ir_path = tmp_path / "no-regions.json"
    ir_path.write_text(json.dumps(ir), encoding="utf-8")
    job = tmp_path / "job"
    assert main([
        "build", str(ir_path), "--source", str(SOURCE_A),
        "--out", str(job), "--dpi", "72",
    ]) == 0
    review_file = tmp_path / "empty-review.json"
    review_file.write_text(json.dumps({"round": 1, "regions": [], "differences": []}), encoding="utf-8")
    assert main(["review", str(job), str(review_file)]) == 2
    assert main(["approve", str(job)]) == 2


def test_source_less_needs_human_job_rejects_source_review(tmp_path):
    from kirchhoff_eye.cli import main

    ir = json.loads(GOLDEN_A.read_text(encoding="utf-8"))
    ir["unknowns"] = [{
        "id": "UNK1", "at": [8, 8], "size": [1, 1], "pin_count": 0,
        "pins": [], "appearance": "unknown symbol",
    }]
    ir_path = tmp_path / "unknown.json"
    ir_path.write_text(json.dumps(ir), encoding="utf-8")
    job = tmp_path / "job"
    assert main(["build", str(ir_path), "--out", str(job), "--dpi", "72"]) == 0
    review_file = tmp_path / "review.json"
    _write_clean_review(review_file)
    assert main(["review", str(job), str(review_file)]) == 2


@pytest.mark.parametrize("payload", [[], "text", None])
def test_non_object_review_json_is_an_input_error(tmp_path, payload):
    from kirchhoff_eye.cli import main

    job = tmp_path / "job"
    assert main([
        "build", str(GOLDEN_A), "--source", str(SOURCE_A),
        "--out", str(job), "--dpi", "72",
    ]) == 0
    review_file = tmp_path / "review.json"
    review_file.write_text(json.dumps(payload), encoding="utf-8")
    assert main(["review", str(job), str(review_file)]) == 2


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
            "ir_path": "/components/1/label_at",
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
        "operations": [{"operation": "MOVE", "ir_path": "/components/1/label_at", "description": "调整", "difference_id": "D1"}]
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


def test_review_differences_are_bound_to_regions(tmp_path):
    from kirchhoff_eye.cli import main

    job = tmp_path / "job"
    assert main([
        "build", str(GOLDEN_A), "--source", str(SOURCE_A),
        "--out", str(job), "--dpi", "72",
    ]) == 0
    review_file = tmp_path / "review.json"
    _write_difference_review(review_file)
    report = json.loads(review_file.read_text(encoding="utf-8"))
    report["regions"][1]["conclusion"] = "differences"
    report["regions"][1]["summary"] = "也有差异"
    report["differences"][0]["region"] = report["regions"][0]["name"]
    review_file.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    assert main(["review", str(job), str(review_file)]) == 2

    _write_difference_review(review_file)
    report = json.loads(review_file.read_text(encoding="utf-8"))
    report["differences"][0]["region"] = report["regions"][1]["name"]
    review_file.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    assert main(["review", str(job), str(review_file)]) == 2


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
            {"operation": "MOVE", "ir_path": "/components/1/label_at", "description": f"调整 {index}", "difference_id": "D1"}
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
        "operations": [{"operation": "MOVE", "ir_path": "/components/1/label_at", "description": "调整", "difference_id": "D1"}]
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


@pytest.mark.parametrize("failure_point", ["feedback", "publish"])
def test_repair_publish_failure_rolls_back_every_live_artifact(tmp_path, monkeypatch, failure_point):
    import kirchhoff_eye.pipeline as pipeline
    from kirchhoff_eye.cli import main

    job = tmp_path / "job"
    assert main(["build", str(GOLDEN_A), "--source", str(SOURCE_A), "--out", str(job), "--dpi", "72"]) == 0
    round_review = tmp_path / "round-review.json"
    _write_difference_review(round_review)
    assert main(["review", str(job), str(round_review)]) == 0
    patches = tmp_path / "patches.json"
    _write_patches(patches, [{
        "operation": "MOVE", "ir_path": "/components/1/label_at", "description": "调整 R1",
    }])
    before = _job_bytes(job)

    if failure_point == "feedback":
        monkeypatch.setattr(
            pipeline, "_copy_feedback",
            lambda _output: (_ for _ in ()).throw(OSError("injected feedback failure")),
        )
    else:
        real_atomic_copy = pipeline._atomic_copy
        calls = {"count": 0}

        def fail_mid_publish(source, target):
            if ".next-round" in str(source):
                calls["count"] += 1
                if calls["count"] == 4:
                    raise OSError("injected publish failure")
            return real_atomic_copy(source, target)

        monkeypatch.setattr(pipeline, "_atomic_copy", fail_mid_publish)

    assert main([
        "repair", str(job), str(_moved_r1_ir(tmp_path / "repaired.json")),
        "--patches", str(patches), "--dpi", "72",
    ]) == 3

    assert _job_bytes(job) == before
    assert not (job / ".next-round").exists()
    assert not (job / "rounds" / "round-02").exists()


def test_repair_uses_unique_transaction_staging_directory(tmp_path, monkeypatch):
    import kirchhoff_eye.pipeline as pipeline
    from kirchhoff_eye.cli import main

    job = tmp_path / "job"
    assert main([
        "build", str(GOLDEN_A), "--source", str(SOURCE_A),
        "--out", str(job), "--dpi", "72",
    ]) == 0
    review_file = tmp_path / "review.json"
    _write_difference_review(review_file)
    assert main(["review", str(job), str(review_file)]) == 0
    patches = tmp_path / "patches.json"
    _write_patches(patches, [{
        "operation": "MOVE", "ir_path": "/components/1/label_at", "description": "调整 R1",
    }])
    seen = []
    real_mkdtemp = pipeline.tempfile.mkdtemp

    def record_mkdtemp(*args, **kwargs):
        path = real_mkdtemp(*args, **kwargs)
        if kwargs.get("prefix") == ".next-round-":
            seen.append(Path(path))
        return path

    monkeypatch.setattr(pipeline.tempfile, "mkdtemp", record_mkdtemp)
    assert main([
        "repair", str(job), str(_moved_r1_ir(tmp_path / "repaired.json")),
        "--patches", str(patches), "--dpi", "72",
    ]) == 0
    assert len(seen) == 1
    assert seen[0].parent == job
    assert not seen[0].exists()


def test_repair_uses_unique_verified_patch_file(tmp_path, monkeypatch):
    import kirchhoff_eye.pipeline as pipeline
    from kirchhoff_eye.cli import main

    job = tmp_path / "job"
    assert main([
        "build", str(GOLDEN_A), "--source", str(SOURCE_A),
        "--out", str(job), "--dpi", "72",
    ]) == 0
    review_file = tmp_path / "review.json"
    _write_difference_review(review_file)
    assert main(["review", str(job), str(review_file)]) == 0
    patches = tmp_path / "patches.json"
    _write_patches(patches, [{
        "operation": "MOVE", "ir_path": "/components/1/label_at", "description": "调整 R1",
    }])
    seen = []
    real_write = pipeline._write_json

    def record_write(path, data):
        if path.name.startswith(".verified-patches-"):
            seen.append(path)
        return real_write(path, data)

    monkeypatch.setattr(pipeline, "_write_json", record_write)
    assert main([
        "repair", str(job), str(_moved_r1_ir(tmp_path / "repaired.json")),
        "--patches", str(patches), "--dpi", "72",
    ]) == 0
    assert len(seen) == 1
    assert seen[0].parent == job
    assert not seen[0].exists()


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
            "ir_path": "/components/1/label_at",
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


@pytest.mark.parametrize("operation", ["ADD_COMPONENT", "REMOVE_COMPONENT"])
def test_patch_evidence_tracks_middle_array_insertions_and_removals(operation):
    from kirchhoff_eye.pipeline import _validate_patch_manifest

    original = {"components": [{"id": "A"}, {"id": "C"}, {"id": "D"}]}
    inserted = {"components": [{"id": "A"}, {"id": "B"}, {"id": "C"}, {"id": "D"}]}
    before, after = (original, inserted) if operation == "ADD_COMPONENT" else (inserted, original)
    state = {"rounds": [{"differences": [{
        "id": "D1", "patch_operation": operation, "ir_path": "/components/1",
    }]}]}
    patch_doc = {"operations": [{
        "difference_id": "D1", "operation": operation,
        "ir_path": "/components/1", "description": "调整中部元件",
    }]}

    assert _validate_patch_manifest(before, after, state, patch_doc)["changed_paths"] == ["/components/1"]


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

    with pytest.raises(ValueError, match="not valid for IR path"):
        _validate_patch_manifest(before, after, state, patch_doc)


def test_add_remove_operations_are_bound_to_their_canonical_collections():
    from kirchhoff_eye.pipeline import _validate_patch_manifest

    before = {"texts": [{"content": "old"}]}
    after = {"texts": [{"content": "old"}, {"content": "new"}]}
    state = {"rounds": [{"differences": [{
        "id": "D1",
        "patch_operation": "ADD_COMPONENT",
        "ir_path": "/texts/1",
    }]}]}
    patch_doc = {"operations": [{
        "difference_id": "D1",
        "operation": "ADD_COMPONENT",
        "ir_path": "/texts/1",
        "description": "伪装成元件新增",
    }]}

    with pytest.raises(ValueError, match="not valid for IR path"):
        _validate_patch_manifest(before, after, state, patch_doc)


def test_patch_operations_use_canonical_field_paths():
    from kirchhoff_eye.pipeline import _validate_patch_manifest

    component_before = {"components": [{"value": "1k"}]}
    component_after = {"components": [{"value": "2k"}]}
    value_state = {"rounds": [{"differences": [{
        "id": "D1", "patch_operation": "SET_VALUE", "ir_path": "/components/0/value",
    }]}]}
    value_patch = {"operations": [{
        "difference_id": "D1", "operation": "SET_VALUE",
        "ir_path": "/components/0/value", "description": "更新值",
    }]}
    assert _validate_patch_manifest(
        component_before, component_after, value_state, value_patch,
    )["changed_paths"] == ["/components/0/value"]

    wire_before = {"wires": [{"points": [[0, 0], [1, 0]]}]}
    wire_after = {"wires": [{"points": [[0, 0], [0, 1], [1, 1]]}]}
    wire_state = {"rounds": [{"differences": [{
        "id": "D1", "patch_operation": "SET_WAYPOINTS", "ir_path": "/wires/0/points",
    }]}]}
    wire_patch = {"operations": [{
        "difference_id": "D1", "operation": "SET_WAYPOINTS",
        "ir_path": "/wires/0/points", "description": "更新转角",
    }]}
    assert _validate_patch_manifest(
        wire_before, wire_after, wire_state, wire_patch,
    )["changed_paths"] == ["/wires/0/points/1/0", "/wires/0/points/1/1", "/wires/0/points/2"]


def test_patch_manifest_rejects_duplicate_difference_references():
    from kirchhoff_eye.pipeline import _validate_patch_manifest

    before = {"components": [{"label_at": [1, 1]}]}
    after = {"components": [{"label_at": [2, 2]}]}
    state = {"rounds": [{"differences": [{
        "id": "D1", "patch_operation": "MOVE", "ir_path": "/components/0",
    }]}]}
    operation = {
        "difference_id": "D1", "operation": "MOVE",
        "ir_path": "/components/0", "description": "移动",
    }
    with pytest.raises(ValueError, match="referenced more than once"):
        _validate_patch_manifest(before, after, state, {"operations": [operation, dict(operation)]})


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
        "operations": [{"operation": "MOVE", "ir_path": "/components/1/label_at", "description": "调整", "difference_id": "D1"}]
    }), encoding="utf-8")
    assert main(["repair", str(job), str(_moved_r1_ir(tmp_path / "repaired.json")), "--patches", str(patches), "--dpi", "72"]) == 0
    review_2 = tmp_path / "review-2.json"
    _write_difference_review(review_2, round_number=2, count=1)

    assert main(["review", str(job), str(review_2)]) == 0
    state = json.loads((job / "review.json").read_text(encoding="utf-8"))
    assert state["status"] == "needs_human"
    assert "difference_count_not_decreasing" in state["reason_codes"]
    assert main(["repair", str(job), str(GOLDEN_A), "--patches", str(patches), "--dpi", "72"]) == 2


def test_patch_path_freeze_counts_distinct_rounds_not_duplicate_manifest_entries():
    from kirchhoff_eye.pipeline import _patch_path_reason

    duplicate_round = [{
        "applied_patches": [
            {"ir_path": "/components/1/label_at"},
            {"ir_path": "/components/1/label_at"},
            {"ir_path": "/components/1/label_at"},
        ],
    }]
    assert _patch_path_reason(duplicate_round) is None

    three_rounds = [
        {"applied_patches": [{"ir_path": "/components/1/label_at"}]}
        for _ in range(3)
    ]
    assert _patch_path_reason(three_rounds) == "patch_path_frozen:/components/1/label_at"
