# Kirchhoff-eye

Kirchhoff-eye is an **AI-assisted circuit-redrawing workflow with a deterministic
IR/rendering backend**. It turns a reviewed, topology-aware JSON IR into
validated `circuitikz`, normal/debug renders, and comparison artifacts.

Image understanding is currently a human-in-the-loop step: the public repository
does not ship an autonomous arbitrary-image-to-IR recognizer. Once the IR is
available, validation, serialization, rendering, and layout checks are
repeatable and deterministic.

## Product contract

The project prioritizes:

- electrical topology and pin connectivity;
- component identity, orientation, and mirror state;
- relative placement, grouping, buses, and meaningful wire bends;
- explicit junction/crossing semantics;
- deterministic validation, serialization, rendering, and debug grids;
- human-selected label coordinates through `label_at` when automatic placement
  is not reliable.

This is **semantic redraw**, not facsimile tracing. Uniform scaling, clean spacing,
and adjusted canvas dimensions are acceptable when the source's topology and
recognizable composition are preserved. Exact pixel overlap, symbol dimensions,
and line lengths are not acceptance criteria unless facsimile output is
explicitly requested.

## Requirements

- Python 3.9+
- Pillow
- jsonschema
- TeX Live with `circuitikz`, `pdflatex` or `lualatex`, and `pdftoppm`

Install the project and development tools in a virtual environment:

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
.venv/Scripts/kirchhoff-eye --help
```

On POSIX systems, replace `.venv/Scripts/` with `.venv/bin/`. If a target
virtual environment is already active, the install command is simply:

```bash
python -m pip install -e ".[dev]"
```

## Quick start

The v0.2 package exposes the stable top-level CLI and version metadata:

```bash
kirchhoff-eye --help
kirchhoff-eye --version
kirchhoff-eye doctor
kirchhoff-eye build circuit.ir.json --source source.png --out out/job
kirchhoff-eye labels apply circuit.ir.json positions.json -o circuit.labelled.ir.json
```

`build` validates the IR, generates normal/debug TeX and PNG files, runs the
layout gate, optionally creates a source comparison, and writes
`validation.json`, `layout_report.json`, `review.json`, and `DELIVERY.md` with
absolute artifact paths. Exit codes are `0=ok`, `1=needs_human`,
`2=canonical/generation error`, and `3=environment/IO error`.
Reusing an output directory clears stale generated artifacts before the new run,
so a failed rebuild cannot leave an old comparison or delivery report behind.

The existing deterministic tools remain available as backwards-compatible
scripts while their subcommands move under the package CLI:

```bash
python scripts/validate_ir.py circuit.ir.json --phase full --json
python scripts/ir2tikz.py circuit.ir.json -o circuit.tex
python scripts/render.py circuit.tex -o circuit.png
python scripts/ir_fix_and_render.py circuit.ir.json --layout-check --json
python scripts/score_ir.py truth.ir.json candidate.ir.json --json
```

`score_ir.py` uses declared/geometric topology and orientation hard gates plus a
translation/scale-invariant semantic composition score. Relative placement, region
grouping, meaningful bends, annotation semantics, and component text affect the score. Absolute coordinates,
canvas proportions, pixel overlap, and human-approved `label_at` coordinates are
diagnostics only. See `references/semantic-redraw-scoring.md`.

Serialization automatically creates `circuit.debug.tex`; rendering the normal
TeX automatically creates `circuit.debug.png`. The debug image contains a 0.5
grid, integer coordinates, a small red cross at every internal component anchor,
and red component IDs. The cross distinguishes the component anchor from the
visual bounds of the label glyphs.

To place a component label manually, add an absolute grid coordinate:

```json
{
  "id": "Q1",
  "label": "T_1",
  "label_at": [6.25, 5.75]
}
```

`label_at` takes precedence over `label_side` and `label_gap`.

`kirchhoff-eye doctor` checks the running Python, packaged schema/catalog/template
resources, `pdflatex`/`lualatex`, `pdftoppm`, a real `circuitikz` compile probe,
and a writable temporary output directory. Use `kirchhoff-eye doctor --json` for
automation. It exits `0` when the build environment is ready and `3` when a
required environment capability is missing.

For reproducible batch placement, copy
`templates/component_label_positions.json`, set each component ID to an absolute
`[x, y]` coordinate, and run `labels apply`. A `null` value leaves the current
automatic or manual placement unchanged. Unknown component IDs and malformed
coordinates are rejected without writing an output file. Applying the same file
repeatedly is deterministic and idempotent.
Coordinates must be finite JSON numbers; `NaN` and infinity are rejected.

## Tests

```bash
python -m pytest tests -q
```

GitHub Actions runs the complete suite on Python 3.9, 3.11, and 3.12, plus a
separate TeX integration workflow for golden compilation, normal/debug PNG
rendering, exact `label_at` serialization, and the production build smoke test:

```text
.github/workflows/python.yml
.github/workflows/tex.yml
```

The public synthetic fixture set contains 20 reviewed IR/image pairs generated
only from repository-owned IR:

```bash
python scripts/generate_synthetic_fixture.py --out tests/fixtures --dpi 72
python -m pytest tests/test_synthetic_e2e.py -q
```

It covers passive/source circuits, diodes and polarized capacitors, BJT/MOS,
op-amps, transformer/SPDT multi-terminal parts, buses, connected junctions,
unconnected crossings, current arrows, voltage polarity, and controlled image
variants such as scaling, JPEG compression, blur, tint, and small rotation.

Future independent image perception is deliberately bounded and is not shipped
by v0.2. Its narrow input scope, evidence pipeline, multimodal-model policy,
`needs_human` rules, and evaluation requirements are defined in
`references/perception-roadmap.md`.

## Repository contents

- `scripts/` — validator, serializer, renderer, comparison, scoring, and layout tools.
- `schemas/` — canonical IR JSON schema.
- `catalog/` — component catalog.
- `templates/` — anchors and delivery templates.
- `references/` — IR, rendering, scoring, and future perception conventions.
- `tests/` — unit, rendering, golden-output, and public synthetic end-to-end tests.

Real user images, generated outputs, local benchmark data, and temporary review
artifacts are intentionally excluded from the public repository.

## License

MIT. See `LICENSE`.
