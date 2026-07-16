# -*- coding: utf-8 -*-
"""score_ir 测试：自比满分、对齐恢复、各指标对扰动的响应方向。"""
import copy

import irlib
import score_ir


def make_scorer(truth, cand):
    return score_ir.Scorer(truth, cand, irlib.load_anchors(), irlib.load_config())


def test_identity_full_score(golden_b):
    rep = make_scorer(golden_b, copy.deepcopy(golden_b)).report()
    assert rep["total"] == 1.0
    assert rep["netlist"]["f1"] == 1.0
    assert rep["netlist"]["netlist_equivalent"] is True
    assert rep["layout"]["rmse_raw"] == 0.0


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
