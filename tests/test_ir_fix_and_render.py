# -*- coding: utf-8 -*-
"""ir_fix_and_render 布局门禁契约。"""
import json
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ir_fix_and_render.py"


def test_layout_check_error_uses_shared_exit_code_2(tmp_path):
    tex = tmp_path / "diagonal.tex"
    tex.write_text(r"\draw (0,0) -- (1,1);" + "\n", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), str(tex), "--layout-check", "--json"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
    assert proc.returncode == 2
    report = tex.with_suffix(".layout_report.json").read_text(encoding="utf-8")
    assert '"code": "E004"' in report
    assert '"path": "/tex/wires/0/segments/0"' in report


def test_layout_check_clean_exit_0(tmp_path):
    tex = tmp_path / "orthogonal.tex"
    tex.write_text(r"\draw (0,0) -- (1,0) -- (1,1);" + "\n", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), str(tex), "--layout-check"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
    assert proc.returncode == 0


def test_layout_check_ir_uses_explicit_pin_references(tmp_path, golden_b):
    ir_path = tmp_path / "ir.json"
    ir_path.write_text(json.dumps(golden_b, ensure_ascii=False), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), str(ir_path), "--layout-check", "--json"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
    assert proc.returncode == 0
    report_path = ir_path.with_suffix(".layout_report.json")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["errors"] == 0
    assert not any(f.get("rule") == "铁律五·引脚未接" for f in report["findings"])


def test_layout_check_ir_propagates_non_e004_geometry_errors(tmp_path, golden_b):
    golden_b["junctions"].append({"at": [6.5, 7.5]})
    ir_path = tmp_path / "ir.json"
    ir_path.write_text(json.dumps(golden_b, ensure_ascii=False), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), str(ir_path), "--layout-check", "--json"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
    assert proc.returncode == 2
    report = json.loads(ir_path.with_suffix(".layout_report.json").read_text(encoding="utf-8"))
    assert any(f["code"] == "E013" for f in report["findings"])


def test_layout_report_from_validated_ir_does_not_reload_document(golden_b, monkeypatch):
    import ir_fix_and_render
    import validate_ir

    validated = validate_ir.validate_document(golden_b, phase="full")
    monkeypatch.setattr(ir_fix_and_render.irlib, "load_json", lambda *_a, **_k: (_ for _ in ()).throw(
        AssertionError("validated layout should not reload IR")
    ))

    report = ir_fix_and_render.layout_report_from_validated(validated)

    assert report["status"] == "ok"
    assert report["errors"] == 0
