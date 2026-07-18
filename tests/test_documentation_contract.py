# -*- coding: utf-8 -*-
"""Public documentation must describe only files and capabilities that ship."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = ("README.md", "SKILL.md")
REPOSITORY_PATH = re.compile(
    r"`((?:scripts|references|templates|schemas|catalog)/[^`\n]*)`"
)
WINDOWS_ABSOLUTE_PATH = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z]:\\")
USER_HOME_PATH = re.compile(r"/(?:home|Users)/[^/\s]+")


def test_documented_repository_paths_exist():
    missing = []
    for document in DOCUMENTS:
        text = (ROOT / document).read_text(encoding="utf-8")
        for relative in REPOSITORY_PATH.findall(text):
            if not (ROOT / relative).exists():
                missing.append(f"{document}: {relative}")

    assert not missing, "documented repository paths do not exist:\n" + "\n".join(missing)


def test_readme_does_not_advertise_unshipped_perception_modules():
    readme = (ROOT / "README.md").read_text(encoding="utf-8").lower()
    if not (ROOT / "scripts" / "perception").is_dir():
        assert "optional perception modules" not in readme
        assert "scripts/perception" not in readme


def test_readme_documents_fast_tex_synthetic_and_perf_gates():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert '-m "not tex and not synthetic"' in readme
    assert "-m tex" in readme
    assert "tests/test_synthetic_e2e.py -q -n auto" in readme
    assert "benchmark/perf/benchmark_pipeline.py" in readme


def test_performance_benchmark_uses_pipeline_timings():
    benchmark = ROOT / "benchmark" / "perf" / "benchmark_pipeline.py"
    text = benchmark.read_text(encoding="utf-8")
    assert "from kirchhoff_eye.pipeline import build" in text
    assert 'state["timings"]' in text


def test_public_contract_has_no_machine_specific_absolute_paths():
    offenders = []
    for relative in _tracked_text_files():
        text = (ROOT / relative).read_text(encoding="utf-8")
        for line_number, line in enumerate(text.splitlines(), start=1):
            if WINDOWS_ABSOLUTE_PATH.search(line) or USER_HOME_PATH.search(line):
                offenders.append(f"{relative}:{line_number}: {line.strip()}")

    assert not offenders, "machine-specific absolute paths found:\n" + "\n".join(offenders)


def _tracked_text_files():
    import subprocess

    result = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    for relative in result.stdout.splitlines():
        path = ROOT / relative
        try:
            path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        yield relative
