# -*- coding: utf-8 -*-
"""validate_ir 坏 IR 注入测试集：PLAN.md §7.1 全部 17 条规则逐条命中错误码与退出码。

用例基座 = 金样 A/B（已知干净），每例做最小变异后断言：
(a) 目标错误码出现 (b) 退出码符合 0/1/2 约定。
"""
import pytest

import irlib
from conftest import codes


# ---------------------------------------------------------------- 基线

def test_golden_a_clean(golden_a, vrun):
    rc, out = vrun(golden_a)
    assert rc == 0 and out["findings"] == []


def test_golden_b_clean(golden_b, vrun):
    rc, out = vrun(golden_b)
    assert rc == 0 and out["findings"] == []


def test_golden_b_clean_all_phases(golden_b, vrun):
    for phase in ("skeleton", "geometry", "full"):
        rc, _ = vrun(golden_b, phase=phase)
        assert rc == 0, phase


@pytest.mark.parametrize(
    "section,index,field",
    [
        ("components", 1, "label"),
        ("components", 1, "value"),
        ("terminals", 0, "label"),
        ("texts", 0, "content"),
        ("arrows", 0, "label"),
        ("annotations", 0, "label"),
    ],
)
def test_e016_rejects_unsafe_tex_in_every_rendered_text_field(
        golden_a, vrun, section, index, field):
    golden_a["texts"] = [{"content": "note", "at": [1, 1], "kind": "annotation"}]
    golden_a["arrows"] = [{"at": [4, 2], "dir": 0, "label": "i_o"}]
    golden_a["annotations"] = [{
        "id": "A1", "kind": "free_text", "label": "note", "label_at": [1, 1],
    }]
    golden_a[section][index][field] = r"\input{secret}"

    rc, out = vrun(golden_a, phase="skeleton")

    assert rc == 2
    finding = next(f for f in out["findings"] if f["code"] == "E016")
    assert finding["path"] == f"/{section}/{index}/{field}"


@pytest.mark.parametrize("phase", ["skeleton", "geometry", "full"])
def test_e016_runs_in_every_validation_phase(golden_a, vrun, phase):
    golden_a["components"][1]["label"] = r"\typeout{MARK}"

    rc, out = vrun(golden_a, phase=phase)

    assert rc == 2 and "E016" in codes(out)


@pytest.mark.parametrize("text", [
    "R_1", "i_o", "R_{C1}", r"1\mathrm{k}\Omega",
    r"470\mu\mathrm{F}", r"2\,\Omega", "输出端口",
])
def test_e016_allows_documented_safe_math_and_unicode(golden_a, vrun, text):
    golden_a["components"][1]["label"] = text

    rc, out = vrun(golden_a)

    assert rc == 0 and "E016" not in codes(out)


# ---------------------------------------------------------------- E001

def test_e001_unknown_type(golden_b, vrun):
    golden_b["components"][0]["type"] = "resistorr"
    rc, out = vrun(golden_b)
    assert rc == 2 and "E001" in codes(out)


def test_e001_structural(golden_b, vrun):
    del golden_b["meta"]
    rc, out = vrun(golden_b)
    assert rc == 2 and "E001" in codes(out)


# ---------------------------------------------------------------- E002

def test_e002_duplicate_id(golden_b, vrun):
    golden_b["components"][1]["id"] = "R1"
    rc, out = vrun(golden_b)
    assert rc == 2 and "E002" in codes(out)


def test_e002_dangling_component_ref(golden_b, vrun):
    golden_b["wires"][0]["points"][1]["pin"] = "R9.1"
    rc, out = vrun(golden_b)
    assert rc == 2 and "E002" in codes(out)


def test_e002_bad_pin_name(golden_b, vrun):
    golden_b["wires"][0]["points"][1]["pin"] = "R1.3"
    rc, out = vrun(golden_b)
    assert rc == 2 and "E002" in codes(out)


def test_e002_region_ref(golden_b, vrun):
    golden_b["regions"][0]["component_ids"].append("Z9")
    rc, out = vrun(golden_b)
    assert rc == 2 and "E002" in codes(out)


def test_e002_unknown_node_ref(golden_b, vrun):
    golden_b["wires"][0]["points"][0] = {"node": "N_MISSING"}
    rc, out = vrun(golden_b)
    assert rc == 2 and "E002" in codes(out)


def test_explicit_node_reference_connects_wires(golden_b, vrun):
    golden_b["nodes"] = [{"name": "N_STUB", "at": [0, 4]}]
    golden_b["wires"][0]["points"][0] = {"node": "N_STUB"}
    rc, out = vrun(golden_b)
    assert rc == 0 and out["findings"] == []


