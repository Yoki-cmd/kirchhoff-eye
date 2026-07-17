#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Generate public synthetic IR/image fixtures from deterministic reviewed IR only."""

import argparse
import copy
import hashlib
import json
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageFilter


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
ANCHORS = json.loads((ROOT / "templates" / "anchors.json").read_text(encoding="utf-8"))


CASES = [
    ("01", "divider-base", "divider", "base", ["resistors_capacitors_sources", "junction_connected"]),
    ("02", "divider-scale", "divider", "scale", ["resistors_capacitors_sources"]),
    ("03", "divider-jpeg", "divider", "jpeg_compression", ["resistors_capacitors_sources"]),
    ("04", "divider-blur", "divider", "mild_blur", ["resistors_capacitors_sources"]),
    ("05", "divider-gray", "divider", "grayscale", ["resistors_capacitors_sources"]),
    ("06", "divider-paper", "divider", "paper_tint", ["resistors_capacitors_sources"]),
    ("07", "divider-lines", "divider", "line_width", ["resistors_capacitors_sources"]),
    ("08", "divider-rotate", "divider", "small_rotation", ["resistors_capacitors_sources"]),
    ("09", "divider-label", "divider", "label_displacement", ["resistors_capacitors_sources"]),
    ("10", "rectifier", "rectifier", "base", ["diodes_polar_capacitors", "crossing_unconnected", "junction_connected"]),
    ("11", "zener-led", "zener", "jpeg_compression", ["diodes_polar_capacitors"]),
    ("12", "bjt", "bjt", "base", ["bjt_mos", "multiple_buses"]),
    ("13", "mos", "mos", "paper_tint", ["bjt_mos", "multiple_buses"]),
    ("14", "opamp", "opamp", "base", ["opamp", "multiple_buses"]),
    ("15", "transformer", "transformer", "grayscale", ["diodes_polar_capacitors", "multiple_buses"]),
    ("16", "spdt", "spdt", "mild_blur", ["multiple_buses"]),
    ("17", "current-annotation", "current_annotation", "base", ["current_arrow"]),
    ("18", "voltage-annotation", "voltage_annotation", "label_displacement", ["voltage_polarity"]),
    ("19", "node-polarity", "node_polarity", "scale", ["voltage_polarity", "multiple_buses"]),
    ("20", "mixed-annotations", "mixed_annotations", "small_rotation", ["current_arrow", "voltage_polarity", "crossing_unconnected"]),
]


def ir_base(case_id, title, canvas=(10, 8)):
    return {
        "version": "kirchhoff-ir/1.0",
        "meta": {
            "source_image": "",
            "title": title,
            "grid": {"unit_cm": 1.0, "snap": 0.5},
            "canvas": {"w": canvas[0], "h": canvas[1]},
        },
        "style": {"flavor": "american"},
        "routing": {"orthogonal": "strict", "grid_snap": "off", "grid_step": 0.5},
        "nets": [], "components": [], "wires": [], "junctions": [],
        "crossings": [], "terminals": [], "texts": [], "annotations": [],
        "regions": [], "unknowns": [],
    }


def net(name):
    return {"name": name}


def two(cid, ctype, start, end, n1, n2, label=None, value=None, **extra):
    item = {
        "id": cid, "type": ctype, "from": list(start), "to": list(end),
        "pins": [{"name": "1", "net": n1}, {"name": "2", "net": n2}],
    }
    if label is not None:
        item["label"] = label
    if value is not None:
        item["value"] = value
    item.update(extra)
    return item


def single(cid, ctype, at, net_name, label=None):
    item = {"id": cid, "type": ctype, "at": list(at),
            "pins": [{"name": "p", "net": net_name}]}
    if label is not None:
        item["label"] = label
    return item


def multi(cid, ctype, at, nets, label, variant=None, rotate=0, mirror=False):
    key = ctype + ("|" + variant if variant else "")
    pin_names = list(ANCHORS["types"][key]["pins"])
    item = {
        "id": cid, "type": ctype, "at": list(at), "rotate": rotate,
        "mirror": mirror,
        "pins": [{"name": name, "net": nets[name]} for name in pin_names],
        "label": label,
    }
    if variant:
        item["variant"] = variant
    return item


def wire(wid, *points):
    out = []
    for kind, value in points:
        out.append({kind: value})
    return {"id": wid, "points": out}


