"""Conservative catalog-bounded symbol hypothesis generation.

This is an experimental proposal stage, not a trained detector. It identifies ink groups,
computes simple shape evidence, and produces finite catalog shortlists. Ambiguous candidates
stay unresolved and therefore cannot become trusted IR without review/solver evidence.
"""
import json
import math
from collections import deque
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Set, Tuple

from PIL import Image, ImageOps

from .models import PreprocessReport, SymbolAlternative, SymbolCandidate


Rect = Tuple[int, int, int, int]


def _dark_points(image: Image.Image, threshold: int = 150) -> Set[Tuple[int, int]]:
    gray = ImageOps.grayscale(image)
    return {
        (x, y)
        for y in range(gray.height)
        for x in range(gray.width)
        if gray.getpixel((x, y)) < threshold
    }


def _remove_long_orthogonal_runs(points: Set[Tuple[int, int]], width: int, height: int):
    """Mask obvious long conductors before ink-component grouping.

    This is deliberately conservative: only straight runs spanning at least six percent
    of the image are removed. Short symbol bars and plates remain available as evidence.
    """
    remaining = set(points)
    min_horizontal = max(18, round(width * 0.06))
    min_vertical = max(18, round(height * 0.06))
    for y in range(height):
        xs = sorted(x for x, py in points if py == y)
        start = previous = None
        for x in xs + [None]:
            if x is not None and (previous is None or x == previous + 1):
                start = x if start is None else start
                previous = x
                continue
            if start is not None and previous - start + 1 >= min_horizontal:
                remaining.difference_update((px, y) for px in range(start, previous + 1))
            start = previous = x
    for x in range(width):
        ys = sorted(y for px, y in points if px == x)
        start = previous = None
        for y in ys + [None]:
            if y is not None and (previous is None or y == previous + 1):
                start = y if start is None else start
                previous = y
                continue
            if start is not None and previous - start + 1 >= min_vertical:
                remaining.difference_update((x, py) for py in range(start, previous + 1))
            start = previous = y
    return remaining


def _dilate(points: Set[Tuple[int, int]], radius: int, width: int, height: int):
    expanded = set()
    for x, y in points:
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                if abs(dx) + abs(dy) > radius:
                    continue
                px, py = x + dx, y + dy
                if 0 <= px < width and 0 <= py < height:
                    expanded.add((px, py))
    return expanded


def _components(points: Set[Tuple[int, int]]):
    remaining = set(points)
    groups = []
    while remaining:
        seed = remaining.pop()
        queue = deque([seed])
        group = {seed}
        while queue:
            x, y = queue.popleft()
            for neighbor in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    group.add(neighbor)
                    queue.append(neighbor)
        groups.append(group)
    return groups


def _bbox(points: Iterable[Tuple[int, int]]) -> Rect:
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs) + 1, max(ys) + 1


def _merge_boxes(boxes: Sequence[Rect], gap: int) -> List[Rect]:
    merged = list(boxes)
    changed = True
    while changed:
        changed = False
        output = []
        while merged:
            a = merged.pop()
            ax0, ay0, ax1, ay1 = a
            hit = None
            for index, b in enumerate(merged):
                bx0, by0, bx1, by1 = b
                if ax0 <= bx1 + gap and bx0 <= ax1 + gap and ay0 <= by1 + gap and by0 <= ay1 + gap:
                    hit = index
                    break
            if hit is None:
                output.append(a)
                continue
            b = merged.pop(hit)
            merged.append((min(ax0, b[0]), min(ay0, b[1]), max(ax1, b[2]), max(ay1, b[3])))
            changed = True
        merged = output
    return sorted(merged, key=lambda box: (box[1], box[0]))


def _features(gray: Image.Image, box: Rect):
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0
    dark = sum(1 for y in range(y0, y1) for x in range(x0, x1) if gray.getpixel((x, y)) < 150)
    area = max(1, width * height)
    aspect = width / max(1.0, height)
    density = dark / area
    # Dominant diagonal evidence helps surface opamp shortlists; many vertical turns/loops
    # help transformer; wide sparse three-terminal shapes help switches.
    diagonal = 0
    for y in range(y0 + 1, y1 - 1):
        for x in range(x0 + 1, x1 - 1):
            if gray.getpixel((x, y)) >= 150:
                continue
            if (gray.getpixel((x - 1, y - 1)) < 150 and gray.getpixel((x + 1, y + 1)) < 150) or (
                gray.getpixel((x - 1, y + 1)) < 150 and gray.getpixel((x + 1, y - 1)) < 150
            ):
                diagonal += 1
    return width, height, aspect, density, diagonal / max(1, dark)


