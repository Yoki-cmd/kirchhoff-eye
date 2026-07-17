# -*- coding: utf-8 -*-
"""Production build CLI orchestration."""
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GOLDEN_A = ROOT / "tests" / "golden" / "A" / "ir.json"


def test_build_valid_ir_without_source_creates_complete_artifacts(tmp_path):
    from kirchhoff_eye.cli import main

    out = tmp_path / "job"
    rc = main(["build", str(GOLDEN_A), "--out", str(out), "--dpi", "120"])

    assert rc == 0
    expected = {
        "circuit.ir.json",
        "circuit.tex",
        "circuit.debug.tex",
        "circuit.png",
        "circuit.debug.png",
        "validation.json",
        "layout_report.json",
        "review.json",
        "DELIVERY.md",
    }
    assert expected <= {path.name for path in out.iterdir()}
    assert (out / "circuit.png").stat().st_size > 0
    assert (out / "circuit.debug.png").stat().st_size > 0

    validation = json.loads((out / "validation.json").read_text(encoding="utf-8"))
    review = json.loads((out / "review.json").read_text(encoding="utf-8"))
    layout = json.loads((out / "layout_report.json").read_text(encoding="utf-8"))
    delivery = (out / "DELIVERY.md").read_text(encoding="utf-8")

    assert validation["status"] == "ok"
    assert layout["status"] == "ok"
    assert review["report_version"] == "kirchhoff-review/1.0"
    assert review["status"] == "valid"
    assert review["task"]["kind"] == "render"
    assert review["current_round"] == 1
    assert review["max_rounds"] == 3
    assert review["artifacts"]["circuit_png"] == str((out / "circuit.png").resolve())
    assert str((out / "circuit.ir.json").resolve()) in delivery
    assert "compare_png" not in review["artifacts"]
    assert "Status: **valid**" in delivery


def test_build_help_is_available(capsys):
    from kirchhoff_eye.cli import main

    try:
        main(["build", "--help"])
    except SystemExit as exc:
        assert exc.code == 0
    assert "--out" in capsys.readouterr().out


def test_build_with_source_copies_input_and_generates_comparison(tmp_path):
    from kirchhoff_eye.cli import main

    source = ROOT / "tests" / "golden" / "A" / "golden.png"
    out = tmp_path / "job"
    rc = main([
        "build",
        str(GOLDEN_A),
        "--source",
        str(source),
        "--out",
        str(out),
        "--dpi",
        "120",
    ])

    assert rc == 0
    assert (out / "source.png").read_bytes() == source.read_bytes()
    assert (out / "compare.png").stat().st_size > 0
    assert (out / "cmp_round1.png").stat().st_size > 0
    assert (out / "FEEDBACK.md").stat().st_size > 0

    review = json.loads((out / "review.json").read_text(encoding="utf-8"))
    delivery = (out / "DELIVERY.md").read_text(encoding="utf-8")
    assert review["status"] == "needs_review"
    assert review["task"]["kind"] == "redraw-image"
    assert review["ready_for_approval"] is False
    assert review["artifacts"]["source_png"] == str((out / "source.png").resolve())
    assert review["artifacts"]["compare_png"] == str((out / "cmp_round1.png").resolve())
    assert str((out / "cmp_round1.png").resolve()) in delivery
    assert "逐区核对结论" in delivery
    assert "等待审读" in delivery


def test_build_supports_chinese_and_space_paths(tmp_path):
    from kirchhoff_eye.cli import main

    case_dir = tmp_path / "含 空格 中文路径"
    case_dir.mkdir()
    ir_path = case_dir / "输入 电路.json"
    source = case_dir / "源 图.png"
    out = case_dir / "输出 目录"
    ir_path.write_bytes(GOLDEN_A.read_bytes())
    source.write_bytes((ROOT / "tests" / "golden" / "A" / "golden.png").read_bytes())

    rc = main([
        "build", str(ir_path), "--source", str(source),
        "--out", str(out), "--dpi", "72",
    ])

    assert rc == 0
    for name in (
        "circuit.png", "circuit.debug.png", "compare.png", "validation.json",
        "cmp_round1.png", "layout_report.json", "review.json", "DELIVERY.md",
        "FEEDBACK.md",
    ):
        assert (out / name).is_file() and (out / name).stat().st_size > 0


def test_build_nonblocking_warning_without_source_remains_valid(tmp_path):
    from kirchhoff_eye.cli import main

    warned = json.loads(GOLDEN_A.read_text(encoding="utf-8"))
    warned["regions"] = []
    warned_path = tmp_path / "warned.json"
    warned_path.write_text(json.dumps(warned), encoding="utf-8")
    out = tmp_path / "job"

    rc = main(["build", str(warned_path), "--out", str(out), "--dpi", "120"])

    assert rc == 0
    review = json.loads((out / "review.json").read_text(encoding="utf-8"))
    assert review["status"] == "valid"
    assert review["validation_status"] == "warn"
    assert review["reason_codes"] == []
    assert (out / "circuit.png").stat().st_size > 0


