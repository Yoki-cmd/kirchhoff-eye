# -*- coding: utf-8 -*-
"""Reproducible human-approved component label coordinates."""
import json
from pathlib import Path

import pytest

import ir2tikz
from kirchhoff_eye.cli import main


ROOT = Path(__file__).resolve().parents[1]
GOLDEN_A = ROOT / "tests" / "golden" / "A" / "ir.json"


def run_apply(tmp_path, positions):
    source = tmp_path / "input.json"
    feedback = tmp_path / "positions.json"
    output = tmp_path / "output.json"
    source.write_bytes(GOLDEN_A.read_bytes())
    feedback.write_text(json.dumps(positions), encoding="utf-8")
    rc = main([
        "labels", "apply", str(source), str(feedback), "-o", str(output)
    ])
    return rc, source, feedback, output


def test_labels_apply_sets_absolute_coordinates_and_preserves_other_fields(tmp_path):
    rc, source, _feedback, output = run_apply(tmp_path, {"R1": [3.25, 3.75], "C1": None})

    assert rc == 0
    original = json.loads(source.read_text(encoding="utf-8"))
    labelled = json.loads(output.read_text(encoding="utf-8"))
    by_id = {component["id"]: component for component in labelled["components"]}

    assert by_id["R1"]["label_at"] == [3.25, 3.75]
    assert "label_at" not in by_id["C1"]
    assert by_id["R1"]["label_side"] == "right"
    assert by_id["R1"].get("label_gap") == original["components"][1].get("label_gap")


def test_labels_apply_is_deterministic_and_idempotent(tmp_path):
    rc, _source, feedback, first = run_apply(tmp_path, {"R1": [3.25, 3.75]})
    second = tmp_path / "second.json"

    assert rc == 0
    rc2 = main(["labels", "apply", str(first), str(feedback), "-o", str(second)])

    assert rc2 == 0
    assert first.read_bytes() == second.read_bytes()


def test_labels_apply_null_preserves_an_existing_manual_position(tmp_path):
    source = tmp_path / "input.json"
    feedback = tmp_path / "positions.json"
    output = tmp_path / "output.json"
    ir = json.loads(GOLDEN_A.read_text(encoding="utf-8"))
    ir["components"][1]["label_at"] = [9.0, 8.0]
    source.write_text(json.dumps(ir), encoding="utf-8")
    feedback.write_text(json.dumps({"R1": None}), encoding="utf-8")

    assert main(["labels", "apply", str(source), str(feedback), "-o", str(output)]) == 0
    labelled = json.loads(output.read_text(encoding="utf-8"))

    assert labelled["components"][1]["label_at"] == [9.0, 8.0]


def test_labels_apply_rejects_unknown_component(tmp_path, capsys):
    rc, _source, _feedback, output = run_apply(tmp_path, {"R999": [1, 2]})

    assert rc == 2
    assert not output.exists()
    assert "R999" in capsys.readouterr().err


def test_labels_apply_rejects_invalid_feedback_structure(tmp_path):
    rc, _source, _feedback, output = run_apply(tmp_path, {"R1": [1, 2, 3]})

    assert rc == 2
    assert not output.exists()


@pytest.mark.parametrize(
    "coordinate",
    [[float("nan"), 1], [float("inf"), 1], [float("-inf"), 1]],
)
def test_labels_apply_rejects_non_finite_coordinates(tmp_path, coordinate):
    rc, _source, _feedback, output = run_apply(tmp_path, {"R1": coordinate})

    assert rc == 2
    assert not output.exists()


def test_label_positions_template_validates_against_schema():
    import jsonschema

    schema = json.loads((ROOT / "schemas" / "label-positions.schema.json").read_text(encoding="utf-8"))
    template = json.loads((ROOT / "templates" / "component_label_positions.json").read_text(encoding="utf-8"))

    jsonschema.Draft7Validator(schema).validate(template)


def test_debug_tex_marks_internal_component_anchors(tmp_path, golden_a):
    ir_path = tmp_path / "ir.json"
    tex_path = tmp_path / "out.tex"
    ir_path.write_text(json.dumps(golden_a), encoding="utf-8")

    assert ir2tikz.main([str(ir_path), "-o", str(tex_path)]) == 0
    debug = (tmp_path / "out.debug.tex").read_text(encoding="utf-8")

    assert "component anchor V1" in debug
    assert "component anchor R1" in debug
    assert "\\draw[red" in debug


def test_labels_help_is_available(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["labels", "apply", "--help"])
    assert exc.value.code == 0
    assert "positions_file" in capsys.readouterr().out
