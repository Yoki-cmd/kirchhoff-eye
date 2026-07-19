"""Conservative global consistency gate for perception hypotheses."""
from typing import Iterable, Sequence

from .models import (
    IntersectionCandidate,
    PinAttachmentCandidate,
    SolverResult,
    SymbolCandidate,
)


PRIORITY = {
    "AMBIGUOUS_PIN_ATTACHMENT": "blocking",
    "UNATTACHED_PIN": "blocking",
    "WEAK_PIN_ATTACHMENT": "blocking",
    "AMBIGUOUS_JUNCTION_CROSSING": "blocking",
    "AMBIGUOUS_SYMBOL_CLASS": "blocking",
}


def _collect(items, id_attr):
    reasons = []
    queue = []
    for item in items:
        reason = getattr(item, "blocking_reason_code", None)
        if not reason:
            continue
        if reason not in reasons:
            reasons.append(reason)
        queue.append({
            "candidate_id": getattr(item, id_attr),
            "priority": PRIORITY.get(reason, "blocking"),
            "reason_code": reason,
        })
    return reasons, queue


def solve_candidates(
    candidate_ir,
    symbols: Sequence[SymbolCandidate] = (),
    intersections: Sequence[IntersectionCandidate] = (),
    pin_attachments: Sequence[PinAttachmentCandidate] = (),
) -> SolverResult:
    """Return the unchanged candidate IR plus explicit blockers.

    Projection from pixel hypotheses into IR is intentionally not performed here unless a
    caller has already authored/reviewed a canonical seed IR. The solver's first product
    responsibility is refusing contradictions and unresolved topology, not fabricating a
    complete graph from weak local proposals.
    """
    reason_codes = []
    review_queue = []
    for items, id_attr in (
        (symbols, "id"),
        (intersections, "id"),
        (pin_attachments, "pin_id"),
    ):
        reasons, queue = _collect(items, id_attr)
        for reason in reasons:
            if reason not in reason_codes:
                reason_codes.append(reason)
        review_queue.extend(queue)
    return SolverResult(
        status="needs_human" if reason_codes else "candidate",
        candidate_ir=candidate_ir,
        reason_codes=reason_codes,
        review_queue=review_queue,
    )
