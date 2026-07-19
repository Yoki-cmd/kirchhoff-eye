# -*- coding: utf-8 -*-
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "benchmark" / "perception" / "run_benchmark.py"


def _module():
    spec = importlib.util.spec_from_file_location("perception_benchmark", RUNNER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def test_benchmark_keeps_synthetic_and_real_tables_separate(tmp_path):
    module = _module()
    output = tmp_path / "report.json"
    small_manifest = tmp_path / "synthetic.json"
    source_manifest = json.loads((ROOT / "tests" / "fixtures" / "synthetic_manifest.json").read_text(encoding="utf-8"))
    first = source_manifest["cases"][0]
    first["image"] = str((ROOT / "tests" / "fixtures" / first["image"]).resolve())
    small_manifest.write_text(json.dumps({"cases": [first]}), encoding="utf-8")
    real_manifest = tmp_path / "real.json"
    real_manifest.write_text('{"cases": []}', encoding="utf-8")

    assert module.main([
        "--synthetic-manifest", str(small_manifest),
        "--real-manifest", str(real_manifest),
        "--output", str(output),
    ]) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["synthetic"]["summary"]["case_count"] == 2
    assert report["real_image"]["summary"]["case_count"] == 0
    assert "not measured" in report["disclaimer"]
    assert report["synthetic"]["summary"]["refusal_correct"] == 1


def test_public_real_manifest_has_ten_distributable_software_export_rows():
    manifest_path = ROOT / "benchmark" / "perception" / "real_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert len(manifest["cases"]) >= 10
    for case in manifest["cases"]:
        assert (manifest_path.parent / case["image"]).resolve().is_file()
        assert case["license"]
        assert "failure_notes" in case
