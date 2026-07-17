# -*- coding: utf-8 -*-
"""First-class physical annotations: structure, semantics, and rendering."""
import json

import pytest

import ir2tikz
from conftest import codes


def current_annotation():
    return {
        "id": "A1",
        "kind": "current_direction",
        "target": {"wire": "W3"},
        "direction": "down",
        "marker_at": [0.6, 2.0],
        "label": "i_s",
        "label_at": [1.0, 2.0],
    }


def voltage_annotation():
    return {
        "id": "A2",
        "kind": "voltage_measurement",
        "label": "u_o",
        "positive_ref": {"net": "N_MID", "marker_at": [5.8, 2.4]},
        "negative_ref": {"net": "GND", "marker_at": [5.8, 0.4]},
        "label_at": [6.2, 1.4],
    }


def test_schema_accepts_first_class_annotations(golden_a, vrun):
    golden_a["annotations"] = [current_annotation(), voltage_annotation()]

    rc, out = vrun(golden_a)

    assert rc == 0 and out["findings"] == []


def test_annotation_ids_must_be_unique(golden_a, vrun):
    first = current_annotation()
    second = voltage_annotation()
    second["id"] = first["id"]
    golden_a["annotations"] = [first, second]

    rc, out = vrun(golden_a)

    assert rc == 2 and "E015" in codes(out)


@pytest.mark.parametrize(
    "annotation",
    [
        {
            "id": "A1",
            "kind": "current_direction",
            "target": {"component": "R9"},
            "direction": "right",
            "marker_at": [3.0, 2.4],
        },
        {
            "id": "A1",
            "kind": "rail_label",
            "target": {"net": "N_MISSING"},
            "label": "V_X",
            "label_at": [1.0, 1.0],
        },
        {
            "id": "A1",
            "kind": "node_polarity",
            "target": {"node": "N_MISSING"},
            "polarity": "positive",
            "marker_at": [1.0, 1.0],
        },
    ],
)
def test_annotation_targets_must_exist(golden_a, vrun, annotation):
    golden_a["annotations"] = [annotation]

    rc, out = vrun(golden_a)

    assert rc == 2 and "E015" in codes(out)


def test_current_direction_accepts_two_terminal_component_branch(golden_a, vrun):
    annotation = current_annotation()
    annotation["target"] = {"component": "R1"}
    golden_a["annotations"] = [annotation]

    rc, out = vrun(golden_a)

    assert rc == 0 and out["findings"] == []


@pytest.mark.parametrize(
    "kind,target,extra",
    [
        ("component_id", {"wire": "W3"}, {"label_at": [1.0, 1.0]}),
        ("component_value", {"net": "N_MID"}, {"label_at": [1.0, 1.0]}),
        ("port_label", {"component": "R1"}, {"label": "in", "label_at": [1.0, 1.0]}),
        ("rail_label", {"component": "R1"}, {"label": "V_X", "label_at": [1.0, 1.0]}),
        ("node_polarity", {"component": "R1"}, {"polarity": "positive", "marker_at": [1.0, 1.0]}),
    ],
)
def test_annotation_kind_requires_compatible_target_type(golden_a, vrun, kind, target, extra):
    golden_a["annotations"] = [{"id": "A1", "kind": kind, "target": target, **extra}]

    rc, out = vrun(golden_a)

    assert rc == 2 and ("E001" in codes(out) or "E015" in codes(out))


def test_schema_rejects_incompatible_annotation_target_without_semantic_validator(golden_a):
    import jsonschema
    import irlib

    golden_a["annotations"] = [{
        "id": "A1", "kind": "component_id", "target": {"wire": "W3"},
        "label_at": [1.0, 1.0],
    }]

    errors = list(jsonschema.Draft7Validator(irlib.load_schema()).iter_errors(golden_a))

    assert errors


def test_voltage_references_must_differ(golden_a, vrun):
    annotation = voltage_annotation()
    annotation["negative_ref"]["net"] = annotation["positive_ref"]["net"]
    golden_a["annotations"] = [annotation]

    rc, out = vrun(golden_a)

    assert rc == 2 and "E015" in codes(out)


def test_voltage_references_must_be_electrically_distinct(golden_a, vrun):
    golden_a["nodes"] = [{"name": "N_SENSE", "at": [2, 2]}]
    annotation = voltage_annotation()
    annotation["positive_ref"] = {"net": "N_MID", "marker_at": [5.8, 2.4]}
    annotation["negative_ref"] = {"node": "N_SENSE", "marker_at": [5.8, 0.4]}
    golden_a["annotations"] = [annotation]

    rc, out = vrun(golden_a)

    assert rc == 2 and "E015" in codes(out)


def test_component_annotations_replace_native_component_text_rendering(tmp_path, golden_a):
    golden_a["annotations"] = [
        {"id": "A1", "kind": "component_id", "target": {"component": "R1"},
         "label_at": [2.8, 3.5]},
        {"id": "A2", "kind": "component_value", "target": {"component": "R1"},
         "label_at": [3.2, 2.8]},
    ]
    ir_path = tmp_path / "ir.json"
    tex_path = tmp_path / "out.tex"
    ir_path.write_text(json.dumps(golden_a), encoding="utf-8")

    rc = ir2tikz.main([str(ir_path), "-o", str(tex_path)])
    text = tex_path.read_text(encoding="utf-8")

    assert rc == 0
    assert text.count("R_1") == 1
    assert text.count(r"1\mathrm{k}\Omega") == 1


def test_annotations_serialize_at_explicit_coordinates(tmp_path, golden_a):
    golden_a["annotations"] = [
        current_annotation(),
        voltage_annotation(),
        {
            "id": "A3",
            "kind": "node_polarity",
            "target": {"net": "N_MID"},
            "polarity": "positive",
            "marker_at": [5.2, 2.4],
        },
        {
            "id": "A4",
            "kind": "free_text",
            "label": "test",
            "label_at": [6.0, 4.0],
        },
    ]
    ir_path = tmp_path / "ir.json"
    tex_path = tmp_path / "out.tex"
    ir_path.write_text(json.dumps(golden_a), encoding="utf-8")

    rc = ir2tikz.main([str(ir_path), "-o", str(tex_path)])
    text = tex_path.read_text(encoding="utf-8")

    assert rc == 0
    assert "%% ==== annotations ====" in text
    assert "(0.6,2.3) -- (0.6,1.7)" in text
    assert "(1,2) {$i_s$};" in text
    assert "(5.8,2.4) {$+$};" in text
    assert "(5.8,0.4) {$-$};" in text
    assert "(6.2,1.4) {$u_o$};" in text
    assert "(5.2,2.4) {$+$};" in text
    assert "(6,4) {$test$};" in text


def test_legacy_arrows_and_texts_remain_supported(tmp_path, golden_a):
    golden_a["arrows"] = [{"at": [3, 2], "dir": 0, "label": "i_1"}]
    golden_a["annotations"] = []
    ir_path = tmp_path / "ir.json"
    tex_path = tmp_path / "out.tex"
    ir_path.write_text(json.dumps(golden_a), encoding="utf-8")

    rc = ir2tikz.main([str(ir_path), "-o", str(tex_path)])

    assert rc == 0
    assert "%% ==== arrows ====" in tex_path.read_text(encoding="utf-8")
