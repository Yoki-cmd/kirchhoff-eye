# -*- coding: utf-8 -*-
"""Standalone audit CLI validates canonical IR and publishes atomically."""
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GOLDEN_A = ROOT / "tests" / "golden" / "A" / "ir.json"


def test_audit_cli_writes_report_and_optionally_prints_json(tmp_path, capsys):
    from kirchhoff_eye.cli import main

    output = tmp_path / "electrical-audit.json"
    rc = main(["audit", str(GOLDEN_A), "--out", str(output), "--json"])
    stdout = json.loads(capsys.readouterr().out)
    written = json.loads(output.read_text(encoding="utf-8"))

    assert rc == 0
    assert written == stdout
    assert written["version"] == "kirchhoff-electrical-audit/1.0"
    assert written["verdict"] == "pass"
    assert written["summary"]["recognized_motifs"] >= 1


def test_audit_cli_returns_zero_even_when_report_blocks(tmp_path):
    from kirchhoff_eye.cli import main

    ir = json.loads(GOLDEN_A.read_text(encoding="utf-8"))
    ir["components"].append({
        "id": "VCC1", "type": "vcc", "at": [6, 4],
        "pins": [{"name": "p", "net": "GND"}],
    })
    ir["components"].append({
        "id": "GND2", "type": "ground", "at": [6, -1],
        "pins": [{"name": "p", "net": "GND"}],
    })
    ir["wires"].append({
        "id": "W4", "points": [{"pin": "VCC1.p"}, {"xy": [6, 0]}, {"pin": "GND2.p"}],
    })
    ir["regions"][2]["component_ids"].extend(["VCC1", "GND2"])
    ir_path = tmp_path / "blocked.json"
    ir_path.write_text(json.dumps(ir), encoding="utf-8")
    output = tmp_path / "report.json"

    assert main(["audit", str(ir_path), "--out", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["verdict"] == "block"


def test_audit_cli_rejects_invalid_ir_without_partial_output(tmp_path):
    from kirchhoff_eye.cli import main

    invalid = tmp_path / "invalid.json"
    invalid.write_text("{}", encoding="utf-8")
    output = tmp_path / "report.json"
    output.write_text('{"old": true}', encoding="utf-8")

    assert main(["audit", str(invalid), "--out", str(output)]) == 2
    assert output.read_text(encoding="utf-8") == '{"old": true}'


def test_audit_cli_io_failure_returns_environment_error(tmp_path):
    from kirchhoff_eye.cli import main

    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")

    assert main(["audit", str(GOLDEN_A), "--out", str(blocker / "report.json")]) == 3


def test_pipeline_audit_wrapper_returns_report_without_rendering():
    from kirchhoff_eye.pipeline import audit

    report = audit(str(GOLDEN_A))

    assert report["candidate_ir_sha256"]
    assert report["verdict"] == "pass"


def test_audit_cli_parallel_publication_uses_unique_temp_files(tmp_path, monkeypatch):
    from kirchhoff_eye.cli import main

    output = tmp_path / "report.json"
    barrier = threading.Barrier(2)
    original_replace = Path.replace
    sources = []

    def synchronized_replace(source, target):
        if Path(target) == output and source.suffix == ".tmp":
            sources.append(Path(source))
            barrier.wait(timeout=5)
        return original_replace(source, target)

    monkeypatch.setattr(type(output), "replace", synchronized_replace)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(
            lambda _index: main(["audit", str(GOLDEN_A), "--out", str(output)]),
            range(2),
        ))

    assert results == [0, 0]
    assert len(set(sources)) == 2
    assert json.loads(output.read_text(encoding="utf-8"))["verdict"] == "pass"
    assert not list(tmp_path.glob("*.tmp"))