def divider(case_id):
    ir = ir_base(case_id, "Synthetic voltage divider", (8, 6))
    ir["nets"] = [net("N_IN"), net("N_MID"), net("GND")]
    ir["components"] = [
        two("V1", "vsource", (1, 1), (1, 5), "GND", "N_IN", "V_1", "6\\mathrm{V}", label_side="left", value_side="right"),
        two("R1", "resistor", (3, 5), (3, 3), "N_IN", "N_MID", "R_1", "1\\mathrm{k}\\Omega", label_side="right", value_side="left"),
        two("R2", "resistor", (3, 3), (3, 1), "N_MID", "GND", "R_2", "2\\mathrm{k}\\Omega", label_side="right", value_side="left"),
        two("C1", "capacitor", (5, 3), (5, 1), "N_MID", "GND", "C_1", "100\\mathrm{nF}", label_side="right", value_side="left"),
        single("GND1", "ground", (5, 1), "GND"),
    ]
    ir["wires"] = [
        wire("W1", ("pin", "V1.2"), ("pin", "R1.1")),
        wire("W2", ("pin", "V1.1"), ("xy", [3, 1]), ("pin", "C1.2")),
        wire("W3", ("pin", "R1.2"), ("xy", [5, 3]), ("xy", [7, 3])),
    ]
    ir["junctions"] = [{"at": [3, 3]}, {"at": [5, 3]}]
    ir["terminals"] = [{"at": [7, 3], "style": "ocirc", "label": "a", "label_side": "right"}]
    ir["regions"] = [{"name": "source", "component_ids": ["V1"]},
                     {"name": "divider", "component_ids": ["R1", "R2", "C1", "GND1"]}]
    return ir


def rectifier(case_id):
    ir = ir_base(case_id, "Synthetic diode and filter network", (12, 8))
    ir["nets"] = [net("N_IN"), net("N_MID"), net("N_OUT"), net("GND")]
    ir["components"] = [
        two("V1", "vsource", (1, 1), (1, 6), "GND", "N_IN", "V_1"),
        two("D1", "diode", (1, 6), (4, 6), "N_IN", "N_MID", "D_1"),
        two("D2", "diode", (4, 6), (7, 6), "N_MID", "N_OUT", "D_2"),
        two("C1", "polar_capacitor", (7, 6), (7, 1), "N_OUT", "GND", "C_1", "470\\mathrm{uF}", label_side="right", value_side="left"),
        two("R1", "resistor", (10, 6), (10, 1), "N_OUT", "GND", "R_L", "1\\mathrm{k}\\Omega", label_side="right", value_side="left"),
        single("GND1", "ground", (7, 1), "GND"),
    ]
    ir["wires"] = [
        wire("W1", ("pin", "C1.1"), ("pin", "R1.1")),
        wire("W2", ("pin", "V1.1"), ("pin", "C1.2"), ("pin", "R1.2")),
        wire("W3", ("xy", [3, 2]), ("xy", [3, 5])),
        wire("W4", ("xy", [2, 3]), ("xy", [5, 3])),
    ]
    ir["junctions"] = [{"at": [7, 6]}, {"at": [7, 1]}]
    ir["crossings"] = [{"at": [3, 3], "style": "plain"}]
    ir["regions"] = [{"name": "rectifier", "component_ids": ["V1", "D1", "D2"]},
                     {"name": "filter", "component_ids": ["C1", "R1", "GND1"]}]
    return ir


def zener(case_id):
    ir = ir_base(case_id, "Synthetic zener and LED rail", (10, 7))
    ir["nets"] = [net("VCC"), net("N_OUT"), net("GND")]
    ir["components"] = [
        single("VCC1", "vcc", (2, 6), "VCC", "+12\\mathrm{V}"),
        two("R1", "resistor", (2, 6), (2, 4), "VCC", "N_OUT", "R_1", "1\\mathrm{k}\\Omega"),
        two("DZ1", "zener", (4, 4), (4, 2), "N_OUT", "GND", "D_Z"),
        two("LED1", "led", (6, 4), (6, 2), "N_OUT", "GND", "LED_1"),
        two("C1", "polar_capacitor", (8, 4), (8, 2), "N_OUT", "GND", "C_1", "100\\mathrm{uF}"),
        single("GND1", "ground", (6, 2), "GND"),
    ]
    ir["wires"] = [wire("W1", ("pin", "R1.2"), ("pin", "DZ1.1"), ("pin", "LED1.1"), ("pin", "C1.1")),
                   wire("W2", ("pin", "DZ1.2"), ("pin", "LED1.2"), ("pin", "C1.2"))]
    ir["junctions"] = [{"at": [4, 4]}, {"at": [6, 4]}, {"at": [6, 2]}]
    ir["regions"] = [{"name": "regulator", "component_ids": ["VCC1", "R1", "DZ1", "LED1", "C1", "GND1"]}]
    return ir