def _rank_types(features, catalog: Dict[str, Dict[str, object]]):
    width, height, aspect, density, diagonal = features
    ranked = []
    for component_type, meta in catalog.items():
        kind = meta.get("kind")
        score = 0.2
        if kind == "two":
            score += 0.22 if max(aspect, 1 / max(aspect, 1e-6)) >= 1.4 else 0.04
            score += 0.12 if density < 0.32 else 0.02
        elif kind == "multi":
            score += 0.16 if width >= 14 and height >= 14 else 0.02
        else:
            score += 0.08 if max(width, height) <= 35 else 0.01

        if component_type == "opamp":
            score += 0.48 * diagonal + (0.12 if aspect >= 1.1 else 0.0)
        elif component_type == "transformer":
            score += 0.16 if height >= width * 0.55 else 0.0
            score += 0.10 if density >= 0.12 else 0.0
        elif component_type == "spdt":
            score += 0.14 if aspect >= 1.3 and density < 0.28 else 0.0
        elif component_type in {"diode", "zener", "led"}:
            score += 0.18 if aspect >= 1.4 and diagonal > 0.01 else 0.0
        elif component_type in {"resistor", "inductor"}:
            score += 0.16 if max(aspect, 1 / max(aspect, 1e-6)) >= 1.6 else 0.0
        elif component_type in {"capacitor", "polar_capacitor"}:
            score += 0.14 if 0.45 <= aspect <= 2.2 and density < 0.3 else 0.0
        elif component_type in {"vsource", "isource", "battery"}:
            score += 0.12 if 0.65 <= aspect <= 1.45 else 0.0
        ranked.append((component_type, score))
    return sorted(ranked, key=lambda item: (-item[1], item[0]))


def generate_symbol_candidates(report: PreprocessReport, catalog_path) -> Tuple[SymbolCandidate, ...]:
    catalog_doc = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
    catalog = catalog_doc["components"]
    with Image.open(report.normalized_path) as opened:
        gray = ImageOps.grayscale(opened)
        points = _remove_long_orthogonal_runs(
            _dark_points(gray), gray.width, gray.height
        )
    if not points:
        return ()
    radius = max(1, report.line_width_px * 2)
    groups = _components(_dilate(points, radius, gray.width, gray.height))
    boxes = []
    min_area = max(9, report.line_width_px * report.line_width_px * 4)
    for group in groups:
        box = _bbox(group)
        area = (box[2] - box[0]) * (box[3] - box[1])
        if area >= min_area:
            boxes.append(box)
    boxes = _merge_boxes(boxes, max(2, report.line_width_px * 2))
    candidates = []
    for index, box in enumerate(boxes, start=1):
        features = _features(gray, box)
        ranked = _rank_types(features, catalog)
        # Keep a finite shortlist. Ensure one representative from the important public
        # multi-terminal families is present for local adjudication, but never select it
        # solely because it appears in the list.
        shortlist = ranked[:5]
        must_offer = ["opamp", "transformer", "spdt", "diode", "resistor"]
        for component_type in must_offer:
            if component_type not in {item[0] for item in shortlist}:
                score = next(score for name, score in ranked if name == component_type)
                shortlist.append((component_type, score))
        # Exactly five stable finite choices. Reserve three slots for public
        # multi-terminal adjudication and one each for diode/passive evidence.
        required = []
        for component_type in must_offer:
            score = next(score for name, score in shortlist if name == component_type)
            required.append((component_type, score))
        shortlist = sorted(required, key=lambda item: (-item[1], item[0]))
        alternatives = []
        for component_type, raw_score in shortlist:
            meta = catalog[component_type]
            rotate = 0 if features[2] >= 1 else 90
            alternatives.append(SymbolAlternative(component_type, rotate, False, round(min(0.99, raw_score), 4)))
        # The current public MVP has no trained/class-specific detector. Shape scores
        # rank finite local choices but never authorize a component class by themselves.
        status = "unresolved"
        selected = None
        blocker = "AMBIGUOUS_SYMBOL_CLASS"
        candidates.append(SymbolCandidate(
            id=f"SYM{index}", crop=box, confidence=alternatives[0].score,
            alternatives=tuple(alternatives), resolution_status=status,
            selected_alternative_id=selected, blocking_reason_code=blocker,
        ))
    return tuple(candidates)