# ---------------------------------------------------------------- E003

def test_e003_unsnapped_component(golden_b, vrun):
    golden_b["routing"] = {"orthogonal": "strict", "grid_snap": "strict", "grid_step": 0.5}
    golden_b["components"][0]["from"] = [1.2, 4]
    rc, out = vrun(golden_b)
    assert rc == 2 and "E003" in codes(out)


def test_e003_unsnapped_wire_xy(golden_a, vrun):
    golden_a["routing"] = {"orthogonal": "strict", "grid_snap": "strict", "grid_step": 0.5}
    golden_a["wires"][2]["points"][1]["xy"] = [4.1, 2]
    rc, out = vrun(golden_a)
    assert rc == 2 and "E003" in codes(out)


def test_e003_texts_exempt(golden_b, vrun):
    golden_b["texts"][0]["at"] = [0.23, 4.61]
    rc, out = vrun(golden_b)
    assert rc == 0, out


def test_e003_default_warn_allows_offgrid_waypoint(golden_b, vrun):
    golden_b["wires"][1]["points"] = [
        {"pin": "R1.2"}, {"xy": [3.7, 4]}, {"pin": "Q1.B"}]
    rc, out = vrun(golden_b)
    finding = next(f for f in out["findings"] if f["code"] == "E003")
    assert rc == 1 and finding["severity"] == "W"


def test_e003_grid_snap_off_suppresses_report(golden_b, vrun):
    golden_b["routing"] = {"orthogonal": "strict", "grid_snap": "off", "grid_step": 0.5}
    golden_b["wires"][1]["points"] = [
        {"pin": "R1.2"}, {"xy": [3.7, 4]}, {"pin": "Q1.B"}]
    rc, out = vrun(golden_b)
    assert rc == 0 and "E003" not in codes(out)


def test_e003_custom_grid_step(golden_b, vrun):
    golden_b["routing"] = {"orthogonal": "strict", "grid_snap": "strict", "grid_step": 0.25}
    golden_b["components"][0]["from"] = [1.25, 4]
    rc, out = vrun(golden_b)
    assert "E003" not in codes(out)


# ---------------------------------------------------------------- E004

def test_e004_diagonal_wire(golden_a, vrun):
    golden_a["wires"][2]["points"][1]["xy"] = [4, 2.5]
    rc, out = vrun(golden_a)
    assert rc == 2 and "E004" in codes(out)


def test_e004_multi_pin_near_diagonal_is_rejected(golden_b, vrun):
    # 旧 PIN_ORTHO_TOL=0.25 会把这条 dx=0.1, dy=0.1 的斜线当成水平线。
    golden_b["wires"][1]["points"][0] = {"xy": [4.5, 4.1]}
    rc, out = vrun(golden_b)
    assert rc == 2 and "E004" in codes(out)
    finding = next(f for f in out["findings"] if f["code"] == "E004")
    assert "L 形 waypoint" in finding["hint"]


def test_e004_diagonal_two_terminal(golden_a, vrun):
    golden_a["components"][3]["from"] = [4.5, 2]  # C1 斜放
    rc, out = vrun(golden_a)
    assert rc == 2 and "E004" in codes(out)


def test_e004_allow_diagonal_flag(golden_a, vrun):
    c1 = golden_a["components"][3]
    c1["from"] = [4.5, 2]
    c1["flags"] = ["allow_diagonal"]
    rc, out = vrun(golden_a, phase="skeleton")
    assert "E004" not in codes(out)


# ---------------------------------------------------------------- E005

def test_e005_zero_span(golden_b, vrun):
    golden_b["components"][0]["to"] = [1, 4]
    rc, out = vrun(golden_b)
    assert rc == 2 and "E005" in codes(out)


def test_e005_short_span(golden_b, vrun):
    golden_b["components"][1]["to"] = [3, 3.5]  # C1 跨度 0.5
    rc, out = vrun(golden_b)
    assert rc == 2 and "E005" in codes(out)


# ---------------------------------------------------------------- E006

def test_e006_wrong_pin_names(golden_b, vrun):
    golden_b["components"][3]["pins"][0]["name"] = "X"
    rc, out = vrun(golden_b)
    assert rc == 2 and "E006" in codes(out)


def test_e006_missing_pin(golden_b, vrun):
    pins = golden_b["components"][3]["pins"]
    golden_b["components"][3]["pins"] = pins[:2] + [dict(pins[1], name="C")]
    rc, out = vrun(golden_b)
    assert rc == 2 and "E006" in codes(out)


