# -*- coding: utf-8 -*-
"""Bounded perception rejects or escalates inputs instead of guessing scope."""
from pathlib import Path

from PIL import Image

from kirchhoff_eye.perception.scope import assess_image_scope


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "synthetic_images"


def test_short_edge_below_contract_is_out_of_scope(tmp_path):
    image = tmp_path / "small.png"
    Image.new("RGB", (599, 900), "white").save(image)

    result = assess_image_scope(image)

    assert result.status == "needs_human"
    assert "SHORT_EDGE_BELOW_600" in result.reason_codes


def test_supported_dimensions_remain_eligible_but_unverified_without_detectors(tmp_path):
    image = tmp_path / "eligible.png"
    Image.new("RGB", (1200, 800), "white").save(image)

    result = assess_image_scope(image)

    assert result.status == "eligible"
    assert result.width_px == 1200 and result.height_px == 800
    assert "COMPONENT_COUNT_UNVERIFIED" in result.review_items
    assert "SUBFIGURE_COUNT_UNVERIFIED" in result.review_items


def test_missing_or_non_image_input_is_reported_as_input_error(tmp_path):
    missing = assess_image_scope(tmp_path / "missing.png")
    assert missing.status == "input_error"
    text = tmp_path / "not-image.txt"
    text.write_text("not an image", encoding="utf-8")
    invalid = assess_image_scope(text)
    assert invalid.status == "input_error"
    assert invalid.reason_codes == ["UNREADABLE_IMAGE"]


def test_public_synthetic_fixture_reports_real_dimensions():
    result = assess_image_scope(FIXTURES / "19-node-polarity.png")
    assert result.width_px > 0 and result.height_px > 0
    # The public 72-DPI fixture is intentionally below the product 600px envelope.
    assert result.status == "needs_human"
    assert "SHORT_EDGE_BELOW_600" in result.reason_codes
