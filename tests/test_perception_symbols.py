# -*- coding: utf-8 -*-
"""Symbol candidates are finite catalog hypotheses, never unconstrained labels."""
from pathlib import Path

from PIL import Image

from kirchhoff_eye.perception.preprocess import preprocess_image
from kirchhoff_eye.perception.symbols import generate_symbol_candidates


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "synthetic_images"
CATALOG = ROOT / "catalog" / "components.json"


def _symbols(name, tmp_path):
    report = preprocess_image(FIXTURES / name, tmp_path / name[:-4])
    return generate_symbol_candidates(report, CATALOG)


def test_symbol_shortlists_are_finite_and_catalog_bounded(tmp_path):
    candidates = _symbols("01-divider-base.png", tmp_path)

    assert candidates
    assert all(1 <= len(candidate.alternatives) <= 5 for candidate in candidates)
    assert all(alternative.component_type for candidate in candidates for alternative in candidate.alternatives)
    assert all(candidate.crop[2] > candidate.crop[0] and candidate.crop[3] > candidate.crop[1]
               for candidate in candidates)


def test_supported_synthetic_families_surface_expected_type_in_some_shortlist(tmp_path):
    expectations = {
        "01-divider-base.png": "resistor",
        "10-rectifier.png": "diode",
        "14-opamp.png": "opamp",
        "15-transformer.png": "transformer",
        "16-spdt.png": "spdt",
    }
    for name, expected in expectations.items():
        candidates = _symbols(name, tmp_path / name[:-4])
        offered = {alternative.component_type for candidate in candidates for alternative in candidate.alternatives}
        assert expected in offered, f"{name} did not offer {expected}: {sorted(offered)}"


def test_low_information_blob_remains_unresolved_unknown(tmp_path):
    image = tmp_path / "blob.png"
    canvas = Image.new("L", (800, 600), 255)
    for y in range(250, 350):
        for x in range(350, 450):
            canvas.putpixel((x, y), 0)
    canvas.save(image)
    report = preprocess_image(image, tmp_path / "pre")

    candidates = generate_symbol_candidates(report, CATALOG)

    # A solid low-information blob may be rejected before candidate generation;
    # it must never be promoted to a confident catalog class.
    assert not candidates or all(candidate.resolution_status == "unresolved" for candidate in candidates)
    assert not candidates or any(candidate.blocking_reason_code == "AMBIGUOUS_SYMBOL_CLASS"
                                 for candidate in candidates)


def test_symbol_candidates_include_orientation_and_mirror_finite_choices(tmp_path):
    candidates = _symbols("14-opamp.png", tmp_path)
    opamp = next(candidate for candidate in candidates
                  if any(item.component_type == "opamp" for item in candidate.alternatives))
    alternatives = [item for item in opamp.alternatives if item.component_type == "opamp"]
    assert alternatives
    assert all(item.rotate in {0, 90, 180, 270} for item in alternatives)
    assert all(isinstance(item.mirror, bool) for item in alternatives)