def test_e006_bad_variant(golden_b, vrun):
    golden_b["components"][3]["variant"] = "core"
    rc, out = vrun(golden_b)
    assert rc == 2 and "E006" in codes(out)


# ---------------------------------------------------------------- E007

def test_e007_merged_and_split(golden_a, vrun):
    golden_a["components"][0]["pins"][0]["net"] = "N_MID"  # V1 负端错标成 N_MID
    rc, out = vrun(golden_a)
    assert rc == 2 and "E007" in codes(out)
    msgs = " ".join(f["message"] for f in out["findings"] if f["code"] == "E007")
    assert "N_MID" in msgs


def test_e007_split_only(golden_b, vrun):
    # 断开 W2（R1.2 -> Q1.B），N_B 网被声明为一体但几何分裂
    golden_b["wires"] = [w for w in golden_b["wires"] if w["id"] != "W2"]
    rc, out = vrun(golden_b)
    assert rc == 2 and "E007" in codes(out)


def test_e007_reports_explicit_node_evidence(golden_b, vrun):
    golden_b["nodes"] = [{"name": "N_STUB", "at": [0, 4]}]
    golden_b["wires"][0]["points"][0] = {"node": "N_STUB"}
    golden_b["components"][0]["pins"][0]["net"] = "N_B"
    rc, out = vrun(golden_b)
    messages = " ".join(f["message"] for f in out["findings"] if f["code"] == "E007")
    assert rc == 2 and "evidence=explicit+geometric" in messages


# ---------------------------------------------------------------- E008

def _cross_wire(ir):
    ir["wires"].append(
        {"id": "W9", "points": [{"xy": [3, 1]}, {"xy": [3, 3]}]})
    return ir


def test_e008_undeclared_cross(golden_a, vrun):
    rc, out = vrun(_cross_wire(golden_a))
    assert rc == 2 and "E008" in codes(out)


def test_e008_declared_crossing_ok(golden_a, vrun):
    ir = _cross_wire(golden_a)
    ir["crossings"].append({"at": [3, 2], "style": "plain"})
    rc, out = vrun(ir)
    assert "E008" not in codes(out)


def test_e008_four_way_vertex_needs_junction(golden_a, vrun):
    # 去掉 (2,2) 的 junction 并加第四路：R1.2/R2.1/W3/W9 四路汇合无声明
    golden_a["junctions"] = []
    golden_a["wires"].append(
        {"id": "W9", "points": [{"xy": [0.5, 2]}, {"xy": [2, 2]}]})
    rc, out = vrun(golden_a)
    assert rc == 2 and "E008" in codes(out)


# ---------------------------------------------------------------- E013

def test_e013_junction_off_wire(golden_a, vrun):
    golden_a["junctions"].append({"at": [6, 4]})
    rc, out = vrun(golden_a)
    assert rc == 2 and "E013" in codes(out)


def test_e013_junction_on_interior_cross(golden_a, vrun):
    # 十字交点声明 junction 但两条 wire 都没在交点设顶点 -> E013 引导加顶点
    ir = _cross_wire(golden_a)
    ir["junctions"].append({"at": [3, 2]})
    rc, out = vrun(ir)
    assert rc == 2 and "E013" in codes(out)


def test_e013_crossing_not_a_cross(golden_a, vrun):
    golden_a["crossings"].append({"at": [2, 2], "style": "plain"})
    rc, out = vrun(golden_a)
    assert rc == 2 and "E013" in codes(out)


# ---------------------------------------------------------------- E014

def test_e014_wire_through_pin(golden_a, vrun):
    golden_a["wires"].append(
        {"id": "W9", "points": [{"xy": [1, 2]}, {"xy": [3, 2]}]})
    rc, out = vrun(golden_a)
    assert rc == 2 and "E014" in codes(out)


def test_e014_wire_through_other_vertex(golden_a, vrun):
    # W9 中段穿过 W2 的中间顶点 (2,0)（单侧顶点 = 模糊连接）
    golden_a["wires"].append(
        {"id": "W9", "points": [{"xy": [1.5, 0]}, {"xy": [2.5, 0]}]})
    rc, out = vrun(golden_a)
    assert rc == 2 and "E014" in codes(out)


# ---------------------------------------------------------------- W101

def test_w101_dangling_pin(golden_b, vrun):
    golden_b["terminals"] = []
    rc, out = vrun(golden_b)
    assert rc == 1 and "W101" in codes(out)


