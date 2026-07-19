# -*- coding: utf-8 -*-
"""Wire graph extraction keeps orthogonal conductor evidence and confidence."""
from pathlib import Path

from kirchhoff_eye.perception.preprocess import preprocess_image
from kirchhoff_eye.perception.wire_graph import extract_wire_graph


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "synthetic_images"


def test_divider_exposes_horizontal_and_vertical_conductor_candidates(tmp_path):
    report = preprocess_image(FIXTURES / "01-divider-base.png", tmp_path / "pre")
    graph = extract_wire_graph(report)

    assert any(segment.orientation == "horizontal" for segment in graph.segments)
    assert any(segment.orientation == "vertical" for segment in graph.segments)
    assert all(0 <= segment.confidence <= 1 for segment in graph.segments)
    assert all(segment.crop[2] > segment.crop[0] and segment.crop[3] > segment.crop[1]
               for segment in graph.segments)


def test_line_width_variant_retains_long_bus_candidates(tmp_path):
    report = preprocess_image(FIXTURES / "07-divider-lines.png", tmp_path / "pre")
    graph = extract_wire_graph(report)

    assert graph.line_width_px >= 1
    assert any(segment.length_px >= 60 for segment in graph.segments)
    assert not any(segment.orientation == "diagonal" for segment in graph.segments)


def test_weak_segments_are_retained_instead_of_dropped(tmp_path):
    report = preprocess_image(FIXTURES / "04-divider-blur.png", tmp_path / "pre")
    graph = extract_wire_graph(report)

    assert graph.segments
    assert any(segment.strength in {"weak", "strong"} for segment in graph.segments)
    assert all(segment.provenance == "orthogonal-run/1" for segment in graph.segments)


def test_extraction_is_deterministic(tmp_path):
    report = preprocess_image(FIXTURES / "10-rectifier.png", tmp_path / "pre")
    first = extract_wire_graph(report)
    second = extract_wire_graph(report)
    assert first == second
