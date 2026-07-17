# -*- coding: utf-8 -*-
"""score_ir 测试：自比满分、对齐恢复、各指标对扰动的响应方向。"""
import copy

import pytest

import irlib
import score_ir


def make_scorer(truth, cand):
    return score_ir.Scorer(truth, cand, irlib.load_anchors(), irlib.load_config())


def test_identity_full_score(golden_b):
    rep = make_scorer(golden_b, copy.deepcopy(golden_b)).report()
    assert rep["score_version"] == "kirchhoff-semantic-score/2.0"
    assert rep["total"] == 1.0
    assert rep["gates"]["passed"] is True
    assert rep["semantic"]["score"] == 1.0
    assert rep["netlist"]["f1"] == 1.0
    assert rep["netlist"]["netlist_equivalent"] is True
    assert rep["layout"]["rmse_raw"] == 0.0
    assert rep["layout"]["diagnostic_only"] is True


def test_config_declares_semantic_score_contract():
    config = irlib.load_config()
    semantic = config["score_weights"]["semantic"]

    assert set(semantic) == {
        "relative_relations",
        "region_grouping",
        "route_shape",
        "annotation_ownership",
        "component_text",
    }
    assert abs(sum(semantic.values()) - 1.0) < 1e-9
    assert config["score_gates"] == [
        "component_set_type",
        "pin_net_connectivity",
        "geometric_topology",
        "candidate_full_validation",
        "junction_crossing",
        "orientation_mirror",
    ]
    assert "human_approved_label_coordinates" in config["score_diagnostics"]


def _transform(ir, s, tx, ty):
    def tp(p):
        return [p[0] * s + tx, p[1] * s + ty]
    out = copy.deepcopy(ir)
    for c in out["components"]:
        for f in ("from", "to", "at"):
            if f in c:
                c[f] = tp(c[f])
        for p in c.get("pins", []):
            if "at" in p:
                p["at"] = tp(p["at"])
    for w in out["wires"]:
        for pt in w["points"]:
            if "xy" in pt:
                pt["xy"] = tp(pt["xy"])
    for sec in ("junctions", "crossings", "terminals", "texts"):
        for item in out.get(sec, []):
            item["at"] = tp(item["at"])
    out["meta"]["canvas"] = {"w": ir["meta"]["canvas"]["w"] * s + tx,
                             "h": ir["meta"]["canvas"]["h"] * s + ty}
    return out


def test_alignment_recovers_scale_shift(golden_a):
    cand = _transform(golden_a, 2.0, 3.0, 1.0)
    sc = make_scorer(golden_a, cand)
    assert abs(sc.s - 2.0) < 0.05
    rep = sc.report()
    assert rep["netlist"]["f1"] == 1.0
    assert rep["netlist"]["score"] == 1.0
    assert rep["semantic"]["score"] == 1.0
    assert rep["total"] == 1.0


def test_topology_change_is_a_blocking_gate(golden_a):
    cand = copy.deepcopy(golden_a)
    cand["components"][3]["pins"][0]["net"] = "N_X"

    rep = make_scorer(golden_a, cand).report()

    assert rep["gates"]["passed"] is False
    assert "pin_net_connectivity" in rep["gates"]["failed"]
    assert rep["total"] == 0.0


def test_extra_shorting_wire_is_a_blocking_gate(golden_a):
    cand = copy.deepcopy(golden_a)
    cand["wires"].append({
        "id": "W99",
        "points": [{"pin": "V1.1"}, {"pin": "V1.2"}],
    })

    rep = make_scorer(golden_a, cand).report()

    assert rep["gates"]["passed"] is False
    assert "geometric_topology" in rep["gates"]["failed"]
    assert rep["total"] == 0.0


@pytest.mark.parametrize(
    "mutate,code",
    [
        (lambda cand: cand["wires"].append({
            "id": "W99", "points": [{"xy": [0, 1]}, {"xy": [1, 2]}],
        }), "E004"),
        (lambda cand: cand["wires"].append({
            "id": "W99", "points": [{"xy": [3, 1]}, {"xy": [3, 3]}],
        }), "E008"),
        (lambda cand: cand["wires"].append({
            "id": "W99", "points": [{"xy": [1.5, 0]}, {"xy": [2.5, 0]}],
        }), "E014"),
        (lambda cand: cand["wires"].append(copy.deepcopy(cand["wires"][0])), "E002"),
    ],
)
def test_full_candidate_validation_errors_are_blocking_gates(golden_a, mutate, code):
    cand = copy.deepcopy(golden_a)
    mutate(cand)

    rep = make_scorer(golden_a, cand).report()

    assert rep["gates"]["candidate_full_validation"] is False
    assert code in rep["diagnostics"]["candidate_validation_errors"]
    assert rep["total"] == 0.0


