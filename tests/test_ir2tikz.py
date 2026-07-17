# -*- coding: utf-8 -*-
"""ir2tikz 测试：金样往返、validate 门禁、jump 切链、debug/fragment、确定性。"""
import json
import os
import subprocess

import pytest

import ir2tikz


def run_ir2tikz(tmp_path, ir, extra=None, name="ir.json", out="out.tex"):
    p = tmp_path / name
    p.write_text(json.dumps(ir, ensure_ascii=False), encoding="utf-8")
    o = tmp_path / out
    rc = ir2tikz.main([str(p), "-o", str(o)] + (extra or []))
    text = o.read_text(encoding="utf-8") if o.exists() else None
    return rc, o, text


# ---------------------------------------------------------------- 金样往返

def test_golden_a_structure(tmp_path, golden_a):
    rc, _o, text = run_ir2tikz(tmp_path, golden_a)
    assert rc == 0
    for frag in (
        "%% ==== [region] source ====",
        "to[V, invert, l=$U_s$, a=$6\\mathrm{V}$, name=V1]",
        "\\coordinate (N_MID) at (2,2);",
        "to[R, l=$R_1$, a=$1\\mathrm{k}\\Omega$, name=R1]",
        "\\node[circ] at (N_MID) {};",
        "\\node[ocirc] at (5.5,2) {};",
        "\\node[ground] at (4,0) {};",
    ):
        assert frag in text, frag


def test_golden_b_structure(tmp_path, golden_b):
    rc, _o, text = run_ir2tikz(tmp_path, golden_b)
    assert rc == 0
    for frag in (
        "\\node[npn] (Q1) at (5,4) {};",
        "(Q1.B)",
        "(Q1.C)",
        "l_=$R_C$",
        "a^=$2\\mathrm{k}\\Omega$",
        "\\usepackage[american]{circuitikz}",
        "\\ctikzset{bipoles/length=1.0cm}",
    ):
        assert frag in text, frag
    assert "ctex" not in text  # 纯 ASCII 不加 ctex


def test_explicit_node_reference_serializes_to_coordinate(tmp_path, golden_b):
    golden_b["nodes"] = [{"name": "N_STUB", "at": [0, 4]}]
    golden_b["wires"][0]["points"][0] = {"node": "N_STUB"}
    rc, _o, text = run_ir2tikz(tmp_path, golden_b)
    assert rc == 0
    assert "\\coordinate (N_STUB) at (0,4);" in text
    assert "(N_STUB) -- (1,4);" in text


def test_golden_a_compiles(tmp_path, golden_a):
    rc, o, _text = run_ir2tikz(tmp_path, golden_a)
    assert rc == 0
    proc = subprocess.run(
        ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", o.name],
        cwd=str(tmp_path), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=120)
    assert proc.returncode == 0, proc.stdout[-800:]


# ---------------------------------------------------------------- 门禁

def test_gate_rejects_bad_ir(tmp_path, golden_a):
    golden_a["components"][0]["pins"][0]["net"] = "N_MID"  # 制造 E007
    rc, o, text = run_ir2tikz(tmp_path, golden_a)
    assert rc == 2 and text is None and not o.exists()


def test_warnings_pass_through(tmp_path, golden_a, capsys):
    golden_a["nets"].append({"name": "N_GHOST"})  # 仅 W106
    rc, _o, text = run_ir2tikz(tmp_path, golden_a)
    assert rc == 0 and text is not None


# ---------------------------------------------------------------- jump crossing

@pytest.fixture
def jump_ir():
    return {
        "version": "kirchhoff-ir/1.0",
        "meta": {"source_image": "synthetic://jump", "title": "jump",
                 "grid": {"unit_cm": 1.0, "snap": 0.5}, "canvas": {"w": 4, "h": 4}},
        "style": {"flavor": "american"},
        "components": [], "junctions": [], "terminals": [], "texts": [],
        "regions": [], "unknowns": [],
        "wires": [
            {"id": "W1", "points": [{"xy": [0, 2]}, {"xy": [4, 2]}]},
            {"id": "W2", "points": [{"xy": [2, 0]}, {"xy": [2, 4]}]},
        ],
        "crossings": [{"at": [2, 2], "style": "jump"}],
    }


