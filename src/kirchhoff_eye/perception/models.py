"""Small, dependency-light data models for the bounded perception frontend."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


Point = Tuple[float, float]
Rect = Tuple[int, int, int, int]


@dataclass(frozen=True)
class Affine2D:
    a: float
    b: float
    c: float
    d: float
    e: float
    f: float

    @classmethod
    def identity(cls) -> "Affine2D":
        return cls(1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

    def apply(self, point: Point) -> Point:
        x, y = point
        return (
            self.a * x + self.c * y + self.e,
            self.b * x + self.d * y + self.f,
        )

    def inverse(self) -> "Affine2D":
        determinant = self.a * self.d - self.b * self.c
        if abs(determinant) < 1e-12:
            raise ValueError("affine transform is singular")
        a = self.d / determinant
        b = -self.b / determinant
        c = -self.c / determinant
        d = self.a / determinant
        e = -(a * self.e + c * self.f)
        f = -(b * self.e + d * self.f)
        return Affine2D(a, b, c, d, e, f)

    def as_list(self) -> List[float]:
        return [self.a, self.b, self.c, self.d, self.e, self.f]


@dataclass(frozen=True)
class ScopeAssessment:
    status: str
    width_px: int = 0
    height_px: int = 0
    short_edge_px: int = 0
    reason_codes: List[str] = field(default_factory=list)
    review_items: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class PreprocessReport:
    source_path: Path
    normalized_path: Path
    source_sha256: str
    normalized_sha256: str
    width_px: int
    height_px: int
    mode: str
    deskew_degrees: float
    line_width_px: int
    source_to_normalized: Affine2D
    normalized_to_source: Affine2D
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WireSegment:
    id: str
    orientation: str
    start: Tuple[int, int]
    end: Tuple[int, int]
    crop: Rect
    length_px: int
    thickness_px: int
    confidence: float
    strength: str
    provenance: str = "orthogonal-run/1"


@dataclass(frozen=True)
class WireGraph:
    image_path: Path
    line_width_px: int
    segments: Tuple[WireSegment, ...]


@dataclass(frozen=True)
class HypothesisAlternative:
    id: str
    label: str
    score: float


@dataclass(frozen=True)
class IntersectionEvidence:
    branch_count: int
    dot_score: float
    line_continuity: str
    incident_segment_ids: Tuple[str, ...]


@dataclass(frozen=True)
class IntersectionCandidate:
    id: str
    at_px: Tuple[int, int]
    crop: Rect
    confidence: float
    alternatives: Tuple[HypothesisAlternative, ...]
    resolution_status: str
    selected_alternative_id: Optional[str]
    blocking_reason_code: Optional[str]
    evidence: IntersectionEvidence


@dataclass(frozen=True)
class SymbolAlternative:
    component_type: str
    rotate: int
    mirror: bool
    score: float

    @property
    def id(self) -> str:
        return f"{self.component_type}:{self.rotate}:{int(self.mirror)}"


@dataclass(frozen=True)
class SymbolCandidate:
    id: str
    crop: Rect
    confidence: float
    alternatives: Tuple[SymbolAlternative, ...]
    resolution_status: str
    selected_alternative_id: Optional[str]
    blocking_reason_code: Optional[str]


@dataclass(frozen=True)
class PinAttachmentAlternative:
    segment_id: str
    distance_px: float
    distance_score: float
    direction_score: float
    interior_penalty: float
    competition_penalty: float
    score: float


@dataclass(frozen=True)
class PinAttachmentCandidate:
    pin_id: str
    status: str
    selected_segment_id: Optional[str]
    blocking_reason_code: Optional[str]
    alternatives: Tuple[PinAttachmentAlternative, ...]


@dataclass(frozen=True)
class SolverResult:
    status: str
    candidate_ir: Dict[str, Any]
    reason_codes: List[str]
    review_queue: List[Dict[str, str]]


@dataclass(frozen=True)
class PerceptionJobResult:
    status: str
    output_dir: Path
    reason_codes: List[str]
