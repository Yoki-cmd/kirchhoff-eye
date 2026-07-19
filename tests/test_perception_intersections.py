# -*- coding: utf-8 -*-
"""Intersection candidates preserve junction/crossing alternatives and local evidence."""
from pathlib import Path

from kirchhoff_eye.perception.intersections import detect_intersection_candidates
from kirchhoff_eye.perception.preprocess import preprocess_image
from kirchhoff_eye.perception.wire_graph import extract_wire_graph


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "synthetic_images"


def _candidates(name, tmp_path):
    report = preprocess_image(FIXTURES / name, tmp_path / name[:-4])
    return detect_intersection_candidates(report, extract_wire_graph(report))


def test_rectifier_intersection_has_finite_junction_and_crossing_alternatives(tmp_path):
    candidates = _candidates("10-rectifier.png", tmp_path)

    assert candidates
    assert any({alternative.id for alternative in candidate.alternatives}
               == {"connected_junction", "unconnected_crossing"}
               for candidate in candidates)
    assert all(candidate.crop[2] > candidate.crop[0] and candidate.crop[3] > candidate.crop[1]
               for candidate in candidates)


def test_detector_does_not_make_center_pixel_the_only_decision(tmp_path):
    candidates = _candidates("10-rectifier.png", tmp_path)
    ambiguous = [candidate for candidate in candidates if candidate.resolution_status == "unresolved"]

    assert ambiguous, "plain crossing evidence should remain reviewable when the dot test is not decisive"
    assert all(candidate.evidence.branch_count >= 3 for candidate in ambiguous)
    assert all(candidate.evidence.line_continuity in {"supported", "weak"} for candidate in ambiguous)


def test_divider_junction_candidates_include_dot_and_branch_evidence(tmp_path):
    candidates = _candidates("19-node-polarity.png", tmp_path)

    assert candidates
    assert any(candidate.evidence.dot_score > 0 for candidate in candidates)
    assert any(candidate.evidence.branch_count >= 3 for candidate in candidates)


def test_intersection_candidates_are_deterministic(tmp_path):
    first = _candidates("10-rectifier.png", tmp_path / "a")
    second = _candidates("10-rectifier.png", tmp_path / "b")
    assert first == second
