# -*- coding: utf-8 -*-
"""The project installs as a standard src-layout Python package."""
from pathlib import Path
import subprocess
import sys

import pytest

try:
    import tomllib
except ImportError:  # Python 3.9-3.10
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[1]


def _pyproject():
    with (ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)


def test_pyproject_declares_package_metadata_and_console_script():
    project = _pyproject()["project"]

    assert project["name"] == "kirchhoff-eye"
    assert project["version"] == "0.2.0"
    assert project["requires-python"] == ">=3.9"
    assert {item.split(">=", 1)[0] for item in project["dependencies"]} == {
        "Pillow",
        "jsonschema",
    }
    assert project["scripts"]["kirchhoff-eye"] == "kirchhoff_eye.cli:main"


def test_package_imports_without_test_side_path_mutation():
    import kirchhoff_eye

    assert kirchhoff_eye.__version__ == "0.2.0"
    assert Path(kirchhoff_eye.__file__).resolve().is_relative_to(ROOT / "src")


def test_module_help_exits_successfully():
    proc = subprocess.run(
        [sys.executable, "-m", "kirchhoff_eye", "--help"],
        cwd=ROOT / "src",
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert proc.returncode == 0, proc.stderr
    assert "Kirchhoff-eye" in proc.stdout
    assert "--version" in proc.stdout


def test_cli_main_without_arguments_prints_help(capsys):
    from kirchhoff_eye.cli import main

    assert main([]) == 0
    assert "Kirchhoff-eye" in capsys.readouterr().out


def test_cli_help_flag_exits_zero():
    from kirchhoff_eye.cli import main

    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0


def test_readme_documents_standard_install_and_cli():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert 'python -m pip install -e ".[dev]"' in readme
    assert "kirchhoff-eye --help" in readme


def test_packaging_artifacts_are_ignored():
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert {".venv/", "build/", "dist/", "*.egg-info/"} <= set(gitignore)


def test_wheel_bundles_deterministic_backend_and_runtime_data():
    wheel = _pyproject()["tool"]["hatch"]["build"]["targets"]["wheel"]

    assert wheel["packages"] == ["src/kirchhoff_eye"]
    assert wheel["force-include"] == {
        "catalog": "kirchhoff_eye/catalog",
        "config.json": "kirchhoff_eye/config.json",
        "references": "kirchhoff_eye/references",
        "schemas": "kirchhoff_eye/schemas",
        "scripts": "kirchhoff_eye/scripts",
        "templates": "kirchhoff_eye/templates",
    }