def test_human_approved_label_coordinate_is_diagnostic_only(golden_a):
    truth = copy.deepcopy(golden_a)
    cand = copy.deepcopy(golden_a)
    truth["components"][1]["label_at"] = [2.8, 3.3]
    cand["components"][1]["label_at"] = [6.5, 4.75]

    rep = make_scorer(truth, cand).report()

    assert rep["gates"]["passed"] is True
    assert rep["semantic"]["score"] == 1.0
    assert rep["total"] == 1.0
    assert rep["diagnostics"]["human_label_coordinate_distance"] > 0.0


def test_deleting_meaningful_bend_lowers_route_shape(golden_a):
    truth = copy.deepcopy(golden_a)
    truth["wires"][2]["points"] = [
        {"pin": "R1.2"}, {"xy": [4, 2]}, {"xy": [4, 3]},
        {"xy": [5.5, 3]}, {"xy": [5.5, 2]}]
    cand = copy.deepcopy(truth)
    cand["wires"][2]["points"] = [
        {"pin": "R1.2"}, {"xy": [4, 2]}, {"xy": [5.5, 2]}]

    rep = make_scorer(truth, cand).report()

    assert rep["gates"]["passed"] is True
    assert rep["semantic"]["route_shape"] < 1.0
    assert rep["semantic"]["score"] < 1.0


def test_swapping_annotation_ownership_lowers_semantic_annotation_score(golden_a):
    truth = copy.deepcopy(golden_a)
    cand = copy.deepcopy(golden_a)
    annotation = {
        "id": "A1",
        "kind": "current_direction",
        "target": {"wire": "W3"},
        "direction": "right",
        "marker_at": [4.8, 2.3],
        "label": "i_o",
        "label_at": [4.8, 2.7],
    }
    truth["annotations"] = [annotation]
    cand["annotations"] = [copy.deepcopy(annotation)]
    cand["annotations"][0]["target"] = {"wire": "W2"}

    rep = make_scorer(truth, cand).report()

    assert rep["gates"]["passed"] is True
    assert rep["semantic"]["annotation_ownership"] < 1.0
    assert rep["semantic"]["score"] < 1.0


def test_annotation_direction_label_and_polarity_are_semantic(golden_a):
    truth = copy.deepcopy(golden_a)
    truth["annotations"] = [
        {
            "id": "A1", "kind": "current_direction", "target": {"wire": "W3"},
            "direction": "right", "marker_at": [4.8, 2.3],
            "label": "i_o", "label_at": [4.8, 2.7],
        },
        {
            "id": "A2", "kind": "node_polarity", "target": {"net": "N_MID"},
            "polarity": "positive", "marker_at": [5.0, 2.4], "label": "v_o",
        },
    ]
    cand = copy.deepcopy(truth)
    cand["annotations"][0]["direction"] = "left"
    cand["annotations"][0]["label"] = "wrong"
    cand["annotations"][1]["polarity"] = "negative"

    rep = make_scorer(truth, cand).report()

    assert rep["semantic"]["annotation_ownership"] < 1.0
    assert rep["total"] < 1.0


def test_annotation_id_renumbering_is_semantically_equivalent(golden_a):
    truth = copy.deepcopy(golden_a)
    truth["annotations"] = [{
        "id": "A1", "kind": "current_direction", "target": {"wire": "W3"},
        "direction": "right", "marker_at": [4.8, 2.3],
        "label": "i_o", "label_at": [4.8, 2.7],
    }]
    cand = copy.deepcopy(truth)
    cand["annotations"][0]["id"] = "A99"

    rep = make_scorer(truth, cand).report()

    assert rep["semantic"]["annotation_ownership"] == 1.0
    assert rep["total"] == 1.0


def test_annotation_wire_owner_survives_uniform_wire_id_rename(golden_a):
    truth = copy.deepcopy(golden_a)
    truth["annotations"] = [{
        "id": "A1", "kind": "current_direction", "target": {"wire": "W3"},
        "direction": "right", "marker_at": [4.8, 2.3], "label": "i_o",
    }]
    cand = copy.deepcopy(truth)
    cand["wires"][2]["id"] = "W99"
    cand["annotations"][0]["target"] = {"wire": "W99"}

    rep = make_scorer(truth, cand).report()

    assert rep["semantic"]["annotation_ownership"] == 1.0
    assert rep["total"] == 1.0


