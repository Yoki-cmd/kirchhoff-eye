# Electrical plausibility audit

Kirchhoff-eye evaluates every source-backed delivery on two independent axes:

1. **Source fidelity** — whether canonical IR and the redraw faithfully reproduce the source diagram.
2. **Electrical plausibility** — whether the source-described connectivity is self-consistent and engineering-plausible within the explicitly analyzed scope.

A faithful redraw may preserve an electrically suspicious source. The audit never silently “corrects” topology and never treats unfamiliarity or absence of a recognized motif as an error.

## Deterministic sidecar

After full IR validation, `kirchhoff-eye audit` and every build/repair produce `electrical-audit.json` (`kirchhoff-electrical-audit/1.0`). It is bound to the canonical IR hash and contains:

- conservative blocker/warning/info findings;
- positive-only recognized motifs;
- coverage counts and limitations;
- a verdict of `pass`, `warn`, or `block`.

Blockers are intentionally narrow: collapsed power rails, a known nonzero ideal voltage source short, and contradictory known independent ideal-voltage constraints. Warnings cover suspicious device semantics or heuristics with plausible exceptions, such as parallel ideal sources, bypassed components, floating control pins, output contention, and positive feedback without a negative path.

The report does **not** prove that the circuit works. Nonlinear operating points, frequency response, transient behavior, controlled-source control relationships, unknown switch state, device models, tolerances, and external context are not inferred.

## AI electrical assessment

For a source-backed review, the Agent must add an `electrical_assessment` object to the normal round-review JSON. It binds the current canonical IR hash and deterministic audit hash, then records claims with exact IR paths, assumptions, confidence, rationale, and disposition.

Every deterministic warning/blocker must have exactly one disposition claim. A `repair_ir` claim must link a normal source-review difference with a matching IR path. Thus all topology changes continue through the existing reviewed repair state machine.

Allowed assessment verdicts:

- `pass` — no unresolved concern and deterministic audit has no warnings/blockers;
- `warn` — findings were explicitly accepted or confirmed as source-intended;
- `needs_context` — missing external conditions block approval;
- `requires_repair` — source evidence suggests the canonical IR must be repaired.

A deterministic blocker always keeps the job in `needs_human`; AI confirmation cannot clear it in this release.

## Approval evidence

Approval rechecks and binds:

- canonical IR hash;
- source image hash;
- comparison image hash;
- deterministic electrical audit hash;
- AI electrical assessment hash.

Repair produces a new audit and requires a new assessment. Each round snapshot preserves its IR, render, comparison, audit, and reviewed assessment in `review.json`.

## CLI

```bash
kirchhoff-eye audit circuit.ir.json --out electrical-audit.json
kirchhoff-eye audit circuit.ir.json --json
```

A successful audit command exits 0 even when the report verdict is `warn` or `block`; findings are workflow evidence, not command-execution failures. Invalid canonical IR exits 2, while IO/environment failures exit 3. Output files are published atomically.
