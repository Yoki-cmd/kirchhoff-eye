# -*- coding: utf-8 -*-
"""Public synthetic fixtures cover deterministic backend behavior without private scans."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import jsonschema
from PIL import Image, ImageDraw

from kirchhoff_eye.cli import main
from generate_synthetic_fixture import apply_variant, image_pixel_sha256


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
IR_DIR = FIXTURES / "synthetic_ir"
IMAGE_DIR = FIXTURES / "synthetic_images"
MANIFEST = FIXTURES / "synthetic_manifest.json"
GENERATOR = ROOT / "scripts" / "generate_synthetic_fixture.py"

REQUIRED_COVERAGE = {
    "resistors_capacitors_sources",
    "diodes_polar_capacitors",
    "bjt_mos",
    "opamp",
    "multiple_buses",
    "junction_connected",
    "crossing_unconnected",
    "current_arrow",
    "voltage_polarity",
}
REQUIRED_VARIANTS = {
    "base",
    "scale",
    "jpeg_compression",
    "mild_blur",
    "grayscale",
    "paper_tint",
    "line_width",
    "small_rotation",
    "label_displacement",
}


def load_manifest(path=MANIFEST):
    return json.loads(path.read_text(encoding="utf-8"))


def test_resampling_constants_support_pillow_9_api(monkeypatch):
    import generate_synthetic_fixture as generator

    monkeypatch.delattr(generator.Image, "Resampling", raising=False)

    lanczos, bicubic = generator.resampling_filters()

    assert lanczos == generator.Image.LANCZOS
    assert bicubic == generator.Image.BICUBIC


def test_manifest_declares_twenty_public_synthetic_cases():
    manifest = load_manifest()
    cases = manifest["cases"]

    assert manifest["version"] == "kirchhoff-eye-synthetic/1.0"
    assert manifest["source_policy"] == "generated_from_public_ir_only"
    assert len(cases) == 20
    assert len({case["id"] for case in cases}) == 20
    assert REQUIRED_COVERAGE <= {tag for case in cases for tag in case["coverage"]}
    assert REQUIRED_VARIANTS <= {case["image_variant"] for case in cases}
    assert all("benchmark/cases" not in json.dumps(case) for case in cases)


def test_committed_fixture_ir_and_images_are_complete_and_schema_valid():
    manifest = load_manifest()
    schema = json.loads((ROOT / "schemas" / "ir.schema.json").read_text(encoding="utf-8"))
    validator = jsonschema.Draft7Validator(schema)

    for case in manifest["cases"]:
        ir_path = FIXTURES / case["ir"]
        image_path = FIXTURES / case["image"]
        ir = json.loads(ir_path.read_text(encoding="utf-8"))

        validator.validate(ir)
        assert ir_path.parent == IR_DIR
        assert image_path.parent == IMAGE_DIR
        assert image_path.suffix == ".png"
        assert image_path.stat().st_size > 300
        assert ir["meta"]["source_image"] == case["image"]


def test_generator_rebuilds_the_fixture_set(tmp_path):
    out = tmp_path / "fixtures"
    proc = subprocess.run(
        [sys.executable, str(GENERATOR), "--out", str(out), "--dpi", "72"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    generated = load_manifest(out / "synthetic_manifest.json")
    committed = load_manifest()
    assert [
        {key: value for key, value in case.items() if key != "sha256"}
        for case in generated["cases"]
    ] == [
        {key: value for key, value in case.items() if key != "sha256"}
        for case in committed["cases"]
    ]
    assert len(list((out / "synthetic_ir").glob("*.json"))) == 20
    assert len(list((out / "synthetic_images").glob("*.png"))) == 20
    for case in committed["cases"]:
        assert json.loads((out / case["ir"]).read_text(encoding="utf-8")) == json.loads(
            (FIXTURES / case["ir"]).read_text(encoding="utf-8")
        )
        generated_image = Image.open(out / case["image"]).convert("RGB")
        committed_image = Image.open(FIXTURES / case["image"]).convert("RGB")
        assert generated_image.size == committed_image.size
        assert generated_image.tobytes() == committed_image.tobytes()
        assert case["sha256"]["ir"] == hashlib.sha256((FIXTURES / case["ir"]).read_bytes()).hexdigest()
        assert case["sha256"]["image_pixels"] == image_pixel_sha256(FIXTURES / case["image"])


def test_label_displacement_is_local_and_preserves_remote_geometry(tmp_path):
    source = tmp_path / "source.png"
    output = tmp_path / "output.png"
    image = Image.new("RGB", (200, 100), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((80, 20, 95, 30), fill="black")
    draw.line((20, 70, 20, 90), fill="black", width=3)
    image.save(source)

    apply_variant(source, output, "label_displacement")

    moved = Image.open(output).convert("RGB")
    assert moved.crop((15, 65, 26, 96)).tobytes() == image.crop((15, 65, 26, 96)).tobytes()
    assert moved.crop((78, 18, 98, 33)).getbbox() is not None
    assert moved.crop((100, 18, 125, 33)).getextrema()[0][0] == 0


def test_line_width_variant_thickens_strokes(tmp_path):
    source = tmp_path / "source.png"
    output = tmp_path / "output.png"
    image = Image.new("RGB", (60, 40), "white")
    ImageDraw.Draw(image).line((10, 20, 50, 20), fill="black", width=1)
    image.save(source)

    apply_variant(source, output, "line_width")

    thickened = Image.open(output).convert("L")
    source_dark = sum(image.convert("L").histogram()[:128])
    output_dark = sum(thickened.histogram()[:128])
    assert output_dark > source_dark


def test_committed_label_variant_matches_deterministic_transform(tmp_path):
    output = tmp_path / "label.png"

    apply_variant(IMAGE_DIR / "01-divider-base.png", output, "label_displacement")

    generated = Image.open(output).convert("RGB")
    committed = Image.open(IMAGE_DIR / "09-divider-label.png").convert("RGB")
    assert generated.size == committed.size
    assert generated.tobytes() == committed.tobytes()


def test_all_synthetic_ir_cases_build_end_to_end(tmp_path):
    manifest = load_manifest()

    for case in manifest["cases"]:
        ir_path = FIXTURES / case["ir"]
        out = tmp_path / case["id"]
        rc = main(["build", str(ir_path), "--out", str(out), "--dpi", "72"])

        assert rc == 0, case["id"]
        assert (out / "circuit.tex").stat().st_size > 0
        assert (out / "circuit.png").stat().st_size > 0
        assert (out / "circuit.debug.png").stat().st_size > 0
        assert (out / "validation.json").exists()
        assert (out / "layout_report.json").exists()