def test_jump_splits_chains(tmp_path, jump_ir):
    rc, _o, text = run_ir2tikz(tmp_path, jump_ir)
    assert rc == 0
    assert "\\node[jump crossing] (XJ1) at (2,2) {};" in text
    assert "(0,2) -- (XJ1.west);" in text
    assert "(XJ1.east) -- (4,2);" in text
    assert "(2,0) -- (XJ1.south);" in text
    assert "(XJ1.north) -- (2,4);" in text


def test_jump_compiles(tmp_path, jump_ir):
    rc, o, _text = run_ir2tikz(tmp_path, jump_ir)
    assert rc == 0
    proc = subprocess.run(
        ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", o.name],
        cwd=str(tmp_path), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=120)
    assert proc.returncode == 0, proc.stdout[-800:]


def test_plain_crossing_draws_through(tmp_path, jump_ir):
    jump_ir["crossings"][0]["style"] = "plain"
    rc, _o, text = run_ir2tikz(tmp_path, jump_ir)
    assert rc == 0
    assert "jump crossing" not in text
    assert "(0,2) -- (4,2);" in text and "(2,0) -- (2,4);" in text


# ---------------------------------------------------------------- 选项

def test_fragment_mode(tmp_path, golden_a):
    rc, _o, text = run_ir2tikz(tmp_path, golden_a, extra=["--fragment"])
    assert rc == 0
    assert text.startswith("\\begin{circuitikz}")
    assert "documentclass" not in text


def test_debug_file(tmp_path, golden_a):
    rc, o, _text = run_ir2tikz(tmp_path, golden_a, extra=["--debug"])
    assert rc == 0
    dbg = o.with_name("out.debug.tex")
    assert dbg.exists()
    dtext = dbg.read_text(encoding="utf-8")
    assert "grid" in dtext and "red" in dtext and "{V1}" in dtext


def test_debug_file_is_generated_by_default(tmp_path, golden_a):
    rc, o, _text = run_ir2tikz(tmp_path, golden_a)
    assert rc == 0
    assert o.with_name("out.debug.tex").exists()


def test_component_label_at_uses_exact_human_selected_coordinate(tmp_path, golden_b):
    q1 = next(c for c in golden_b["components"] if c["id"] == "Q1")
    q1["label"] = "Q_1"
    q1["label_at"] = [6.25, 5.75]
    rc, _o, text = run_ir2tikz(tmp_path, golden_b)
    assert rc == 0
    assert "at (6.25,5.75) {$Q_1$};" in text


def test_two_terminal_label_at_uses_exact_human_selected_coordinate(tmp_path, golden_a):
    r1 = next(c for c in golden_a["components"] if c["id"] == "R1")
    r1["label_at"] = [3.25, 4.75]
    rc, _o, text = run_ir2tikz(tmp_path, golden_a)
    assert rc == 0
    assert "at (3.25,4.75) {$R_1$};" in text


def test_cjk_texts_add_ctex(tmp_path, golden_a):
    golden_a["texts"].append(
        {"content": "输出端口", "at": [5.5, 3.4], "kind": "annotation"})
    rc, _o, text = run_ir2tikz(tmp_path, golden_a)
    assert rc == 0 and "\\usepackage{ctex}" in text


def test_cjk_text_compiles_with_lualatex(tmp_path, golden_a):
    golden_a["texts"].append(
        {"content": "输出端口", "at": [5.5, 3.4], "kind": "annotation"})
    rc, output, _text = run_ir2tikz(tmp_path, golden_a)
    assert rc == 0

    proc = subprocess.run(
        ["lualatex", "-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error", output.name],
        cwd=tmp_path,
        capture_output=True,
        timeout=120,
    )

    assert proc.returncode == 0, proc.stdout.decode("utf-8", "replace")[-1500:]


@pytest.mark.parametrize("payload", [
    r"\typeout{KIRCHHOFF_IR_TEX_INJECTION}",
    r"\input{secrets.txt}",
    r"\write18{whoami}",
    "trailing\\",
    "unbalanced}",
    "escape] ; \\draw (0,0)",
    "raw,comma",
    "line\nbreak",
])
def test_untrusted_ir_text_rejects_unsafe_tex_commands(tmp_path, golden_a, payload):
    golden_a["components"][1]["label"] = payload

    rc, _out, _text = run_ir2tikz(tmp_path, golden_a)

    assert rc == 2


