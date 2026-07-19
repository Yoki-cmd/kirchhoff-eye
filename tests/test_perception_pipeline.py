# -*- coding: utf-8 -*-
"""Perception pipeline produces evidence-bound candidate jobs and honest statuses."""
import json
from pathlib import Path

import pytest
from PIL import Image

from kirchhoff_eye.perception.pipeline import perceive


FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures"


def test_out_of_scope_image_creates_needs_human_job_without_candidate_ir(tmp_path):
    out = tmp_path / "small-job"
    result = perceive(FIXTURE_ROOT / "synthetic_images" / "01-divider-base.png", out)

    assert result.status == "needs_human"
    state = json.loads((out / "review.json").read_text(encoding="utf-8"))
    evidence = json.loads((out / "perception-evidence.json").read_text(encoding="utf-8"))
    assert "SHORT_EDGE_BELOW_600" in state["reason_codes"]
    assert evidence["source"]["sha256"]
    assert not (out / "candidate.ir.json").exists()


def test_large_image_without_model_stays_needs_human_with_reviewable_evidence(tmp_path):
    source = FIXTURE_ROOT / "synthetic_images" / "10-rectifier.png"
    large = tmp_path / "large.png"
    with Image.open(source) as image:
        image.resize((image.width * 4, image.height * 4)).save(large)
    out = tmp_path / "large-job"

    result = perceive(large, out)

    assert result.status == "needs_human"
    evidence = json.loads((out / "perception-evidence.json").read_text(encoding="utf-8"))
    assert evidence["candidates"]
    assert evidence["review_queue"]
    assert all(item["priority"] in {"blocking", "high", "normal", "low"}
               for item in evidence["review_queue"])
    assert (out / "preprocess" / "normalized.png").is_file()


@pytest.mark.tex
def test_seed_ir_is_hash_bound_and_enters_standard_eye_review_job_when_no_blocker(tmp_path, monkeypatch, golden_a):
    source = tmp_path / "large-source.png"
    Image.new("L", (800, 600), 255).save(source)
    seed = tmp_path / "seed.ir.json"
    seed.write_text(json.dumps(golden_a), encoding="utf-8")
    out = tmp_path / "seeded-job"

    monkeypatch.setattr("kirchhoff_eye.perception.pipeline.generate_symbol_candidates", lambda *_args, **_kwargs: ())
    monkeypatch.setattr("kirchhoff_eye.perception.pipeline.extract_wire_graph", lambda report: type(
        "Graph", (), {"image_path": report.normalized_path, "line_width_px": report.line_width_px, "segments": ()}
    )())
    monkeypatch.setattr("kirchhoff_eye.perception.pipeline.detect_intersection_candidates", lambda *_args: ())

    result = perceive(source, out, seed_ir=seed, dpi=72)

    assert result.status == "needs_review"
    state = json.loads((out / "review.json").read_text(encoding="utf-8"))
    evidence = json.loads((out / "perception-evidence.json").read_text(encoding="utf-8"))
    assert state["status"] == "needs_review"
    assert evidence["candidate_ir_sha256"] == state["rounds"][0]["ir_sha256"]
    assert (out / "circuit.ir.json").is_file()
    assert (out / "circuit.png").is_file()
    assert (out / "cmp_round1.png").is_file()


def test_reusing_output_removes_stale_candidate_and_evidence(tmp_path):
    out = tmp_path / "job"
    out.mkdir()
    (out / "candidate.ir.json").write_text("stale", encoding="utf-8")
    (out / "perception-evidence.json").write_text("stale", encoding="utf-8")

    result = perceive(FIXTURE_ROOT / "synthetic_images" / "01-divider-base.png", out)

    assert result.status == "needs_human"
    assert not (out / "candidate.ir.json").exists()
    assert json.loads((out / "perception-evidence.json").read_text(encoding="utf-8"))["version"] == \
        "kirchhoff-perception-evidence/1.0"
