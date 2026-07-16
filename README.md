# Kirchhoff-eye

Kirchhoff-eye reconstructs printed or software-exported circuit diagrams into a
topology-aware JSON IR and deterministic `circuitikz` output.

The project prioritizes:

- electrical topology and pin connectivity;
- relative component placement, orientation, buses, and meaningful bends;
- explicit junction/crossing semantics;
- deterministic validation, serialization, rendering, and debug grids;
- human-selected label coordinates through `label_at` when automatic label
  placement is not reliable.

Exact pixel dimensions are not a reconstruction requirement. The renderer may
choose clean dimensions and spacing while preserving the source composition.

## Requirements

- Python 3.9+
- Pillow
- jsonschema
- TeX Live with `circuitikz`, `pdflatex`/`lualatex`, and `pdftoppm`

Optional perception modules also use OpenCV, NumPy, SciPy, and NetworkX.

## Quick start

```bash
python scripts/validate_ir.py circuit.ir.json --phase full --json
python scripts/ir2tikz.py circuit.ir.json -o circuit.tex
python scripts/render.py circuit.tex -o circuit.png
```

Serialization automatically creates `circuit.debug.tex`; rendering the normal
TeX automatically creates `circuit.debug.png`. The debug image contains a 0.5
grid, integer coordinates, and red internal component IDs.

To place a component label manually, add an absolute grid coordinate:

```json
{
  "id": "Q1",
  "label": "T_1",
  "label_at": [6.25, 5.75]
}
```

`label_at` takes precedence over `label_side` and `label_gap`.

## Tests

```bash
python -m pytest tests -q
```

## Repository contents

- `scripts/` — validator, serializer, renderer, comparison tools, and optional
  perception modules.
- `schemas/` — canonical IR JSON schema.
- `catalog/` — component catalog.
- `templates/` — anchors and delivery templates.
- `references/` — IR and rendering conventions.
- `tests/` — unit, rendering, and synthetic perception tests.

Real user images, generated outputs, local benchmark data, and temporary review
artifacts are intentionally excluded from the public repository.

## License

MIT. See `LICENSE`.