def test_metadata_comments_cannot_escape_to_tex_body(tmp_path, golden_a):
    golden_a["meta"]["title"] = "safe\n\\typeout{META_INJECTION}"
    golden_a["meta"]["source_image"] = "source^^J\\typeout{SOURCE_INJECTION}"
    golden_a["regions"][0]["name"] = "region\r\\typeout{REGION_INJECTION}"

    rc, output, text = run_ir2tikz(tmp_path, golden_a)

    assert rc == 0
    assert "\n\\typeout" not in text
    proc = subprocess.run(
        ["pdflatex", "-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error", output.name],
        cwd=tmp_path,
        capture_output=True,
        timeout=120,
    )
    log = output.with_suffix(".log").read_text(encoding="utf-8", errors="replace")
    assert proc.returncode == 0, proc.stdout.decode("utf-8", "replace")[-1500:]
    assert "META_INJECTION" not in log
    assert "SOURCE_INJECTION" not in log
    assert "REGION_INJECTION" not in log


def test_safe_math_and_cjk_text_remain_supported(tmp_path, golden_a):
    golden_a["components"][1]["label"] = "R_1"
    golden_a["components"][1]["value"] = r"1\mathrm{k}\Omega"
    golden_a["texts"].append(
        {"content": "输出端口", "at": [5.5, 3.4], "kind": "annotation"})

    rc, _out, text = run_ir2tikz(tmp_path, golden_a)

    assert rc == 0
    assert "$R_1$" in text
    assert r"1\mathrm{k}\Omega" in text
    assert "输出端口" in text


def test_european_flavor(tmp_path, golden_a):
    golden_a["style"]["flavor"] = "european"
    rc, _o, text = run_ir2tikz(tmp_path, golden_a)
    assert rc == 0 and "\\usepackage[european]{circuitikz}" in text


def test_unknown_box(tmp_path, golden_a):
    golden_a["unknowns"].append(
        {"id": "UNK1", "at": [6, 4], "size": [1, 1], "pin_count": 0,
         "pins": [], "appearance": "圆圈叉"})
    rc, _o, text = run_ir2tikz(tmp_path, golden_a)
    assert rc == 0
    assert "\\draw[dashed] (5.5,3.5) rectangle (6.5,4.5);" in text
    assert "UNK1?" in text


def test_deterministic_output(tmp_path, golden_b):
    _rc, _o, t1 = run_ir2tikz(tmp_path, golden_b, out="o1.tex")
    _rc, _o, t2 = run_ir2tikz(tmp_path, golden_b, out="o2.tex")
    assert t1 == t2


def test_exit3_missing_input(tmp_path):
    rc = ir2tikz.main(["no_such.json", "-o", str(tmp_path / "x.tex")])
    assert rc == 3


def test_unassigned_region_fallback(tmp_path, golden_a):
    golden_a["regions"] = []  # 全部元件无区 -> (unassigned) 兜底 + W107
    rc, _o, text = run_ir2tikz(tmp_path, golden_a)
    assert rc == 0 and "[region] (unassigned)" in text


# ---------------------------------------------------------------- arrows (v1.1)

def test_arrows_section_emitted(tmp_path, golden_a):
    golden_a["arrows"] = [{"at": [3, 2], "dir": 0, "label": "i_1"}]
    rc, _o, text = run_ir2tikz(tmp_path, golden_a)
    assert rc == 0
    assert "%% ==== arrows ====" in text
    assert "\\draw[-{Latex}]" in text
    assert "{$i_1$}" in text


def test_arrows_absent_no_section(tmp_path, golden_a):
    rc, _o, text = run_ir2tikz(tmp_path, golden_a)
    assert rc == 0 and "==== arrows ====" not in text


def test_arrows_compile(tmp_path, golden_a):
    golden_a["arrows"] = [{"at": [3, 2], "dir": 0, "label": "i_1"}]
    rc, o, _text = run_ir2tikz(tmp_path, golden_a)
    assert rc == 0
    proc = subprocess.run(
        ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", o.name],
        cwd=str(tmp_path), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=120)
    assert proc.returncode == 0, proc.stdout.decode("utf-8", "replace")[-1500:]


