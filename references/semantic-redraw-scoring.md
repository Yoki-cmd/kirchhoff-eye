# Semantic redraw scoring

Report contract: `kirchhoff-semantic-score/2.0`.

`scripts/score_ir.py` evaluates whether a candidate preserves the circuit's electrical meaning and recognizable composition. It is not a facsimile or pixel-overlap score.

## Hard gates

Any failure sets the final `total` score to `0`:

- `component_set_type` — identical component IDs and types;
- `pin_net_connectivity` — identical declared pin-to-net partitions;
- `geometric_topology` — conductor geometry yields the same pin connectivity and the candidate has no E007/E008/E014 topology errors;
- `candidate_full_validation` — the candidate passes the canonical full validator with no E-level finding;
- `junction_crossing` — junction and connected/unconnected crossing semantics agree after translation/uniform-scale alignment;
- `orientation_mirror` — polarity/direction-sensitive two-terminal parts and multi-terminal rotate/mirror/variant agree; passive symmetric endpoint reversal is ignored.

## Semantic soft score

When all gates pass, `total` equals the weighted semantic score:

| Metric | Meaning | Weight |
|---|---|---:|
| `relative_relations` | left/right, above/below, same-row, same-column component relations | 0.30 |
| `region_grouping` | whether component pairs remain in the same functional region | 0.15 |
| `route_shape` | wire direction sequence and meaningful bend preservation | 0.30 |
| `annotation_ownership` | annotation kind, target/reference, direction/polarity, and label semantics; annotation IDs are ignored | 0.15 |
| `component_text` | component label/value semantics after normalization | 0.10 |

Uniform translation and scale are aligned away. Absolute coordinates, exact line lengths, canvas proportions, pixel overlap, and human-approved `label_at` coordinates never reduce `total`.

## Diagnostic-only fields

The report keeps the legacy `layout` metrics for debugging and marks them `diagnostic_only: true`. `diagnostics.human_label_coordinate_distance` can show how far approved labels moved after alignment, but `diagnostics.absolute_geometry_affects_total` is always `false`.

## Interpretation

- `gates.passed=false`: reject the redraw regardless of soft score.
- `gates.passed=true`, `total<1`: topology is valid, but composition, routing, grouping, or annotation ownership differs.
- `total=1`: all hard semantics and the measured semantic composition agree; it does not claim pixel identity.