def test_w101_terminal_suppresses(golden_b, vrun):
    rc, out = vrun(golden_b)
    assert "W101" not in codes(out)


# ---------------------------------------------------------------- W102

def test_w102_two_way_junction(golden_a, vrun):
    golden_a["junctions"].append({"at": [0, 4]})  # V1.2 与 W1 端点，仅 2 路
    rc, out = vrun(golden_a)
    assert rc == 1 and "W102" in codes(out)


# ---------------------------------------------------------------- W103

def test_w103_pose_mismatch(golden_b, vrun):
    golden_b["components"][3]["pins"][0]["at"] = [5.8, 4]
    rc, out = vrun(golden_b)
    assert rc == 1 and "W103" in codes(out)


# ---------------------------------------------------------------- W104

def test_w104_overlap(golden_a, vrun):
    golden_a["components"].append(
        {"id": "R3", "type": "resistor", "from": [2, 3.5], "to": [2, 1.5],
         "pins": [{"name": "1", "net": "N_X1"}, {"name": "2", "net": "N_X2"}]})
    golden_a["regions"][1]["component_ids"].append("R3")
    rc, out = vrun(golden_a)
    assert rc == 1 and "W104" in codes(out)


def test_w104_shared_pin_not_overlap(golden_a, vrun):
    rc, out = vrun(golden_a)
    assert "W104" not in codes(out)  # C1 与 GND1 共点相接不算重叠


# ---------------------------------------------------------------- W105

def test_w105_canvas_too_big(golden_a, vrun):
    golden_a["meta"]["canvas"]["w"] = 40
    rc, out = vrun(golden_a)
    assert rc == 1 and "W105" in codes(out)


def test_w105_component_outside(golden_a, vrun):
    golden_a["meta"]["canvas"]["h"] = 3  # V1 顶端 (0,4) 出画布
    rc, out = vrun(golden_a)
    assert rc == 1 and "W105" in codes(out)


# ---------------------------------------------------------------- W106

def test_w106_declared_unused(golden_a, vrun):
    golden_a["nets"].append({"name": "N_GHOST"})
    rc, out = vrun(golden_a)
    assert rc == 1 and "W106" in codes(out)


def test_w106_used_undeclared(golden_a, vrun):
    golden_a["nets"] = [n for n in golden_a["nets"] if n["name"] != "N_MID"]
    rc, out = vrun(golden_a)
    assert rc == 1 and "W106" in codes(out)


# ---------------------------------------------------------------- W107

def test_w107_region_gap(golden_a, vrun):
    golden_a["regions"] = golden_a["regions"][:2]  # 去掉 output 区
    rc, out = vrun(golden_a)
    assert rc == 1 and "W107" in codes(out)


# ---------------------------------------------------------------- W108

def _unknown_entry(golden_a):
    return {
        "id": "UNK1", "at": [1, 1], "size": [1, 1], "pin_count": 1,
        "pins": [{"name": "1", "net": golden_a["nets"][0]["name"], "at": [1, 1.5]}],
        "appearance": "占位测试：词表外符号",
    }


def test_w108_unknowns_force_needs_human(golden_a, vrun):
    golden_a["unknowns"] = [_unknown_entry(golden_a)]
    rc, out = vrun(golden_a)
    assert "W108" in codes(out)  # unknowns 非空 → 提醒 needs_human


def test_w108_absent_without_unknowns(golden_a, vrun):
    rc, out = vrun(golden_a)
    assert "W108" not in codes(out)


def test_e004_short_pin_segment_ok(golden_b, vrun):
    # 回归：PIN-TOL 容差下长度 0.23 的真垂直段(Q1.C->(5,5))曾被误判为点重合
    golden_b["components"][2]["from"] = [5, 5]  # R2 下移到 (5,5)
    golden_b["components"][2]["to"] = [5, 6.5]
    golden_b["components"][4]["at"] = [5, 6.5]  # VCC1 跟随
    rc, out = vrun(golden_b)
    assert "E004" not in codes(out), out


# ---------------------------------------------------------------- 其他契约

def test_exit3_missing_file():
    import validate_ir
    assert validate_ir.main(["no_such_file.json", "--json"]) == 3


def test_findings_have_hints(golden_b, vrun):
    golden_b["components"][1]["id"] = "R1"
    _rc, out = vrun(golden_b)
    assert out["findings"] and all(f["hint"] for f in out["findings"])


# ---------------------------------------------------------------- arrows (E013, v1.1)

