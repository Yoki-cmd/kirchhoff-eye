# Bounded perception benchmark metrics

## Reporting rule

Synthetic and real/software-exported image results are always reported in separate tables. An empty real-image manifest means **real-image accuracy has not been measured**. Synthetic results must never be quoted as real-image accuracy.

## Current public MVP metrics

| Metric | Meaning | Current source |
|---|---|---|
| component candidate count | finite catalog-bounded symbol proposals, not accepted classes | `perception-evidence.json` |
| intersection candidate count | junction/crossing locations with finite alternatives | evidence sidecar |
| unresolved candidates | candidates deliberately left for review | evidence sidecar |
| blocking items / diagram | review queue size | evidence sidecar |
| refusal correctness | out-of-scope input becomes `needs_human` with the expected reason code | explicit refusal rows |
| runtime P50/P95 | end-to-end `perceive` wall-clock duration | benchmark runner |
| candidate IR emitted | whether automatic evidence passed all gates | job artifacts |
| correction operations/time | human correction count and duration | real-image manifest, when available |
| manual JSON edits | should be zero in companion UI trials | real-image manifest |

## Metrics reserved for labelled real-image data

Component detection/class/orientation precision/recall, pin attachment accuracy, junction/crossing accuracy, and exact pin-net topology require labelled, distributable real/software-exported images. The runner does not synthesize these values when ground truth is absent.

## Failure reporting

Each real-image row may include `failure_notes`. Reports must retain failed and refused examples, not only successful diagrams.
