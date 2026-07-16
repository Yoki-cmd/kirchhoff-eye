#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""gen_anchor_table.py — Phase 0 一次性工具：实测多端件符号的 anchor 偏移。

方法（PLAN.md §7.6）：生成一个 .tex，把每个多端件 \\node 在已知坐标上，
用 \\pgfpointanchor 取各 anchor 坐标 \\typeout 进编译 log；本脚本跑 pdflatex
后解析 log，换算 cm（=网格单位）生成 templates/anchors.json。全程机器读数。

用法: gen_anchor_table.py [-o anchors.json] [--build-dir DIR]
退出码: 0 成功 / 2 解析失败 / 3 环境或 IO 错误
"""
import argparse
import json
import os
import re
import subprocess
import sys

PT_PER_CM = 28.45274
ROUND_DIGITS = 4
X_SPACING_CM = 10  # 相邻符号横向间距，避免 anchor 归属混淆

# (ir_type, variant, tikz 样式串, {IR pin 名: circuitikz anchor 名})
NODE_TYPES = [
    ("npn", None, "npn", {"B": "B", "C": "C", "E": "E"}),
    ("pnp", None, "pnp", {"B": "B", "C": "C", "E": "E"}),
    ("nmos", None, "nmos", {"G": "G", "D": "D", "S": "S"}),
    ("pmos", None, "pmos", {"G": "G", "D": "D", "S": "S"}),
    ("opamp", None, "op amp", {"inp": "+", "inn": "-", "out": "out"}),
    ("opamp", "noinv_up", "op amp, noinv input up",
     {"inp": "+", "inn": "-", "out": "out"}),
    ("transformer", None, "transformer",
     {"A1": "A1", "A2": "A2", "B1": "B1", "B2": "B2"}),
    ("transformer", "core", "transformer core",
     {"A1": "A1", "A2": "A2", "B1": "B1", "B2": "B2"}),
    ("spdt", None, "spdt", {"in": "in", "out1": "out 1", "out2": "out 2"}),
]
BBOX_ANCHORS = ("north west", "south east")

TEX_HEADER_FMT = r"""\documentclass[margin=5pt]{standalone}
\usepackage[american]{circuitikz}
%(ctikzset)s
\begin{document}
\begin{circuitikz}
\makeatletter
\def\logank#1#2{\pgfpointanchor{#1}{#2}\typeout{ANK #1 [#2] \the\pgf@x\space\the\pgf@y}}
"""
TEX_FOOTER = "\\end{circuitikz}\n\\end{document}\n"

ANK_RE = re.compile(r"^ANK (\S+) \[([^\]]*)\] (-?[0-9.]+)pt\s+(-?[0-9.]+)pt")


def type_key(ir_type, variant):
    return ir_type + ("|" + variant if variant else "")


def load_ctikzset():
    """从 config.json 读取生产 ctikzset，注入 anchor-gen tex，保证 anchor 与出图同风格。

    与 ir2tikz.py 一致：读 style.ctikzset，包成 \\ctikzset{...}；缺失则返回空串。
    """
    cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "..", "config.json")
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        return ""
    ctikzset = cfg.get("style", {}).get("ctikzset", "")
    return "\\ctikzset{%s}" % ctikzset if ctikzset else ""


def build_tex():
    lines = [TEX_HEADER_FMT % {"ctikzset": load_ctikzset()}]
    for i, (_, _, style, pins) in enumerate(NODE_TYPES):
        name = "n%d" % i
        x = i * X_SPACING_CM
        lines.append("\\node[%s] (%s) at (%d,0) {};\n" % (style, name, x))
        for anchor in list(pins.values()) + list(BBOX_ANCHORS):
            lines.append("\\logank{%s}{%s}\n" % (name, anchor))
    lines.append(TEX_FOOTER)
    return "".join(lines)


def run_pdflatex(build_dir, tex_name):
    try:
        proc = subprocess.run(
            ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", tex_name],
            cwd=build_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=120)
    except FileNotFoundError:
        sys.stderr.write("ERROR: 找不到 pdflatex（应随 TeX Live 2026 在 PATH 上）\n")
        sys.exit(3)
    except subprocess.TimeoutExpired:
        sys.stderr.write("ERROR: pdflatex 超时\n")
        sys.exit(3)
    return proc.returncode


def parse_log(log_text):
    """返回 {node_name: {anchor: (x_pt, y_pt)}} 与 circuitikz 版本串。"""
    anchors = {}
    for line in log_text.splitlines():
        m = ANK_RE.match(line)
        if m:
            node, anchor, x, y = m.group(1), m.group(2), float(m.group(3)), float(m.group(4))
            anchors.setdefault(node, {})[anchor] = (x, y)
    ver = ""
    m = re.search(r"Package: circuitikz (\d{4}/\d{2}/\d{2})", log_text)
    date = m.group(1) if m else "?"
    m = re.search(r"The CircuiTikz circuit drawing package version\s*\n?\s*([0-9.]+)", log_text)
    if m:
        ver = m.group(1)
    return anchors, "%s (%s)" % (ver or "?", date)


def to_cm(v_pt):
    return round(v_pt / PT_PER_CM, ROUND_DIGITS)


def main():
    ap = argparse.ArgumentParser(description="实测多端件 anchor 偏移 -> anchors.json")
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument("-o", "--output",
                    default=os.path.join(here, "..", "templates", "anchors.json"))
    ap.add_argument("--build-dir",
                    default=os.path.join(here, "..", "out", "anchor_gen"))
    args = ap.parse_args()

    build_dir = os.path.abspath(args.build_dir)
    try:
        os.makedirs(build_dir, exist_ok=True)
        tex_path = os.path.join(build_dir, "anchor_gen.tex")
        with open(tex_path, "w", encoding="utf-8") as f:
            f.write(build_tex())
    except OSError as e:
        sys.stderr.write("ERROR: 写入构建目录失败: %s\n" % e)
        sys.exit(3)

    rc = run_pdflatex(build_dir, "anchor_gen.tex")
    log_path = os.path.join(build_dir, "anchor_gen.log")
    if not os.path.exists(log_path):
        sys.stderr.write("ERROR: 编译未产生 log（pdflatex rc=%s）\n" % rc)
        sys.exit(3)
    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        log_text = f.read()
    if rc != 0:
        sys.stderr.write("ERROR: pdflatex 编译失败，检查 %s\n" % log_path)
        sys.exit(3)

    raw, version = parse_log(log_text)
    types = {}
    problems = []
    for i, (ir_type, variant, style, pins) in enumerate(NODE_TYPES):
        name = "n%d" % i
        placed_x_pt = i * X_SPACING_CM * PT_PER_CM
        got = raw.get(name, {})
        entry = {"node": style, "pins": {}}
        for ir_pin, anchor in pins.items():
            if anchor not in got:
                problems.append("%s 缺 anchor [%s]" % (type_key(ir_type, variant), anchor))
                continue
            x_pt, y_pt = got[anchor]
            entry["pins"][ir_pin] = {
                "anchor": anchor,
                "offset": [to_cm(x_pt - placed_x_pt), to_cm(y_pt)],
            }
        if all(a in got for a in BBOX_ANCHORS):
            nw = got["north west"]
            se = got["south east"]
            entry["bbox"] = [
                [to_cm(nw[0] - placed_x_pt), to_cm(se[1])],
                [to_cm(se[0] - placed_x_pt), to_cm(nw[1])],
            ]
        types[type_key(ir_type, variant)] = entry

    if problems:
        sys.stderr.write("ERROR: log 解析不完整:\n" + "\n".join("  " + p for p in problems) + "\n")
        sys.exit(2)

    doc = {
        "_meta": {
            "generated_by": "scripts/gen_anchor_table.py",
            "circuitikz": version,
            "unit": "cm (=1 网格单位)",
            "pin_formula": "pin = at + M^mirror * R(rotate) * offset "
                           "(mirror 先作用于已旋转坐标，与 [xscale=-1, rotate=t] 实测一致)",
            "bbox": "[[xmin,ymin],[xmax,ymax]] 相对 at，未变换",
        },
        "types": types,
    }
    out_path = os.path.abspath(args.output)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    sys.stdout.write("OK anchors -> %s (circuitikz %s, %d types)\n"
                     % (out_path, version, len(types)))
    sys.exit(0)


if __name__ == "__main__":
    main()