def test_arrows_on_wire_clean(golden_a, vrun):
    # W3 段 [2,2]-[4,2] 为水平导线；dir=0 与其平行。
    golden_a["arrows"] = [{"at": [3, 2], "dir": 0, "label": "i_1"}]
    rc, out = vrun(golden_a)
    assert rc == 0 and out["findings"] == []


def test_arrows_at_exempt_from_snap(golden_a, vrun):
    # 标注类：at 豁免 E003，可落在非 0.5 网格点（只要在导线上）。
    golden_a["arrows"] = [{"at": [3.3, 2], "dir": 0}]
    rc, out = vrun(golden_a)
    assert rc == 0 and out["findings"] == []


def test_arrows_off_wire(golden_a, vrun):
    golden_a["arrows"] = [{"at": [3, 3], "dir": 0}]
    rc, out = vrun(golden_a)
    assert rc == 2 and "E013" in codes(out)


def test_arrows_not_parallel(golden_a, vrun):
    golden_a["arrows"] = [{"at": [3, 2], "dir": 90}]
    rc, out = vrun(golden_a)
    assert rc == 2 and "E013" in codes(out)


def test_arrows_bad_dir_is_schema_error(golden_a, vrun):
    golden_a["arrows"] = [{"at": [3, 2], "dir": 45}]
    rc, out = vrun(golden_a)
    assert rc == 2 and "E001" in codes(out)


# ---------------------------------------------------------------- v1.1: scale / label_gap / value_gap

def test_v11_scale_accepted_all_kinds(golden_b, vrun):
    # 0.25 步进、[0.5, 2.0] 内：two 的引脚(from/to)不动；multi 引脚随缩放移动
    # （金样 B 的 npn 引脚偏移都是纯轴向的，缩放后连线保持正交）；single 接点=at 不动。
    golden_b["components"][0]["scale"] = 0.75   # R1 two（2·0.75 ≤ 跨度 2，不触发 W109）
    golden_b["components"][3]["scale"] = 1.5    # Q1 npn
    golden_b["components"][6]["scale"] = 2.0    # GND2 single
    rc, out = vrun(golden_b)
    assert rc == 0 and out["findings"] == []


@pytest.mark.parametrize("bad", [0.3, 3.0, 1.37])
def test_v11_scale_rejected_by_schema(golden_b, vrun, bad):
    golden_b["components"][3]["scale"] = bad
    rc, out = vrun(golden_b)
    assert rc == 2 and "E001" in codes(out)


def test_v11_label_gap_range(golden_b, vrun):
    golden_b["components"][0]["label_gap"] = 0.4
    rc, out = vrun(golden_b)
    assert rc == 0 and out["findings"] == []
    golden_b["components"][0]["label_gap"] = 2.5
    rc, out = vrun(golden_b)
    assert rc == 2 and "E001" in codes(out)


def test_v11_value_gap_two_only(golden_b, vrun):
    golden_b["components"][0]["value_gap"] = 0.3   # two：合法
    rc, out = vrun(golden_b)
    assert rc == 0 and out["findings"] == []
    del golden_b["components"][0]["value_gap"]
    golden_b["components"][3]["value_gap"] = 0.3   # multi：additionalProperties 拒收
    rc, out = vrun(golden_b)
    assert rc == 2 and "E001" in codes(out)


def test_v11_w109_body_overrun(golden_b, vrun):
    golden_b["components"][0]["scale"] = 1.5   # R1 跨度 2，体长 2×1.5=3 > 2
    rc, out = vrun(golden_b)
    assert rc == 1 and "W109" in codes(out)


def test_v11_w109_boundary_exact_fit_ok(golden_b, vrun):
    golden_b["components"][0]["scale"] = 1.0   # 2×1.0 == 跨度 2：恰好放下，不告警
    rc, out = vrun(golden_b)
    assert rc == 0 and out["findings"] == []


def test_v11_pin_formula_scales_offsets():
    # pin = at + M^mirror · R(rotate) · (offset × scale) —— 与 GATE ① 探针实测一致。
    anchors = irlib.load_anchors()
    m = irlib.IRModel({"components": [
        {"id": "Q1", "type": "npn", "at": [5, 4],
         "rotate": 90, "mirror": True, "scale": 1.5}]}, anchors)
    pos = m.pin_positions(m.components["Q1"])
    assert pos["B"] == pytest.approx((5.0, 3.1))    # (-0.6,0)×1.5 →R90→ (0,-0.9) →M→ (0,-0.9)
    assert pos["C"] == pytest.approx((5.825, 4.0))  # (0,0.55)×1.5 →R90→ (-0.825,0) →M→ (0.825,0)
    assert pos["E"] == pytest.approx((4.175, 4.0))
