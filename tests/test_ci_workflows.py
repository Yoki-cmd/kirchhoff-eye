# -*- coding: utf-8 -*-
"""GitHub Actions must reproduce the public Python and TeX verification gates."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
PYTHON_WORKFLOW = WORKFLOWS / "python.yml"
TEX_WORKFLOW = WORKFLOWS / "tex.yml"


def workflow_text(path):
    assert path.exists(), f"missing workflow: {path.relative_to(ROOT)}"
    return path.read_text(encoding="utf-8")


def test_workflows_run_on_main_pull_requests_and_manual_dispatch():
    for path in (PYTHON_WORKFLOW, TEX_WORKFLOW):
        text = workflow_text(path)
        assert "push:" in text and "branches: [main]" in text
        assert "pull_request:" in text
        assert "workflow_dispatch:" in text
        assert "permissions:\n  contents: read" in text


def test_python_workflow_runs_the_public_matrix_and_verification_gate():
    text = workflow_text(PYTHON_WORKFLOW)

    assert 'python-version: ["3.9", "3.11", "3.12"]' in text
    for command in (
        'python -m pip install -e ".[dev]"',
        'python -m pytest tests -q -m "not tex and not synthetic"',
        "python -m compileall src scripts tests",
        "git diff --check",
    ):
        assert command in text
    assert "texlive-latex-base" not in text
    assert "if: matrix.python-version == '3.9'" in text
    assert 'python -m pip install "Pillow==9.0.0"' in text


def test_tex_workflow_exercises_compile_render_label_and_pipeline_paths():
    text = workflow_text(TEX_WORKFLOW)

    for package in (
        "texlive-latex-base",
        "texlive-latex-extra",
        "texlive-pictures",
        "texlive-luatex",
        "texlive-lang-chinese",
        "texlive-lang-japanese",
        "poppler-utils",
    ):
        assert package in text
    for node_id in (
        "tests/test_ir2tikz.py::test_golden_a_compiles",
        "tests/test_render_compare_crop.py::test_render_ok",
        "tests/test_render_compare_crop.py::test_render_also_renders_matching_debug_tex",
        "tests/test_ir2tikz.py::test_component_label_at_uses_exact_human_selected_coordinate",
        "tests/test_pipeline_cli.py::test_build_valid_ir_without_source_creates_complete_artifacts",
        "tests/test_review_workflow.py",
        "tests/test_synthetic_e2e.py",
        "tests/test_ir2tikz.py::test_cjk_text_compiles_with_lualatex",
    ):
        assert node_id in text
    assert "tests/test_synthetic_e2e.py -q -n auto" in text


def test_direct_rendering_regressions_are_marked_tex():
    perception = (ROOT / "tests" / "test_perception_pipeline.py").read_text(encoding="utf-8")
    concurrency = (ROOT / "tests" / "test_pipeline_concurrency.py").read_text(encoding="utf-8")
    workflow = workflow_text(TEX_WORKFLOW)

    assert "@pytest.mark.tex\ndef test_seed_ir_is_hash_bound" in perception
    assert "@pytest.mark.tex\ndef test_concurrent_reviews_serialize" in concurrency
    assert "tests/test_perception_pipeline.py::test_seed_ir_is_hash_bound" in workflow
    assert "tests/test_pipeline_concurrency.py::test_concurrent_reviews_serialize" in workflow


def test_workflows_use_stable_official_actions_and_no_machine_paths():
    windows_user_prefix = "C:" + "\\" + "Users" + "\\"
    windows_drive_prefix = "E:" + "\\"
    msys_interpreter_prefix = "/" + "e" + "/Miniconda"

    for path in (PYTHON_WORKFLOW, TEX_WORKFLOW):
        text = workflow_text(path)
        assert "actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5" in text
        assert "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065" in text
        assert "persist-credentials: false" in text
        assert windows_user_prefix not in text
        assert windows_drive_prefix not in text
        assert msys_interpreter_prefix not in text
