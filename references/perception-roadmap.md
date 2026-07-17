# Bounded perception roadmap

## Status

Kirchhoff-eye does not ship an autonomous arbitrary-image-to-IR recognizer. The
public v0.2 product is an AI-assisted, human-reviewed workflow backed by a
deterministic IR validator, serializer, renderer, layout checker, and scoring
system.

This roadmap defines a future perception frontend. It is a product boundary and
acceptance contract, not a claim that the modules below already exist.

## Narrow v1 input scope

The first independently measured frontend should accept only inputs satisfying
all of these conditions:

```text
printed or software-exported circuit image
single circuit subfigure
short edge >= 600 px
<= 15 components
<= 2 complex multi-terminal components
orthogonal or near-orthogonal wires
symbols drawn from the public component catalog
no handwritten obstruction over symbols, pins, or junctions
```

Images outside this scope must be rejected or returned as `needs_human`; they
must not be forced through by guessing a complete topology.

## Required architecture

The frontend should preserve the canonical JSON IR as the only structural source
of truth and use an evidence-producing pipeline:

```text
preprocess
→ symbol candidates and masks
→ wire graph
→ junction/crossing candidates
→ pin attachment evidence
→ global consistency solver
→ candidate IR
→ review queue
```

Each stage must retain observed evidence, provenance, confidence, and unresolved
alternatives. Projected expectations from an existing IR are weak supervision,
not pixel detections.

### Preprocess

Normalize grayscale/contrast, estimate line width, deskew small rotations, and
retain the transform back to source pixels. Do not erase ambiguous dots or wire
crossings during cleanup.

### Symbol candidates

Detect candidate bounding boxes, finite catalog classes, orientation, mirror
state, and pin-facing directions. Unknown or low-confidence symbols remain
explicit unknowns rather than being replaced by a visually similar component.

### Wire graph

Extract horizontal and vertical conductor evidence while masking symbol bodies.
Keep broken, weak, and competing segments in the evidence graph until global
resolution; a nearest-line heuristic is not sufficient for pin attachment.

### Junction and crossing candidates

Combine center-pixel/dot evidence, branch directions, local line continuity, and
incident-wire support. Connected junctions and unconnected crossings are separate
semantic hypotheses.

### Pin attachment evidence

Score distance, expected pin direction, component-interior traversal, occlusion,
line width, and competing candidates. Use explicit states such as `attached`,
`weak`, `ambiguous`, and `unattached`.

### Global consistency solver

Resolve candidates jointly against electrical and geometric invariants:

- every declared component pin has a compatible attachment or an unresolved item;
- nets, explicit topology references, wire vertices, junctions, and crossings agree;
- conductor geometry remains orthogonal unless the schema explicitly permits an
  exception;
- symbol class, orientation, polarity, and pin identities remain mutually
  consistent;
- the solver never changes a blocking ambiguity into a confident guess solely to
  produce valid JSON.

### Candidate IR and review queue

The output is a canonical candidate IR plus a prioritized review queue. Every
blocking item identifies the source crop, alternatives, evidence, confidence,
and the IR path that a reviewer would change.

## Multimodal model policy

Use multimodal models only for local finite-choice adjudication after deterministic
candidate generation, for example:

```text
junction vs crossing
pin A vs pin B
arrow direction among explicit alternatives
text ownership among nearby components/nets
component class among a finite catalog shortlist
```

Do not ask one whole-image call to freely invent final topology JSON. Whole-image
context may rank already-generated alternatives, but it must not bypass measured
wire, pin, junction, or component evidence.

## Status policy

Return `needs_human` when any of the following remains unresolved:

- component class, orientation, polarity, or mirror state;
- pin-to-net attachment;
- junction versus crossing semantics;
- text or physical-annotation ownership;
- a contradiction between explicit topology and conductor geometry.

Return `ok` only with zero blocking topology ambiguity and after the candidate IR
passes canonical validation, deterministic serialization, rendering, and layout
checks.

## Evaluation policy

Public synthetic fixtures measure reproducibility and controlled degradation;
they do not by themselves establish real-image accuracy. A future perception
release must report synthetic and real-image results separately and include at
least:

- component detection/class/orientation accuracy;
- pin attachment accuracy;
- junction/crossing accuracy;
- exact pin-net topology accuracy;
- blocking review items per diagram;
- human correction time to validated IR.

The default package must not add OpenCV, SciPy, NetworkX, model weights, or other
heavy dependencies until public perception source and tests require them.
