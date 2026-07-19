# -*- coding: utf-8 -*-
"""Preprocessing is deterministic, content-addressed, and transform-preserving."""
import hashlib
from pathlib import Path

from PIL import Image

from kirchhoff_eye.perception.preprocess import preprocess_image


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "synthetic_images"


def _pixel_digest(path):
    with Image.open(path) as image:
        return hashlib.sha256(image.convert("L").tobytes()).hexdigest()


def test_preprocess_does_not_overwrite_source_and_is_byte_deterministic(tmp_path):
    source = FIXTURES / "06-divider-paper.png"
    before = source.read_bytes()

    first = preprocess_image(source, tmp_path / "first")
    second = preprocess_image(source, tmp_path / "second")

    assert source.read_bytes() == before
    assert first.source_sha256 == hashlib.sha256(before).hexdigest()
    assert first.normalized_sha256 == second.normalized_sha256
    assert first.normalized_path.read_bytes() == second.normalized_path.read_bytes()
    assert first.normalized_path != source


def test_preprocess_normalizes_gray_blur_jpeg_and_paper_variants(tmp_path):
    names = [
        "03-divider-jpeg.png", "04-divider-blur.png", "05-divider-gray.png",
        "06-divider-paper.png", "07-divider-lines.png",
    ]
    reports = [preprocess_image(FIXTURES / name, tmp_path / name[:-4]) for name in names]

    assert all(report.mode == "L" for report in reports)
    assert all(report.line_width_px >= 1 for report in reports)
    assert all(report.normalized_path.is_file() for report in reports)
    assert len({_pixel_digest(report.normalized_path) for report in reports}) >= 3


def test_small_rotation_is_deskewed_and_transform_round_trips(tmp_path):
    report = preprocess_image(FIXTURES / "08-divider-rotate.png", tmp_path / "rotated")

    assert abs(report.deskew_degrees) > 0.25
    assert abs(report.deskew_degrees) <= 5.0
    point = (100.0, 80.0)
    normalized = report.source_to_normalized.apply(point)
    restored = report.normalized_to_source.apply(normalized)
    assert abs(restored[0] - point[0]) < 1e-6
    assert abs(restored[1] - point[1]) < 1e-6


def test_preprocess_report_uses_content_hashes_not_path_identity(tmp_path):
    source = FIXTURES / "05-divider-gray.png"
    copy_path = tmp_path / "renamed.png"
    copy_path.write_bytes(source.read_bytes())

    original = preprocess_image(source, tmp_path / "original-out")
    copied = preprocess_image(copy_path, tmp_path / "copy-out")

    assert original.source_sha256 == copied.source_sha256
    assert original.normalized_sha256 == copied.normalized_sha256


def test_preprocess_preserves_one_pixel_wires_and_capacitor_gaps(tmp_path):
    report = preprocess_image(FIXTURES / "01-divider-base.png", tmp_path / "base")

    with Image.open(report.normalized_path) as normalized:
        pixels = normalized.load()
        assert min(pixels[x, 5] for x in range(normalized.width)) < 80
        # The output must not be blanked by denoising; retain substantial dark evidence.
        assert sum(1 for value in normalized.getdata() if value < 100) > 100