def test_annotation_net_owner_survives_uniform_net_rename(golden_a):
    truth = copy.deepcopy(golden_a)
    truth["annotations"] = [{
        "id": "A1", "kind": "node_polarity", "target": {"net": "N_MID"},
        "polarity": "positive", "marker_at": [4.8, 2.3],
    }]
    cand = copy.deepcopy(truth)
    for component in cand["components"]:
        for pin in component.get("pins", []):
            if pin["net"] == "N_MID":
                pin["net"] = "N_RENAMED"
    next(net for net in cand["nets"] if net["name"] == "N_MID")["name"] = "N_RENAMED"
    cand["annotations"][0]["target"] = {"net": "N_RENAMED"}

    rep = make_scorer(truth, cand).report()

    assert rep["semantic"]["annotation_ownership"] == 1.0
    assert rep["total"] == 1.0


def test_extra_isolated_wire_reduces_route_shape(golden_a):
    cand = copy.deepcopy(golden_a)
    cand["wires"].append({
        "id": "W99", "points": [{"xy": [6, 4]}, {"xy": [6.5, 4]}],
    })

    rep = make_scorer(golden_a, cand).report()

    assert rep["gates"]["candidate_full_validation"] is True
    assert rep["semantic"]["route_shape"] < 1.0
    assert rep["total"] < 1.0


def test_collinear_waypoint_is_route_shape_equivalent(golden_a):
    cand = copy.deepcopy(golden_a)
    cand["wires"][0]["points"].insert(1, {"xy": [1, 4]})

    rep = make_scorer(golden_a, cand).report()

    assert rep["gates"]["passed"] is True
    assert rep["semantic"]["route_shape"] == 1.0
    assert rep["total"] == 1.0


def test_component_value_and_label_errors_reduce_semantic_score(golden_a):
    cand = copy.deepcopy(golden_a)
    cand["components"][1]["value"] = "WRONG"
    cand["components"][2].pop("label")

    rep = make_scorer(golden_a, cand).report()

    assert rep["semantic"]["component_text"] < 1.0
    assert rep["total"] < 1.0


def test_type_swap_hits_f1_and_confusion(golden_a):
    cand = copy.deepcopy(golden_a)
    cand["components"][2]["type"] = "capacitor"  # R2 -> C
    rep = make_scorer(golden_a, cand).report()
    assert rep["netlist"]["f1"] < 1.0
    assert rep["netlist"]["type_confusion"].get("resistor->capacitor", 0) >= 1


def test_missing_component_hits_recall(golden_a):
    cand = copy.deepcopy(golden_a)
    cand["components"] = [c for c in cand["components"] if c["id"] != "C1"]
    cand["regions"][2]["component_ids"] = ["GND1"]
    rep = make_scorer(golden_a, cand).report()
    assert rep["netlist"]["recall"] < 1.0
    assert rep["netlist"]["netlist_equivalent"] is False


def test_net_break_hits_connectivity(golden_a):
    cand = copy.deepcopy(golden_a)
    cand["components"][3]["pins"][0]["net"] = "N_X"  # C1.1 脱离 N_MID
    rep = make_scorer(golden_a, cand).report()
    assert rep["netlist"]["connectivity_rand"] < 1.0
    assert rep["netlist"]["netlist_equivalent"] is False


def test_uniform_net_rename_preserves_pin_connectivity_gate(golden_a):
    cand = copy.deepcopy(golden_a)
    for component in cand["components"]:
        for pin in component.get("pins", []):
            if pin["net"] == "N_MID":
                pin["net"] = "N_RENAMED"
    for net in cand["nets"]:
        if net["name"] == "N_MID":
            net["name"] = "N_RENAMED"

    rep = make_scorer(golden_a, cand).report()

    assert rep["gates"]["pin_net_connectivity"] is True
    assert rep["gates"]["passed"] is True
    assert rep["total"] == 1.0


