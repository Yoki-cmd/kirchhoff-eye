# Perception evidence sidecar contract

`perception-evidence.json` records what a bounded image frontend observed, which finite
hypotheses it considered, and which ambiguities still block a trustworthy IR. It is a
**sidecar**: canonical `kirchhoff-ir/1.0` remains the only structural source of truth and
continues to reject perception-only fields through `additionalProperties: false`.

Machine-readable structure: `schemas/perception-evidence.schema.json`.

## Invariants

1. `source.sha256`, dimensions, and MIME type bind the evidence to the exact source bytes.
2. `candidate_ir_sha256` binds it to the exact canonical candidate IR.
3. `transform.pixel_to_ir` and `transform.ir_to_pixel` preserve the reversible six-value
   affine mapping between source pixels and IR coordinates. Source pixels use the usual
   top-left origin; IR uses bottom-left origin and positive y upward.
4. Every candidate carries a source `crop`, provenance, confidence, a finite non-empty
   alternative list, affected canonical `ir_path` values, and explicit priority.
5. A selected hypothesis must name one declared alternative. This referential rule is
   checked by `kirchhoff_eye.perception.evidence.validate_evidence_document` in addition
   to JSON Schema validation.
6. An unresolved hypothesis must carry a `blocking_reason_code` and exactly one matching
   `review_queue` entry. The queue reason and priority must match the candidate.
7. A selected candidate cannot remain in the review queue. Unknown queue IDs and duplicate
   candidate/queue IDs are invalid.
8. No unresolved topology ambiguity may be silently copied into canonical IR as if solved.

## Candidate kinds

- `symbol` — finite catalog class, orientation, mirror, polarity, or variant choices;
- `wire_segment` — horizontal/vertical conductor evidence, including weak/broken variants;
- `junction_crossing` — connected junction versus unconnected crossing alternatives;
- `pin_attachment` — pin-to-wire/net alternatives;
- `text_ownership` — nearby component/net/annotation ownership alternatives;
- `annotation` — current, voltage, polarity, or similar physical-marker hypotheses.

## Provenance stages

`preprocess`, `symbols`, `wire_graph`, `intersections`, `pin_attach`, `solver`, and `text`.
A detector name is mandatory; optional artifact hashes bind masks, crops, or intermediate
images without storing those pixels in canonical IR.

## Status use

The sidecar does not introduce a competing workflow state machine. Existing Eye job state
remains authoritative:

- any unresolved blocking candidate → `needs_human`;
- zero blocking ambiguity plus valid deterministic artifacts and a source comparison →
  `needs_review` until complete region review and explicit approval;
- `approved` is still produced only by the existing review/approve workflow.

## Minimal example

```json
{
  "version": "kirchhoff-perception-evidence/1.0",
  "source": {
    "sha256": "<64 lowercase hex>",
    "width_px": 1200,
    "height_px": 800,
    "mime_type": "image/png"
  },
  "transform": {
    "pixel_to_ir": [0.01, 0, 0, -0.01, 0, 8],
    "ir_to_pixel": [100, 0, 0, -100, 0, 800]
  },
  "candidate_ir_sha256": "<64 lowercase hex>",
  "candidates": [
    {
      "id": "cand-j1",
      "kind": "junction_crossing",
      "crop": [380, 260, 460, 340],
      "provenance": {
        "stage": "intersections",
        "detector": "orthogonal-branches/1"
      },
      "confidence": 0.62,
      "alternatives": [
        {"id": "connected", "label": "connected junction", "score": 0.62},
        {"id": "crossing", "label": "unconnected crossing", "score": 0.38}
      ],
      "resolution": {
        "status": "unresolved",
        "blocking_reason_code": "AMBIGUOUS_JUNCTION_CROSSING"
      },
      "affected_ir_paths": ["/junctions/0", "/crossings/0"],
      "priority": "blocking"
    }
  ],
  "review_queue": [
    {
      "candidate_id": "cand-j1",
      "priority": "blocking",
      "reason_code": "AMBIGUOUS_JUNCTION_CROSSING"
    }
  ]
}
```
