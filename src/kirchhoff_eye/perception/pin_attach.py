"""Score explicit pin-to-wire alternatives without forcing ambiguous attachments."""
import math
from dataclasses import dataclass
from typing import Iterable, List, Sequence, Tuple

from .models import (
    PinAttachmentAlternative,
    PinAttachmentCandidate,
    SymbolCandidate,
    WireGraph,
    WireSegment,
)


@dataclass(frozen=True)
class PinObservation:
    pin_id: str
    at_px: Tuple[float, float]
    direction: str


def _point_segment_distance(point, segment: WireSegment) -> float:
    x, y = point
    if segment.orientation == "horizontal":
        x0, x1 = sorted((segment.start[0], segment.end[0]))
        px = min(max(x, x0), x1)
        return math.hypot(x - px, y - segment.start[1])
    y0, y1 = sorted((segment.start[1], segment.end[1]))
    py = min(max(y, y0), y1)
    return math.hypot(x - segment.start[0], y - py)


def _direction_score(pin: PinObservation, segment: WireSegment) -> float:
    x, y = pin.at_px
    if pin.direction in {"left", "right"} and segment.orientation != "horizontal":
        return 0.15
    if pin.direction in {"up", "down"} and segment.orientation != "vertical":
        return 0.15
    if pin.direction == "left":
        return 1.0 if segment.end[0] <= x + 2 else 0.2
    if pin.direction == "right":
        return 1.0 if segment.start[0] >= x - 2 else 0.2
    if pin.direction == "up":
        return 1.0 if segment.end[1] <= y + 2 else 0.2
    if pin.direction == "down":
        return 1.0 if segment.start[1] >= y - 2 else 0.2
    return 0.5


def _interior_penalty(symbol: SymbolCandidate, pin: PinObservation, segment: WireSegment) -> float:
    x0, y0, x1, y1 = symbol.crop
    x, y = pin.at_px
    if pin.direction == "left" and segment.end[0] > x + 2:
        return 0.65
    if pin.direction == "right" and segment.start[0] < x - 2:
        return 0.65
    if pin.direction == "up" and segment.end[1] > y + 2:
        return 0.65
    if pin.direction == "down" and segment.start[1] < y - 2:
        return 0.65
    if segment.orientation == "horizontal" and y0 < segment.start[1] < y1:
        overlap = max(0, min(segment.end[0], x1) - max(segment.start[0], x0))
        if overlap > 3:
            return 0.45
    if segment.orientation == "vertical" and x0 < segment.start[0] < x1:
        overlap = max(0, min(segment.end[1], y1) - max(segment.start[1], y0))
        if overlap > 3:
            return 0.45
    return 0.0


def attach_pins(
    symbols: Sequence[SymbolCandidate],
    pins: Sequence[PinObservation],
    graph: WireGraph,
) -> Tuple[PinAttachmentCandidate, ...]:
    by_symbol = {symbol.id: symbol for symbol in symbols}
    results = []
    max_distance = max(5.0, graph.line_width_px * 4.0)
    for pin in pins:
        symbol_id = pin.pin_id.split(".", 1)[0]
        symbol = by_symbol.get(symbol_id)
        alternatives: List[PinAttachmentAlternative] = []
        if symbol is not None:
            prelim = []
            for segment in graph.segments:
                distance = _point_segment_distance(pin.at_px, segment)
                if distance > max_distance * 3:
                    continue
                distance_score = max(0.0, 1.0 - distance / (max_distance * 3))
                direction_score = _direction_score(pin, segment)
                interior = _interior_penalty(symbol, pin, segment)
                base = 0.52 * distance_score + 0.38 * direction_score + 0.1 * segment.confidence - interior
                prelim.append((segment, distance, distance_score, direction_score, interior, max(0.0, base)))
            prelim.sort(key=lambda item: (-item[-1], item[0].id))
            top_score = prelim[0][-1] if prelim else 0.0
            for segment, distance, distance_score, direction_score, interior, base in prelim[:5]:
                competition = max(0.0, min(0.4, top_score - base < 0.12 and 0.18 or 0.0))
                score = round(max(0.0, base - competition), 4)
                alternatives.append(PinAttachmentAlternative(
                    segment_id=segment.id,
                    distance_px=round(distance, 4),
                    distance_score=round(distance_score, 4),
                    direction_score=round(direction_score, 4),
                    interior_penalty=round(interior, 4),
                    competition_penalty=round(competition, 4),
                    score=score,
                ))
        alternatives.sort(key=lambda item: (-item.score, item.segment_id))
        if not alternatives or alternatives[0].score < 0.25:
            status, selected, blocker = "unattached", None, "UNATTACHED_PIN"
        elif len(alternatives) > 1 and alternatives[0].score - alternatives[1].score < 0.12:
            status, selected, blocker = "ambiguous", None, "AMBIGUOUS_PIN_ATTACHMENT"
        elif alternatives[0].score >= 0.68 and alternatives[0].direction_score >= 0.7:
            status, selected, blocker = "attached", alternatives[0].segment_id, None
        elif alternatives[0].score >= 0.38:
            status, selected, blocker = "weak", None, "WEAK_PIN_ATTACHMENT"
        else:
            status, selected, blocker = "unattached", None, "UNATTACHED_PIN"
        results.append(PinAttachmentCandidate(
            pin_id=pin.pin_id, status=status, selected_segment_id=selected,
            blocking_reason_code=blocker, alternatives=tuple(alternatives),
        ))
    return tuple(results)