def test_junction_gate_tracks_incident_semantics_not_absolute_coordinate(golden_a):
    cand = copy.deepcopy(golden_a)
    cand["components"][1]["to"] = [2, 2.5]
    cand["components"][2]["from"] = [2, 2.5]
    cand["components"][2]["to"] = [2, 0.5]
    cand["components"][3]["from"] = [4, 2.5]
    cand["components"][3]["to"] = [4, 0.5]
    cand["components"][4]["at"] = [4, 0.5]
    cand["wires"][1]["points"] = [
        {"pin": "V1.1"}, {"xy": [2, 0]}, {"xy": [2, 0.5]}, {"pin": "C1.2"},
    ]
    cand["wires"][2]["points"] = [
        {"pin": "R1.2"}, {"xy": [4, 2.5]}, {"xy": [5.5, 2.5]},
    ]
    cand["junctions"][0]["at"] = [2, 2.5]
    cand["terminals"][0]["at"] = [5.5, 2.5]

    rep = make_scorer(golden_a, cand).report()

    assert rep["gates"]["junction_crossing"] is True
    assert rep["gates"]["passed"] is True


def test_wire_id_renumbering_preserves_junction_crossing_gate(golden_a):
    cand = copy.deepcopy(golden_a)
    for index, wire in enumerate(cand["wires"], 1):
        wire["id"] = "W%d" % (index + 50)

    rep = make_scorer(golden_a, cand).report()

    assert rep["gates"]["junction_crossing"] is True
    assert rep["gates"]["passed"] is True


def test_wire_detour_hits_shape(golden_a):
    cand = copy.deepcopy(golden_a)
    cand["wires"][2]["points"] = [
        {"pin": "R1.2"}, {"xy": [4, 2]}, {"xy": [4, 3]},
        {"xy": [5.5, 3]}, {"xy": [5.5, 2]}]
    rep = make_scorer(golden_a, cand).report()
    assert rep["layout"]["wire_shape"] < 1.0


def test_label_side_flip(golden_a):
    cand = copy.deepcopy(golden_a)
    cand["components"][1]["label_side"] = "left"
    rep = make_scorer(golden_a, cand).report()
    assert rep["layout"]["label_side"] < 1.0


def test_polarity_flip_hits_orientation(golden_a):
    cand = copy.deepcopy(golden_a)
    v1 = cand["components"][0]
    v1["from"], v1["to"] = v1["to"], v1["from"]
    rep = make_scorer(golden_a, cand).report()
    assert rep["layout"]["orientation"] < 1.0
    assert rep["gates"]["orientation_mirror"] is False


def test_passive_endpoint_reversal_preserves_orientation_gate(golden_a):
    cand = copy.deepcopy(golden_a)
    r1 = cand["components"][1]
    r1["from"], r1["to"] = r1["to"], r1["from"]

    assert make_scorer(golden_a, cand).orientation_gate() is True


def test_pose_change_hits_orientation(golden_b):
    cand = copy.deepcopy(golden_b)
    cand["components"][3]["mirror"] = True
    for p in cand["components"][3]["pins"]:
        p.pop("at", None)
    rep = make_scorer(golden_b, cand).report()
    assert rep["layout"]["orientation"] < 1.0


def test_value_mismatch(golden_a):
    cand = copy.deepcopy(golden_a)
    cand["components"][1]["value"] = "4.7\\mathrm{k}\\Omega"
    rep = make_scorer(golden_a, cand).report()
    assert rep["netlist"]["values"] < 1.0


def test_value_normalization(golden_a):
    cand = copy.deepcopy(golden_a)
    cand["components"][1]["value"] = "1k\\Omega"  # 去掉 \mathrm{} 应视为相等
    rep = make_scorer(golden_a, cand).report()
    assert rep["netlist"]["values"] == 1.0


def test_cli_and_rounds(golden_b, tmp_path, capsys):
    import json
    t = tmp_path / "t.json"
    c = tmp_path / "c.json"
    t.write_text(json.dumps(golden_b), encoding="utf-8")
    c.write_text(json.dumps(golden_b), encoding="utf-8")
    rc = score_ir.main([str(t), str(c), "--json", "--rounds", "2"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["rounds"] == 2 and out["total"] == 1.0


def test_cli_bad_candidate_schema(golden_b, tmp_path):
    import json
    t = tmp_path / "t.json"
    c = tmp_path / "c.json"
    t.write_text(json.dumps(golden_b), encoding="utf-8")
    bad = copy.deepcopy(golden_b)
    del bad["meta"]
    c.write_text(json.dumps(bad), encoding="utf-8")
    assert score_ir.main([str(t), str(c)]) == 2