def transistor_case(case_id, ctype):
    ir = ir_base(case_id, "Synthetic %s stage" % ctype, (11, 9))
    pin_names = ("B", "C", "E") if ctype in ("npn", "pnp") else ("G", "D", "S")
    nets = {pin_names[0]: "N_IN", pin_names[1]: "N_OUT", pin_names[2]: "GND"}
    ir["nets"] = [net("N_SRC"), net("N_IN"), net("N_OUT"), net("VCC"), net("GND")]
    cid = "Q1" if ctype in ("npn", "pnp") else "M1"
    ir["components"] = [
        multi(cid, ctype, (5, 4.5), nets, cid.replace("1", "_1")),
        two("R1", "resistor", (2, 4.5), (4, 4.5), "N_SRC", "N_IN", "R_G", "10\\mathrm{k}\\Omega"),
        two("R2", "resistor", (5, 7.5), (5, 6), "VCC", "N_OUT", "R_D", "2\\mathrm{k}\\Omega"),
        single("VCC1", "vcc", (5, 7.5), "VCC"),
        single("GND1", "ground", (5, 2.5), "GND"),
    ]
    ir["wires"] = [wire("W1", ("xy", [1, 4.5]), ("pin", "R1.1")),
                   wire("W2", ("pin", "R1.2"), ("pin", cid + "." + pin_names[0])),
                   wire("W3", ("pin", cid + "." + pin_names[1]), ("pin", "R2.2")),
                   wire("W4", ("pin", cid + "." + pin_names[2]), ("pin", "GND1.p"))]
    ir["terminals"] = [{"at": [1, 4.5], "style": "ocirc", "label": "in", "label_side": "left"}]
    ir["regions"] = [{"name": "stage", "component_ids": [cid, "R1", "R2", "VCC1", "GND1"]}]
    return ir


def opamp_case(case_id):
    ir = ir_base(case_id, "Synthetic op-amp stage", (12, 8))
    ir["nets"] = [net("N_IN"), net("N_FB"), net("N_OUT"), net("GND")]
    ir["components"] = [
        multi("U1", "opamp", (6, 4), {"inp": "GND", "inn": "N_FB", "out": "N_OUT"}, "U_1"),
        two("R1", "resistor", (1, 4.35), (4, 4.35), "N_IN", "N_FB", "R_1", "10\\mathrm{k}\\Omega"),
        two("R2", "resistor", (6.85, 5.5), (4, 5.5), "N_OUT", "N_FB", "R_F", "100\\mathrm{k}\\Omega"),
        single("GND1", "ground", (4.5, 3.65), "GND"),
    ]
    ir["wires"] = [wire("W1", ("xy", [0.5, 4.35]), ("pin", "R1.1")),
                   wire("W2", ("pin", "R1.2"), ("pin", "U1.inn")),
                   wire("W3", ("pin", "U1.out"), ("xy", [9, 4]), ("xy", [9, 5.5]), ("pin", "R2.1")),
                   wire("W4", ("pin", "R2.2"), ("xy", [4, 4.35])),
                   wire("W5", ("pin", "U1.inp"), ("xy", [4.5, 3.65]))]
    ir["junctions"] = [{"at": [4, 4.35]}]
    ir["terminals"] = [{"at": [0.5, 4.35], "style": "ocirc", "label": "in", "label_side": "left"},
                       {"at": [9, 4], "style": "ocirc", "label": "out", "label_side": "right"}]
    ir["regions"] = [{"name": "amplifier", "component_ids": ["U1", "R1", "R2", "GND1"]}]
    return ir


