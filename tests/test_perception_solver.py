# -*- coding: utf-8 -*-
"""Global solver never converts blocking perception ambiguity into confident IR."""
import copy

from kirchhoff_eye.perception.models import (
    HypothesisAlternative,
    IntersectionCandidate,
    IntersectionEvidence,
    PinAttachmentCandidate,
    SymbolAlternative,
    SymbolCandidate,
)
from kirchhoff_eye.perception.solve import solve_candidates


def _intersection(status="unresolved"):
    return IntersectionCandidate(
        id="IX1", at_px=(100, 100), crop=(90, 90, 111, 111), confidence=0.55,
        alternatives=(
            HypothesisAlternative("connected_junction", "connected junction", 0.55),
            HypothesisAlternative("unconnected_crossing", "unconnected crossing", 0.45),
        ),
        resolution_status=status,
        selected_alternative_id="connected_junction" if status == "selected" else None,
        blocking_reason_code=None if status == "selected" else "AMBIGUOUS_JUNCTION_CROSSING",
        evidence=IntersectionEvidence(4, 0.3, "supported", ("H1", "V1")),
    )


def test_unresolved_topology_candidate_blocks_solver(golden_a):
    result = solve_candidates(copy.deepcopy(golden_a), intersections=[_intersection()])
    assert result.status == "needs_human"
    assert "AMBIGUOUS_JUNCTION_CROSSING" in result.reason_codes
    assert result.candidate_ir == golden_a


def test_unattached_pin_blocks_solver(golden_a):
    pin = PinAttachmentCandidate(
        pin_id="R1.1", status="unattached", selected_segment_id=None,
        blocking_reason_code="UNATTACHED_PIN", alternatives=(),
    )
    result = solve_candidates(copy.deepcopy(golden_a), pin_attachments=[pin])
    assert result.status == "needs_human"
    assert result.reason_codes == ["UNATTACHED_PIN"]


def test_unresolved_symbol_class_blocks_solver(golden_a):
    symbol = SymbolCandidate(
        id="SYM1", crop=(0, 0, 10, 10), confidence=0.5,
        alternatives=(SymbolAlternative("resistor", 0, False, 0.5),),
        resolution_status="unresolved", selected_alternative_id=None,
        blocking_reason_code="AMBIGUOUS_SYMBOL_CLASS",
    )
    result = solve_candidates(copy.deepcopy(golden_a), symbols=[symbol])
    assert result.status == "needs_human"
    assert result.review_queue[0]["candidate_id"] == "SYM1"


def test_zero_blockers_keeps_candidate_ir_for_canonical_validation(golden_a):
    result = solve_candidates(copy.deepcopy(golden_a), intersections=[_intersection("selected")])
    assert result.status == "candidate"
    assert result.reason_codes == []
    assert result.candidate_ir == golden_a
    assert result.review_queue == []
