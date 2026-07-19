# -*- coding: utf-8 -*-
"""Pin attachment combines distance, direction, traversal, and competition evidence."""
from kirchhoff_eye.perception.models import SymbolCandidate, SymbolAlternative, WireGraph, WireSegment
from kirchhoff_eye.perception.pin_attach import PinObservation, attach_pins


def _graph(*segments):
    return WireGraph(image_path=None, line_width_px=2, segments=tuple(segments))


def _segment(id_, orientation, start, end):
    return WireSegment(
        id=id_, orientation=orientation, start=start, end=end,
        crop=(0, 0, 100, 100),
        length_px=abs(end[0] - start[0]) + abs(end[1] - start[1]) + 1,
        thickness_px=2, confidence=0.9, strength="strong",
    )


def _symbol():
    return SymbolCandidate(
        id="S1", crop=(40, 40, 60, 60), confidence=0.8,
        alternatives=(SymbolAlternative("resistor", 0, False, 0.8),),
        resolution_status="selected", selected_alternative_id="resistor:0:0",
        blocking_reason_code=None,
    )


def test_clear_pin_to_wire_attachment_is_selected():
    result = attach_pins(
        [_symbol()],
        [PinObservation("S1.1", (40, 50), "left")],
        _graph(_segment("H1", "horizontal", (5, 50), (40, 50))),
    )
    assert result[0].status == "attached"
    assert result[0].selected_segment_id == "H1"
    assert result[0].alternatives[0].direction_score > 0


def test_competing_nearby_wires_leave_pin_ambiguous():
    result = attach_pins(
        [_symbol()],
        [PinObservation("S1.1", (40, 50), "left")],
        _graph(
            _segment("H1", "horizontal", (5, 49), (40, 49)),
            _segment("H2", "horizontal", (5, 51), (40, 51)),
        ),
    )
    assert result[0].status == "ambiguous"
    assert result[0].blocking_reason_code == "AMBIGUOUS_PIN_ATTACHMENT"
    assert len(result[0].alternatives) == 2


def test_wrong_direction_and_component_interior_traversal_are_penalized():
    result = attach_pins(
        [_symbol()],
        [PinObservation("S1.1", (40, 50), "left")],
        _graph(_segment("H1", "horizontal", (40, 50), (90, 50))),
    )
    assert result[0].alternatives[0].direction_score < 0.5
    assert result[0].alternatives[0].interior_penalty > 0
    assert result[0].status in {"weak", "unattached"}


def test_no_compatible_wire_is_blocking_unattached():
    result = attach_pins(
        [_symbol()],
        [PinObservation("S1.1", (40, 50), "left")],
        _graph(_segment("V1", "vertical", (90, 5), (90, 95))),
    )
    assert result[0].status == "unattached"
    assert result[0].blocking_reason_code == "UNATTACHED_PIN"