def transformer_case(case_id):
    ir = ir_base(case_id, "Synthetic transformer rectifier", (12, 9))
    ir["nets"] = [net("N_PRI1"), net("N_PRI2"), net("N_SEC1"), net("N_SEC2"), net("N_OUT"), net("GND")]
    ir["components"] = [
        multi("T1", "transformer", (5, 5), {"A1": "N_PRI1", "A2": "N_PRI2", "B1": "N_SEC1", "B2": "N_SEC2"}, "T_1", variant="core"),
        two("D1", "diode", (6.25, 5.75), (8.25, 5.75), "N_SEC1", "N_OUT", "D_1"),
        two("D2", "diode", (6.25, 4.25), (8.25, 4.25), "N_SEC2", "GND", "D_2"),
        two("C1", "polar_capacitor", (9, 5.75), (9, 4.25), "N_OUT", "GND", "C_1", "220\\mathrm{uF}"),
        single("GND1", "ground", (9, 4.25), "GND"),
    ]
    ir["wires"] = [wire("W1", ("xy", [2, 5.75]), ("pin", "T1.A1")),
                   wire("W2", ("xy", [2, 4.25]), ("pin", "T1.A2")),
                   wire("W3", ("pin", "T1.B1"), ("pin", "D1.1")),
                   wire("W4", ("pin", "T1.B2"), ("pin", "D2.1")),
                   wire("W5", ("pin", "D1.2"), ("pin", "C1.1")),
                   wire("W6", ("pin", "D2.2"), ("pin", "C1.2"))]
    ir["terminals"] = [
        {"at": [2, 5.75], "style": "ocirc", "label": "pri1", "label_side": "left"},
        {"at": [2, 4.25], "style": "ocirc", "label": "pri2", "label_side": "left"},
    ]
    ir["regions"] = [{"name": "transformer", "component_ids": ["T1"]},
                     {"name": "rectifier", "component_ids": ["D1", "D2", "C1", "GND1"]}]
    return ir


def spdt_case(case_id):
    ir = ir_base(case_id, "Synthetic SPDT selector", (10, 7))
    ir["nets"] = [net("N_IN"), net("N_A"), net("N_B"), net("GND")]
    ir["components"] = [
        multi("S1", "spdt", (5, 4), {"in": "N_IN", "out1": "N_A", "out2": "N_B"}, "S_1"),
        two("R1", "resistor", (6.5, 5.5), (8.5, 5.5), "N_A", "GND", "R_A", "1\\mathrm{k}\\Omega"),
        two("R2", "resistor", (6.5, 2.5), (8.5, 2.5), "N_B", "GND", "R_B", "2\\mathrm{k}\\Omega"),
        single("GND1", "ground", (8.5, 4), "GND"),
    ]
    ir["wires"] = [wire("W1", ("xy", [2, 4]), ("pin", "S1.in")),
                   wire("W2", ("pin", "S1.out1"), ("xy", [6, 4.225]), ("xy", [6, 5.5]), ("pin", "R1.1")),
                   wire("W3", ("pin", "S1.out2"), ("xy", [6, 3.775]), ("xy", [6, 2.5]), ("pin", "R2.1")),
                   wire("W4", ("pin", "R1.2"), ("pin", "GND1.p")),
                   wire("W5", ("pin", "R2.2"), ("xy", [8.5, 4]))]
    ir["junctions"] = [{"at": [8.5, 4]}]
    ir["terminals"] = [{"at": [2, 4], "style": "ocirc", "label": "in", "label_side": "left"}]
    ir["regions"] = [{"name": "selector", "component_ids": ["S1", "R1", "R2", "GND1"]}]
    return ir


def annotated(case_id, kind):
    ir = divider(case_id)
    if kind in ("current_annotation", "mixed_annotations"):
        ir["annotations"].append({"id": "A1", "kind": "current_direction", "target": {"wire": "W3"},
                                  "direction": "right", "marker_at": [6, 3.4], "label": "i_o", "label_at": [6, 3.8]})
    if kind in ("voltage_annotation", "mixed_annotations"):
        ir["annotations"].append({"id": "A2", "kind": "voltage_measurement", "label": "u_o",
                                  "positive_ref": {"net": "N_MID", "marker_at": [6.5, 3.3]},
                                  "negative_ref": {"net": "GND", "marker_at": [6.5, 1.3]},
                                  "label_at": [7, 2.3]})
    if kind in ("node_polarity", "mixed_annotations"):
        next_id = "A3" if ir["annotations"] else "A1"
        ir["annotations"].append({"id": next_id, "kind": "node_polarity", "target": {"net": "N_MID"},
                                  "polarity": "positive", "marker_at": [5.5, 3.35]})
    if kind == "mixed_annotations":
        ir["wires"].extend([wire("W8", ("xy", [6, 0.5]), ("xy", [6, 2.5])),
                            wire("W9", ("xy", [5.5, 2]), ("xy", [7.5, 2]))])
        ir["crossings"] = [{"at": [6, 2], "style": "plain"}]
    return ir


def build_ir(case_id, family):
    if family == "divider": return divider(case_id)
    if family == "rectifier": return rectifier(case_id)
    if family == "zener": return zener(case_id)
    if family == "bjt": return transistor_case(case_id, "npn")
    if family == "mos": return transistor_case(case_id, "nmos")
    if family == "opamp": return opamp_case(case_id)
    if family == "transformer": return transformer_case(case_id)
    if family == "spdt": return spdt_case(case_id)
    return annotated(case_id, family)


