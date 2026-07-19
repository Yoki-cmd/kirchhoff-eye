"""Deterministic Pillow-only preprocessing for the bounded frontend."""
import hashlib
import json
import math
from pathlib import Path

from PIL import Image, ImageEnhance, ImageOps

from .models import Affine2D, PreprocessReport


RESAMPLING = getattr(Image, "Resampling", Image)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _foreground_mask(image: Image.Image, threshold: int = 180):
    return image.point(lambda value: 255 if value < threshold else 0, mode="1")


def _projection_score(mask: Image.Image, angle: float) -> float:
    rotated = mask.rotate(angle, resample=RESAMPLING.NEAREST, expand=False, fillcolor=0)
    width, height = rotated.size
    pixels = rotated.load()
    row_sums = []
    column_sums = []
    for y in range(height):
        row_sums.append(sum(1 for x in range(width) if pixels[x, y]))
    for x in range(width):
        column_sums.append(sum(1 for y in range(height) if pixels[x, y]))
    return sum(value * value for value in row_sums) + sum(value * value for value in column_sums)


def _estimate_deskew(gray: Image.Image) -> float:
    # Downsample only for angle estimation; the output image retains source dimensions.
    probe = gray.copy()
    max_side = max(probe.size)
    if max_side > 900:
        scale = 900.0 / max_side
        probe = probe.resize((max(1, round(probe.width * scale)), max(1, round(probe.height * scale))),
                             RESAMPLING.BILINEAR)
    mask = _foreground_mask(probe)
    candidates = [round(-5.0 + index * 0.25, 2) for index in range(41)]
    scored = [(angle, _projection_score(mask, angle)) for angle in candidates]
    best_angle, best_score = max(scored, key=lambda item: (item[1], -abs(item[0])))
    zero_score = next(score for angle, score in scored if angle == 0.0)
    # Avoid inventing rotation from text/noise when the gain is negligible.
    if best_score <= zero_score * 1.003:
        return 0.0
    return float(best_angle)


def _rotation_transform(width: int, height: int, degrees: float) -> Affine2D:
    radians = math.radians(degrees)
    cos_a = math.cos(radians)
    sin_a = math.sin(radians)
    cx = (width - 1) / 2.0
    cy = (height - 1) / 2.0
    return Affine2D(
        cos_a,
        sin_a,
        -sin_a,
        cos_a,
        cx - cos_a * cx + sin_a * cy,
        cy - sin_a * cx - cos_a * cy,
    )


def _estimate_line_width(gray: Image.Image) -> int:
    mask = _foreground_mask(gray)
    pixels = mask.load()
    widths = []
    # Sample runs away from the outer five pixels where rotation padding may occur.
    step_y = max(1, gray.height // 120)
    for y in range(5, max(5, gray.height - 5), step_y):
        start = None
        for x in range(5, max(5, gray.width - 5)):
            black = bool(pixels[x, y])
            if black and start is None:
                start = x
            elif not black and start is not None:
                length = x - start
                if 1 <= length <= 12:
                    widths.append(length)
                start = None
    if not widths:
        return 1
    widths.sort()
    return max(1, int(widths[len(widths) // 2]))


def preprocess_image(source, output_dir) -> PreprocessReport:
    source_path = Path(source).resolve()
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    source_bytes = source_path.read_bytes()
    with Image.open(source_path) as opened:
        opened.load()
        gray = ImageOps.grayscale(opened)
        width, height = gray.size

    deskew_degrees = _estimate_deskew(gray)
    transform = _rotation_transform(width, height, deskew_degrees)
    if deskew_degrees:
        gray = gray.rotate(deskew_degrees, resample=RESAMPLING.BICUBIC, expand=False, fillcolor=255)
    gray = ImageOps.autocontrast(gray, cutoff=0.5)
    gray = ImageEnhance.Contrast(gray).enhance(1.1)
    # Do not apply morphology or a median filter here: one-pixel public fixtures prove
    # those operations can erase real conductors or close capacitor gaps. Later stages
    # retain weak evidence instead of destructively cleaning it.
    line_width = _estimate_line_width(gray)

    normalized_path = output / "normalized.png"
    gray.save(normalized_path, format="PNG", optimize=False, compress_level=9)
    normalized_bytes = normalized_path.read_bytes()
    metadata = {
        "version": "kirchhoff-preprocess/1.0",
        "source_sha256": _sha256_bytes(source_bytes),
        "normalized_sha256": _sha256_bytes(normalized_bytes),
        "source_to_normalized": transform.as_list(),
        "normalized_to_source": transform.inverse().as_list(),
        "deskew_degrees": deskew_degrees,
        "line_width_px": line_width,
        "width_px": width,
        "height_px": height,
    }
    (output / "preprocess.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return PreprocessReport(
        source_path=source_path,
        normalized_path=normalized_path,
        source_sha256=metadata["source_sha256"],
        normalized_sha256=metadata["normalized_sha256"],
        width_px=width,
        height_px=height,
        mode="L",
        deskew_degrees=deskew_degrees,
        line_width_px=line_width,
        source_to_normalized=transform,
        normalized_to_source=transform.inverse(),
        metadata=metadata,
    )
