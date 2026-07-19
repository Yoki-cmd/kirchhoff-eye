"""Input-envelope checks for bounded perception."""
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from .models import ScopeAssessment


MIN_SHORT_EDGE = 600


def assess_image_scope(path) -> ScopeAssessment:
    image_path = Path(path)
    if not image_path.is_file():
        return ScopeAssessment(status="input_error", reason_codes=["MISSING_IMAGE"])
    try:
        with Image.open(image_path) as image:
            image.load()
            width, height = image.size
    except (OSError, UnidentifiedImageError):
        return ScopeAssessment(status="input_error", reason_codes=["UNREADABLE_IMAGE"])

    reasons = []
    short_edge = min(width, height)
    if short_edge < MIN_SHORT_EDGE:
        reasons.append("SHORT_EDGE_BELOW_600")
    status = "needs_human" if reasons else "eligible"
    # Component/subfigure counts require later detectors. They stay explicit review
    # items rather than becoming fabricated pass/fail claims at the scope-only stage.
    return ScopeAssessment(
        status=status,
        width_px=width,
        height_px=height,
        short_edge_px=short_edge,
        reason_codes=reasons,
        review_items=["COMPONENT_COUNT_UNVERIFIED", "SUBFIGURE_COUNT_UNVERIFIED"],
    )