def test_build_missing_review_regions_with_source_needs_human(tmp_path):
    from kirchhoff_eye.cli import main

    warned = json.loads(GOLDEN_A.read_text(encoding="utf-8"))
    warned["regions"] = []
    warned_path = tmp_path / "warned.json"
    warned_path.write_text(json.dumps(warned), encoding="utf-8")
    source = ROOT / "tests" / "golden" / "A" / "golden.png"
    out = tmp_path / "job"

    assert main([
        "build", str(warned_path), "--source", str(source),
        "--out", str(out), "--dpi", "72",
    ]) == 0
    state = json.loads((out / "review.json").read_text(encoding="utf-8"))
    assert state["status"] == "needs_human"
    assert state["ready_for_approval"] is False
    assert "incomplete_review_regions" in state["reason_codes"]


def test_build_unknowns_warning_is_blocking_needs_human(tmp_path):
    from kirchhoff_eye.cli import main

    warned = json.loads(GOLDEN_A.read_text(encoding="utf-8"))
    warned["unknowns"] = [{
        "id": "UNK1",
        "at": [6, 4],
        "size": [1, 1],
        "pin_count": 0,
        "pins": [],
        "appearance": "unresolved symbol",
    }]
    warned_path = tmp_path / "warned.json"
    warned_path.write_text(json.dumps(warned), encoding="utf-8")
    out = tmp_path / "job"

    assert main(["build", str(warned_path), "--out", str(out), "--dpi", "72"]) == 0
    state = json.loads((out / "review.json").read_text(encoding="utf-8"))
    assert state["status"] == "needs_human"
    assert "blocking_unknown" in state["reason_codes"]


def test_build_invalid_ir_returns_canonical_error_and_stops(tmp_path):
    from kirchhoff_eye.cli import main

    invalid = tmp_path / "invalid.json"
    invalid.write_text("{}", encoding="utf-8")
    out = tmp_path / "job"

    rc = main(["build", str(invalid), "--out", str(out)])

    assert rc == 2
    validation = json.loads((out / "validation.json").read_text(encoding="utf-8"))
    assert validation["status"] == "error"
    assert not (out / "circuit.tex").exists()
    assert not (out / "review.json").exists()


def test_reusing_output_directory_removes_stale_artifacts(tmp_path):
    from kirchhoff_eye.cli import main

    out = tmp_path / "job"
    source = ROOT / "tests" / "golden" / "A" / "golden.png"
    assert main([
        "build", str(GOLDEN_A), "--source", str(source),
        "--out", str(out), "--dpi", "120",
    ]) == 0
    assert (out / "compare.png").exists()

    invalid = tmp_path / "invalid.json"
    invalid.write_text("{}", encoding="utf-8")
    assert main(["build", str(invalid), "--out", str(out)]) == 2

    assert (out / "validation.json").exists()
    for stale in (
        "source.png", "compare.png", "circuit.tex", "circuit.debug.tex",
        "circuit.png", "circuit.debug.png", "layout_report.json",
        "review.json", "DELIVERY.md", "FEEDBACK.md", "cmp_round1.png",
    ):
        assert not (out / stale).exists(), stale


def test_build_missing_input_returns_environment_error(tmp_path):
    from kirchhoff_eye.cli import main

    rc = main(["build", str(tmp_path / "missing.json"), "--out", str(tmp_path / "job")])

    assert rc == 3


def test_build_uncreatable_output_directory_returns_environment_error(tmp_path):
    from kirchhoff_eye.cli import main

    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")

    rc = main(["build", str(GOLDEN_A), "--out", str(blocker / "job")])

    assert rc == 3


def test_build_invalid_layout_report_returns_environment_error(tmp_path, monkeypatch):
    import kirchhoff_eye.pipeline as pipeline

    real_run = pipeline._run

    def corrupt_layout(script, args):
        rc, stdout, stderr = real_run(script, args)
        if script == "ir_fix_and_render.py":
            Path(args[0]).with_suffix(".layout_report.json").write_text(
                "not-json", encoding="utf-8")
        return rc, stdout, stderr

    monkeypatch.setattr(pipeline, "_run", corrupt_layout)

    assert pipeline.build(str(GOLDEN_A), str(tmp_path / "job"), dpi=72) == 3


def test_build_render_environment_failure_returns_environment_error(tmp_path, monkeypatch):
    import kirchhoff_eye.pipeline as pipeline

    real_run = pipeline._run

    def fail_render(script, args):
        if script == "render.py":
            return 3, "", "ERROR: renderer unavailable\n"
        return real_run(script, args)

    monkeypatch.setattr(pipeline, "_run", fail_render)

    rc = pipeline.build(str(GOLDEN_A), str(tmp_path / "job"), dpi=120)

    assert rc == 3


def test_build_render_generation_failure_returns_canonical_error(tmp_path, monkeypatch):
    import kirchhoff_eye.pipeline as pipeline

    real_run = pipeline._run

    def fail_render(script, args):
        if script == "render.py":
            return 2, "COMPILE FAIL\n", ""
        return real_run(script, args)

    monkeypatch.setattr(pipeline, "_run", fail_render)

    rc = pipeline.build(str(GOLDEN_A), str(tmp_path / "job"), dpi=120)

    assert rc == 2