def run(command, cwd, allowed=(0,)):
    proc = subprocess.run(command, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode not in allowed:
        raise RuntimeError("command failed: %s\n%s\n%s" % (command, proc.stdout, proc.stderr))


def resampling_filters():
    resampling = getattr(Image, "Resampling", Image)
    return resampling.LANCZOS, resampling.BICUBIC


def image_pixel_sha256(path):
    image = Image.open(str(path)).convert("RGB")
    header = ("RGB\0%dx%d\0" % image.size).encode("ascii")
    return hashlib.sha256(header + image.tobytes()).hexdigest()


def apply_variant(source, output, variant):
    image = Image.open(str(source)).convert("RGB")
    lanczos, bicubic = resampling_filters()
    if variant == "scale":
        image = image.resize((image.width * 2, image.height * 2), lanczos)
    elif variant == "jpeg_compression":
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as handle:
            temp = Path(handle.name)
        try:
            image.save(str(temp), quality=28, subsampling=2)
            image = Image.open(str(temp)).convert("RGB")
        finally:
            temp.unlink(missing_ok=True)
    elif variant == "mild_blur":
        image = image.filter(ImageFilter.GaussianBlur(radius=0.8))
    elif variant == "grayscale":
        image = image.convert("L").convert("RGB")
    elif variant == "paper_tint":
        gray = image.convert("L")
        image = Image.merge("RGB", (gray.point(lambda p: min(255, int(p * 1.00 + 8))),
                                     gray.point(lambda p: min(255, int(p * 0.97 + 14))),
                                     gray.point(lambda p: min(255, int(p * 0.88 + 24)))))
    elif variant == "line_width":
        image = image.filter(ImageFilter.MinFilter(3))
    elif variant == "small_rotation":
        image = image.rotate(1.2, resample=bicubic, expand=True, fillcolor="white")
    elif variant == "label_displacement":
        box = (
            int(round(image.width * 0.395)),
            int(round(image.height * 0.16)),
            int(round(image.width * 0.49)),
            int(round(image.height * 0.32)),
        )
        shifted = image.crop(box)
        image.paste("white", box)
        image.paste(shifted, (box[0] + max(4, int(round(image.width * 0.04))), box[1]))
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(str(output), format="PNG", optimize=True)


def generate(out, dpi):
    ir_dir = out / "synthetic_ir"
    image_dir = out / "synthetic_images"
    ir_dir.mkdir(parents=True, exist_ok=True)
    image_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"version": "kirchhoff-eye-synthetic/1.0",
                "source_policy": "generated_from_public_ir_only", "cases": []}
    work = out / ".render-work"
    work.mkdir(exist_ok=True)
    try:
        for number, slug, family, variant, coverage in CASES:
            cid = number + "-" + slug
            ir_rel = "synthetic_ir/%s.json" % cid
            image_rel = "synthetic_images/%s.png" % cid
            ir = build_ir(cid, family)
            ir["meta"]["source_image"] = image_rel
            ir_path = out / ir_rel
            ir_path.write_text(json.dumps(ir, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            case_work = work / cid
            case_work.mkdir()
            tex = case_work / "circuit.tex"
            png = case_work / "circuit.png"
            run([sys.executable, str(SCRIPTS / "validate_ir.py"), str(ir_path), "--phase", "full", "--json"], ROOT)
            run([sys.executable, str(SCRIPTS / "ir2tikz.py"), str(ir_path), "-o", str(tex)], ROOT)
            run([sys.executable, str(SCRIPTS / "render.py"), str(tex), "-o", str(png), "--dpi", str(dpi)], ROOT)
            apply_variant(png, out / image_rel, variant)
            image_path = out / image_rel
            manifest["cases"].append({
                "id": cid, "family": family, "image_variant": variant,
                "coverage": coverage, "ir": ir_rel, "image": image_rel,
                "sha256": {
                    "ir": hashlib.sha256(ir_path.read_bytes()).hexdigest(),
                    "image_pixels": image_pixel_sha256(image_path),
                },
            })
        (out / "synthetic_manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description="generate deterministic public synthetic fixtures")
    parser.add_argument("--out", default=str(ROOT / "tests" / "fixtures"))
    parser.add_argument("--dpi", type=int, default=96)
    args = parser.parse_args(argv)
    try:
        manifest = generate(Path(args.out).resolve(), args.dpi)
    except (OSError, RuntimeError, ValueError) as exc:
        sys.stderr.write("ERROR: %s\n" % exc)
        return 3
    sys.stdout.write("OK: generated %d synthetic fixtures -> %s\n" %
                     (len(manifest["cases"]), Path(args.out).resolve()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
