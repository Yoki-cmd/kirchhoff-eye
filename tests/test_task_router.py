# -*- coding: utf-8 -*-
"""Agent-facing task routes converge on the canonical IR pipeline."""
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
GOLDEN_A = ROOT / "tests" / "golden" / "A" / "ir.json"


@pytest.mark.parametrize("name", [
    "redraw-image",
    "draw-from-description",
    "draw-from-netlist",
    "edit-ir",
    "review",
    "repair",
    "render",
    "approve",
])
def test_task_route_help_is_available(name, capsys):
    from kirchhoff_eye.cli import main

    with pytest.raises(SystemExit) as exc:
        main(["task", name, "--help"])
    assert exc.value.code == 0
    assert "usage:" in capsys.readouterr().out.lower()


def test_draw_from_description_records_provenance_and_builds_canonical_ir(tmp_path):
    from kirchhoff_eye.cli import main

    description = tmp_path / "description.txt"
    description.write_text("画一个带旁路电容的分压器", encoding="utf-8")
    out = tmp_path / "job"

    assert main([
        "task", "draw-from-description", str(description), str(GOLDEN_A),
        "--out", str(out), "--dpi", "72",
    ]) == 0
    state = json.loads((out / "review.json").read_text(encoding="utf-8"))
    assert state["status"] == "valid"
    assert state["task"]["kind"] == "draw-from-description"
    assert (out / "description.txt").read_text(encoding="utf-8") == "画一个带旁路电容的分压器"
    assert state["artifacts"]["task_input"] == str((out / "description.txt").resolve())
    assert (out / "circuit.ir.json").read_bytes() == GOLDEN_A.read_bytes()


def test_netlist_and_edit_routes_copy_agent_evidence_and_dispatch(tmp_path, monkeypatch):
    import kirchhoff_eye.cli as cli

    calls = []

    def fake_build(ir_file, out_dir, **kwargs):
        calls.append((ir_file, out_dir, kwargs))
        return 0

    monkeypatch.setattr(cli, "build", fake_build)
    netlist = tmp_path / "input.cir"
    request = tmp_path / "edit.txt"
    netlist.write_text("R1 in out 1k", encoding="utf-8")
    request.write_text("把 R1 移到右侧", encoding="utf-8")

    assert cli.main([
        "task", "draw-from-netlist", str(netlist), str(GOLDEN_A), "--out", str(tmp_path / "net"),
    ]) == 0
    assert cli.main([
        "task", "edit-ir", str(request), str(GOLDEN_A), "--out", str(tmp_path / "edit"),
    ]) == 0
    assert calls[0][2]["task_kind"] == "draw-from-netlist"
    assert calls[0][2]["task_input"] == (str(netlist), "netlist.txt")
    assert calls[1][2]["task_kind"] == "edit-ir"
    assert calls[1][2]["task_input"] == (str(request), "edit-request.txt")


def test_review_and_repair_schemas_are_packaged_contracts():
    review_schema = ROOT / "schemas" / "review.schema.json"
    patches_schema = ROOT / "schemas" / "patch-operations.schema.json"
    state_schema = ROOT / "schemas" / "review-state.schema.json"
    assert review_schema.is_file()
    assert patches_schema.is_file()
    assert state_schema.is_file()
    assert json.loads(review_schema.read_text(encoding="utf-8"))["title"] == "kirchhoff-round-review/1.0"
    assert json.loads(patches_schema.read_text(encoding="utf-8"))["title"] == "kirchhoff-patch-operations/1.0"
    assert json.loads(state_schema.read_text(encoding="utf-8"))["title"] == "kirchhoff-review-state/1.0"


def test_reusing_output_directory_removes_previous_task_input_evidence(tmp_path):
    from kirchhoff_eye.cli import main

    description = tmp_path / "description.txt"
    description.write_text("画一个分压器", encoding="utf-8")
    out = tmp_path / "job"
    assert main([
        "task", "draw-from-description", str(description), str(GOLDEN_A),
        "--out", str(out), "--dpi", "72",
    ]) == 0
    assert (out / "description.txt").is_file()

    assert main(["task", "render", str(GOLDEN_A), "--out", str(out), "--dpi", "72"]) == 0
    assert not (out / "description.txt").exists()
    assert not (out / "netlist.txt").exists()
    assert not (out / "edit-request.txt").exists()