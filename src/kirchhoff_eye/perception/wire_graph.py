"""Orthogonal conductor evidence extraction without heavy CV dependencies."""
from dataclasses import replace
from typing import Iterable, List, Sequence, Tuple

from PIL import Image, ImageOps

from .models import PreprocessReport, WireGraph, WireSegment


def _dark_mask(image: Image.Image, threshold: int = 150):
    gray = ImageOps.grayscale(image)
    return [[gray.getpixel((x, y)) < threshold for x in range(gray.width)] for y in range(gray.height)]


def _merge_runs(runs: Sequence[Tuple[int, int, int]], max_gap: int) -> List[Tuple[int, int, int]]:
    if not runs:
        return []
    merged = [list(runs[0])]
    for fixed, start, end in runs[1:]:
        previous = merged[-1]
        if fixed == previous[0] and start - previous[2] <= max_gap:
            previous[2] = max(previous[2], end)
        else:
            merged.append([fixed, start, end])
    return [tuple(item) for item in merged]


def _raw_horizontal(mask, min_length: int, max_gap: int):
    runs = []
    for y, row in enumerate(mask):
        start = None
        gaps = 0
        last_dark = None
        for x, dark in enumerate(row):
            if dark:
                if start is None:
                    start = x
                last_dark = x
                gaps = 0
            elif start is not None:
                gaps += 1
                if gaps > max_gap:
                    if last_dark is not None and last_dark - start + 1 >= min_length:
                        runs.append((y, start, last_dark))
                    start = None
                    last_dark = None
                    gaps = 0
        if start is not None and last_dark is not None and last_dark - start + 1 >= min_length:
            runs.append((y, start, last_dark))
    return runs


def _raw_vertical(mask, min_length: int, max_gap: int):
    height = len(mask)
    width = len(mask[0]) if height else 0
    runs = []
    for x in range(width):
        start = None
        gaps = 0
        last_dark = None
        for y in range(height):
            dark = mask[y][x]
            if dark:
                if start is None:
                    start = y
                last_dark = y
                gaps = 0
            elif start is not None:
                gaps += 1
                if gaps > max_gap:
                    if last_dark is not None and last_dark - start + 1 >= min_length:
                        runs.append((x, start, last_dark))
                    start = None
                    last_dark = None
                    gaps = 0
        if start is not None and last_dark is not None and last_dark - start + 1 >= min_length:
            runs.append((x, start, last_dark))
    return runs


def _cluster_parallel(runs: Iterable[Tuple[int, int, int]], tolerance: int, overlap_ratio: float = 0.65):
    clusters: List[List[Tuple[int, int, int]]] = []
    for run in sorted(runs):
        fixed, start, end = run
        placed = False
        for cluster in clusters:
            c_fixed = round(sum(item[0] for item in cluster) / len(cluster))
            c_start = min(item[1] for item in cluster)
            c_end = max(item[2] for item in cluster)
            overlap = max(0, min(end, c_end) - max(start, c_start) + 1)
            shorter = max(1, min(end - start + 1, c_end - c_start + 1))
            if abs(fixed - c_fixed) <= tolerance and overlap / shorter >= overlap_ratio:
                cluster.append(run)
                placed = True
                break
        if not placed:
            clusters.append([run])
    return clusters


def _segments_from_clusters(clusters, orientation: str, line_width: int, width: int, height: int):
    segments = []
    for index, cluster in enumerate(clusters, start=1):
        fixed = round(sum(item[0] for item in cluster) / len(cluster))
        start = min(item[1] for item in cluster)
        end = max(item[2] for item in cluster)
        thickness = max(1, max(item[0] for item in cluster) - min(item[0] for item in cluster) + 1)
        length = end - start + 1
        support = min(1.0, len(cluster) / max(1, line_width + 1))
        confidence = round(min(0.99, 0.45 + 0.35 * support + min(0.19, length / max(width, height))), 4)
        strength = "strong" if confidence >= 0.68 else "weak"
        pad = max(2, line_width * 2)
        if orientation == "horizontal":
            start_point, end_point = (start, fixed), (end, fixed)
            crop = (max(0, start - pad), max(0, fixed - pad), min(width, end + pad + 1), min(height, fixed + pad + 1))
        else:
            start_point, end_point = (fixed, start), (fixed, end)
            crop = (max(0, fixed - pad), max(0, start - pad), min(width, fixed + pad + 1), min(height, end + pad + 1))
        segments.append(WireSegment(
            id=("H" if orientation == "horizontal" else "V") + str(index),
            orientation=orientation,
            start=start_point,
            end=end_point,
            crop=crop,
            length_px=length,
            thickness_px=thickness,
            confidence=confidence,
            strength=strength,
        ))
    return segments


def extract_wire_graph(report: PreprocessReport) -> WireGraph:
    with Image.open(report.normalized_path) as image:
        image.load()
        width, height = image.size
        mask = _dark_mask(image)
    min_length = max(12, round(min(width, height) * 0.035))
    max_gap = max(1, report.line_width_px)
    horizontal = _raw_horizontal(mask, min_length, max_gap)
    vertical = _raw_vertical(mask, min_length, max_gap)
    tolerance = max(1, report.line_width_px + 1)
    h_clusters = _cluster_parallel(horizontal, tolerance)
    v_clusters = _cluster_parallel(vertical, tolerance)
    segments = (
        _segments_from_clusters(h_clusters, "horizontal", report.line_width_px, width, height)
        + _segments_from_clusters(v_clusters, "vertical", report.line_width_px, width, height)
    )
    # Stable order is part of the evidence contract and makes IDs reproducible.
    segments.sort(key=lambda item: (item.orientation, item.start, item.end))
    counters = {"horizontal": 0, "vertical": 0}
    stable = []
    for segment in segments:
        counters[segment.orientation] += 1
        prefix = "H" if segment.orientation == "horizontal" else "V"
        stable.append(replace(segment, id=f"{prefix}{counters[segment.orientation]}"))
    return WireGraph(report.normalized_path, report.line_width_px, tuple(stable))
