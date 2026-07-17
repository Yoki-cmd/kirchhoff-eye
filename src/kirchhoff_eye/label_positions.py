"""Apply reproducible human-approved component label coordinates."""

import json
import math
from pathlib import Path
from typing import Any, Dict

import jsonschema


PACKAGE_ROOT = Path(__file__).resolve().parent
SOURCE_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = SOURCE_ROOT if (SOURCE_ROOT / "schemas").exists() else PACKAGE_ROOT
SCHEMA_PATH = PROJECT_ROOT / "schemas" / "label-positions.schema.json"

EXIT_OK = 0
EXIT_ERROR = 2
EXIT_ENV = 3


class LabelPositionsError(ValueError):
    """The feedback is structurally valid JSON but cannot be applied."""


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _validate_positions(positions: Any) -> None:
    schema = _load_json(SCHEMA_PATH)
    try:
        jsonschema.Draft7Validator(schema).validate(positions)
    except jsonschema.ValidationError as exc:
        location = ".".join(str(part) for part in exc.absolute_path) or "$"
        raise LabelPositionsError(f"invalid label positions at {location}: {exc.message}") from exc
    for component_id, coordinate in positions.items():
        if coordinate is not None and not all(math.isfinite(value) for value in coordinate):
            raise LabelPositionsError(
                f"invalid label positions at {component_id}: coordinates must be finite"
            )


def apply_positions(ir: Dict[str, Any], positions: Dict[str, Any]) -> Dict[str, Any]:
    """Apply non-null positions in place and return the IR for convenient chaining."""
    _validate_positions(positions)
    components = {component["id"]: component for component in ir.get("components", [])}
    unknown = sorted(set(positions) - set(components))
    if unknown:
        raise LabelPositionsError(
            "unknown component ID(s): " + ", ".join(unknown)
        )
    for component_id, coordinate in positions.items():
        if coordinate is not None:
            components[component_id]["label_at"] = coordinate
    return ir


def apply_file(ir_file: str, positions_file: str, output_file: str) -> int:
    """Apply a positions JSON file to an IR and write deterministic UTF-8 JSON."""
    source = Path(ir_file)
    feedback = Path(positions_file)
    output = Path(output_file)
    try:
        ir = _load_json(source)
        positions = _load_json(feedback)
        apply_positions(ir, positions)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(ir, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except LabelPositionsError as exc:
        import sys

        sys.stderr.write(f"ERROR: {exc}\n")
        return EXIT_ERROR
    except (OSError, json.JSONDecodeError, jsonschema.SchemaError) as exc:
        import sys

        sys.stderr.write(f"ERROR: unable to apply label positions: {exc}\n")
        return EXIT_ENV
    return EXIT_OK