# ---------------------------------------------------------------- v1.1: scale / label gaps

def test_v11_fields_absent_output_unchanged(tmp_path, golden_b):
    # 不写新字段 ⇒ 正文里既无 per-instance bipoles/length 也无 node scale（金样逐字节门在
    # kirchhoff-paper 端再机械验证一次）。
    rc, _o, text = run_ir2tikz(tmp_path, golden_b)
    assert rc == 0
    assert "/tikz/circuitikz/bipoles/length" not in text
    assert "scale=" not in text


def test_v11_two_scale_appends_bipole_length(tmp_path, golden_b):
    golden_b["components"][0]["scale"] = 0.75   # R1，基数取自 config 的 bipoles/length=1.0cm
    rc, _o, text = run_ir2tikz(tmp_path, golden_b)
    assert rc == 0
    assert "name=R1, /tikz/circuitikz/bipoles/length=0.75cm]" in text


def test_v11_multi_single_scale_node_option(tmp_path, golden_b):
    golden_b["components"][3]["scale"] = 1.5    # Q1
    golden_b["components"][6]["scale"] = 2.0    # GND2
    rc, _o, text = run_ir2tikz(tmp_path, golden_b)
    assert rc == 0
    assert "\\node[npn, scale=1.5] (Q1) at (5,4) {};" in text
    assert "\\node[ground, scale=2] at (5,2) {};" in text


def test_v11_two_label_gap_switches_to_node(tmp_path, golden_a):
    # A 的 R1 (2,4)->(2,2) 竖放，label_side=right：l= 退出 to[]，改独立节点 anchor=west。
    golden_a["components"][1]["label_gap"] = 0.4
    rc, _o, text = run_ir2tikz(tmp_path, golden_a)
    assert rc == 0
    assert "l=$R_1$" not in text
    assert "to[R, a=$1\\mathrm{k}\\Omega$, name=R1]" in text
    assert "\\node[anchor=west] at (2.4,3) {$R_1$};" in text


def test_v11_two_value_gap_keeps_label_inline(tmp_path, golden_a):
    # V1 (0,0)->(0,4) 朝上，value_side=right：a= 退出 to[]，l= 原样保留。
    golden_a["components"][0]["value_gap"] = 0.6
    rc, _o, text = run_ir2tikz(tmp_path, golden_a)
    assert rc == 0
    assert "a=$6\\mathrm{V}$" not in text
    assert "to[V, invert, l=$U_s$, name=V1]" in text
    assert "\\node[anchor=west] at (0.6,2) {$6\\mathrm{V}$};" in text


def test_v11_multi_label_gap(tmp_path, golden_b):
    golden_b["components"][3]["label_gap"] = 0.5   # Q1 label 右侧，bbox 右缘 x=5
    rc, _o, text = run_ir2tikz(tmp_path, golden_b)
    assert rc == 0
    assert "\\node[anchor=west] at (5.5,4) {$Q_1$};" in text
    assert "at (5.2,4)" not in text


def test_v11_single_label_gap(tmp_path, golden_b):
    golden_b["components"][4]["label_gap"] = 0.9   # VCC1 label above，缺省 0.5 → 0.9
    rc, _o, text = run_ir2tikz(tmp_path, golden_b)
    assert rc == 0
    assert "\\node[anchor=south] at (5,8.4) {$+12\\mathrm{V}$};" in text


def test_v11_combo_compiles(tmp_path, golden_b):
    golden_b["components"][0]["scale"] = 0.75
    golden_b["components"][3]["scale"] = 1.5
    golden_b["components"][3]["label_gap"] = 0.5
    golden_b["components"][4]["label_gap"] = 0.9
    golden_b["components"][6]["scale"] = 2.0
    rc, o, _text = run_ir2tikz(tmp_path, golden_b)
    assert rc == 0
    proc = subprocess.run(
        ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", o.name],
        cwd=str(tmp_path), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=120)
    assert proc.returncode == 0, proc.stdout.decode("utf-8", "replace")[-1500:]
