"""Generate finite junction/crossing candidates from orthogonal wire evidence."""
from typing import List, Tuple

from PIL import Image, ImageOps

from .models import (
    HypothesisAlternative,
    IntersectionCandidate,
    IntersectionEvidence,
    PreprocessReport,
    WireGraph,
)


def _near(value: int, low: int, high: int, tolerance: int) -> bool:
    return low - tolerance <= value <= high + tolerance


def _branch_support(horizontal, vertical, x: int, y: int, tolerance: int) -> Tuple[bool, bool, bool, bool]:
    left = x - horizontal.start[0] >= tolerance
    right = horizontal.end[0] - x >= tolerance
    up = y - vertical.start[1] >= tolerance
    down = vertical.end[1] - y >= tolerance
    return left, right, up, down


def _dot_score(gray: Image.Image, x: int, y: int, line_width: int) -> float:
    radius = max(2, line_width * 2)
    x0, y0 = max(0, x - radius), max(0, y - radius)
    x1, y1 = min(gray.width, x + radius + 1), min(gray.height, y + radius + 1)
    values = [gray.getpixel((px, py)) for py in range(y0, y1) for px in range(x0, x1)]
    if not values:
        return 0.0
    darkness = sum((255 - value) / 255.0 for value in values) / len(values)
    # A dot is a local blob beyond two ordinary thin strokes. This is evidence only;
    # it never becomes the sole semantic decision.
    baseline = min(0.55, (2 * line_width + 1) / max(1, (2 * radius + 1)))
    return round(max(0.0, min(1.0, (darkness - baseline * 0.35) / 0.45)), 4)


def detect_intersection_candidates(
    report: PreprocessReport, graph: WireGraph
) -> Tuple[IntersectionCandidate, ...]:
    with Image.open(report.normalized_path) as image:
        gray = ImageOps.grayscale(image)
        width, height = gray.size
    horizontal = [segment for segment in graph.segments if segment.orientation == "horizontal"]
    vertical = [segment for segment in graph.segments if segment.orientation == "vertical"]
    tolerance = max(2, report.line_width_px * 2)
    candidates: List[IntersectionCandidate] = []
    seen = set()
    for h in horizontal:
        hy = h.start[1]
        hx0, hx1 = sorted((h.start[0], h.end[0]))
        for v in vertical:
            vx = v.start[0]
            vy0, vy1 = sorted((v.start[1], v.end[1]))
            if not _near(vx, hx0, hx1, tolerance) or not _near(hy, vy0, vy1, tolerance):
                continue
            point = (vx, hy)
            key = (round(vx / tolerance), round(hy / tolerance))
            if key in seen:
                continue
            seen.add(key)
            branches = _branch_support(h, v, vx, hy, tolerance)
            branch_count = sum(branches)
            if branch_count < 3:
                continue
            dot = _dot_score(gray, vx, hy, report.line_width_px)
            full_cross = branch_count == 4
            continuity = "supported" if min(h.confidence, v.confidence) >= 0.62 else "weak"
            # Dot/branch/continuity evidence jointly rank finite hypotheses. Borderline
            # cases remain unresolved instead of being coerced into topology.
            connected_score = 0.34 + 0.34 * dot + 0.08 * (branch_count - 3)
            crossing_score = 0.32 + (0.22 if full_cross else 0.0) + 0.12 * (1.0 - dot)
            total = connected_score + crossing_score
            connected = round(connected_score / total, 4)
            crossing = round(crossing_score / total, 4)
            margin = abs(connected - crossing)
            if margin >= 0.28 and (dot >= 0.55 or (full_cross and dot <= 0.12)):
                selected = "connected_junction" if connected > crossing else "unconnected_crossing"
                resolution = "selected"
                blocker = None
            else:
                selected = None
                resolution = "unresolved"
                blocker = "AMBIGUOUS_JUNCTION_CROSSING"
            pad = max(8, report.line_width_px * 5)
            crop = (max(0, vx - pad), max(0, hy - pad), min(width, vx + pad + 1), min(height, hy + pad + 1))
            candidates.append(IntersectionCandidate(
                id=f"IX{len(candidates) + 1}",
                at_px=point,
                crop=crop,
                confidence=round(max(connected, crossing), 4),
                alternatives=(
                    HypothesisAlternative("connected_junction", "connected junction", connected),
                    HypothesisAlternative("unconnected_crossing", "unconnected crossing", crossing),
                ),
                resolution_status=resolution,
                selected_alternative_id=selected,
                blocking_reason_code=blocker,
                evidence=IntersectionEvidence(
                    branch_count=branch_count,
                    dot_score=dot,
                    line_continuity=continuity,
                    incident_segment_ids=(h.id, v.id),
                ),
            ))
    candidates.sort(key=lambda item: (item.at_px[1], item.at_px[0]))
    # Renumber after sort to make evidence IDs stable.
    return tuple(
        IntersectionCandidate(
            id=f"IX{index}", at_px=item.at_px, crop=item.crop,
            confidence=item.confidence, alternatives=item.alternatives,
            resolution_status=item.resolution_status,
            selected_alternative_id=item.selected_alternative_id,
            blocking_reason_code=item.blocking_reason_code, evidence=item.evidence,
        )
        for index, item in enumerate(candidates, start=1)
    )
