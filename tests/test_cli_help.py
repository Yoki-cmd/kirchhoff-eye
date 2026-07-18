# -*- coding: utf-8 -*-
"""Public entry points expose useful help and environment diagnostics."""
import json
from pathlib import Path

import pytest

from kirchhoff_eye.cli import main


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_SCRIPTS = [
    path for path in sorted((ROOT / "scripts").glob("*.py"))
    if path.name != "irlib.py"
]


def test_labels_requires_nested_subcommand():
    with pytest.raises(SystemExit) as exc:
        main(["labels"])

    assert exc.value.code == 2


def test_skill_and_package_versions_match():
    import re

    from kirchhoff_eye import __version__

    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert re.search(r"(?m)^\s*version:\s*" + re.escape(__version__) + r"\s*$", skill)


def test_doctor_help_is_available(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["doctor", "--help"])

    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "environment" in output.lower()
    assert "--json" in output


@pytest.mark.tex
def test_doctor_json_reports_all_required_checks(capsys):
    rc = main(["doctor", "--json"])
    report = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert report["status"] == "ok"
    assert report["python"]["version"]
    assert report["package"]["imports"] == "ok"
    assert all(item["available"] for item in report["resources"].values())
    assert report["tools"]["pdftoppm"]["available"]
    assert report["circuitikz_compile_probe"]["ok"]
    assert report["writable_output"]["ok"]


def test_doctor_compile_probe_disables_shell_escape(monkeypatch):
    import kirchhoff_eye.doctor as doctor

    seen = {}

    class Result:
        returncode = 1

    monkeypatch.setattr(doctor.shutil, "which", lambda _name: "available")

    def capture(cmd, **_kwargs):
        seen["cmd"] = cmd
        return Result()

    monkeypatch.setattr(doctor.subprocess, "run", capture)

    doctor._compile_probe("pdflatex")

    assert seen["cmd"].count("-no-shell-escape") == 1


def test_anchor_generator_disables_shell_escape(monkeypatch, tmp_path):
    import gen_anchor_table

    seen = {}

    class Result:
        returncode = 0

    def capture(cmd, **_kwargs):
        seen["cmd"] = cmd
        return Result()

    monkeypatch.setattr(gen_anchor_table.subprocess, "run", capture)

    assert gen_anchor_table.run_pdflatex(str(tmp_path), "anchor_gen.tex") == 0
    assert seen["cmd"].count("-no-shell-escape") == 1


def test_doctor_returns_environment_error_when_required_tool_is_missing(monkeypatch, capsys):
    import kirchhoff_eye.doctor as doctor

    monkeypatch.setattr(
        doctor,
        "_tool",
        lambda name: {"available": name != "pdftoppm", "path": None},
    )
    monkeypatch.setattr(
        doctor,
        "_compile_probe",
        lambda _engine: {"available": True, "ok": True, "detail": "ok"},
    )

    rc = main(["doctor", "--json"])
    report = json.loads(capsys.readouterr().out)

    assert rc == 3
    assert report["status"] == "error"
    assert not report["tools"]["pdftoppm"]["available"]


@pytest.mark.parametrize("script", PUBLIC_SCRIPTS, ids=lambda path: path.name)
def test_public_script_help_exits_zero(script):
    import subprocess
    import sys

    proc = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "usage:" in proc.stdout.lower()
