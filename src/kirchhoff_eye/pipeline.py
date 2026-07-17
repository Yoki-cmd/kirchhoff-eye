"""Deterministic IR-to-delivery build pipeline."""

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple


PACKAGE_ROOT = Path(__file__).resolve().parent
SOURCE_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = SOURCE_ROOT if (SOURCE_ROOT / "scripts" / "validate_ir.py").exists() else PACKAGE_ROOT
SCRIPTS_DIR = PROJECT_ROOT / "scripts"

EXIT_OK = 0
EXIT_NEEDS_HUMAN = 1
EXIT_ERROR = 2
EXIT_ENV = 3

GENERATED_ARTIFACTS = (
    "source.png", "compare.png", "circuit.tex", "circuit.debug.tex",
    "circuit.png", "circuit.debug.png", "validation.json",
    "layout_report.json", "review.json", "DELIVERY.md",
)


def _clear_generated_artifacts(output: Path) -> None:
    for name in GENERATED_ARTIFACTS:
        path = output / name
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def _run(script: str, args: Sequence[str]) -> Tuple[int, str, str]:
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / script), *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc.returncode, proc.stdout, proc.stderr


def _write_json(path: Path, data: Dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _load_json_output(stdout: str, tool: str) -> Dict:
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{tool} returned invalid JSON: {exc}") from exc


def _artifact_paths(out_dir: Path, include_source: bool) -> Dict[str, str]:
    names = {
        "circuit_ir": "circuit.ir.json",
        "circuit_tex": "circuit.tex",
        "circuit_debug_tex": "circuit.debug.tex",
        "circuit_png": "circuit.png",
        "circuit_debug_png": "circuit.debug.png",
        "validation_json": "validation.json",
        "layout_report_json": "layout_report.json",
        "review_json": "review.json",
        "delivery_md": "DELIVERY.md",
    }
    if include_source:
        names["source_png"] = "source.png"
        names["compare_png"] = "compare.png"
    return {key: str((out_dir / name).resolve()) for key, name in names.items()}


def _write_delivery(path: Path, status: str, artifacts: Dict[str, str]) -> None:
    lines = [
        "# Kirchhoff-eye Delivery",
        "",
        f"- Status: **{status}**",
        "",
        "## Artifacts",
        "",
    ]
    lines.extend(f"- `{name}`: `{artifact}`" for name, artifact in artifacts.items())
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build(
    ir_file: str,
    out_dir: str,
    source: Optional[str] = None,
    dpi: int = 300,
) -> int:
    try:
        return _build(ir_file, out_dir, source=source, dpi=dpi)
    except (OSError, RuntimeError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        sys.stderr.write(f"ERROR: build environment failure: {exc}\n")
        return EXIT_ENV


def _build(
    ir_file: str,
    out_dir: str,
    source: Optional[str] = None,
    dpi: int = 300,
) -> int:
    source_ir = Path(ir_file).resolve()
    output = Path(out_dir).resolve()
    target_ir = output / "circuit.ir.json"

    try:
        output.mkdir(parents=True, exist_ok=True)
        _clear_generated_artifacts(output)
        shutil.copy2(source_ir, target_ir)
        if source is not None:
            shutil.copy2(Path(source).resolve(), output / "source.png")
    except OSError as exc:
        sys.stderr.write(f"ERROR: unable to prepare inputs: {exc}\n")
        return EXIT_ENV

    rc, stdout, stderr = _run(
        "validate_ir.py", [str(target_ir), "--phase", "full", "--json"]
    )
    if rc == EXIT_ENV:
        sys.stderr.write(stderr or stdout)
        return EXIT_ENV
    try:
        validation = _load_json_output(stdout, "validate_ir.py")
    except RuntimeError as exc:
        sys.stderr.write(f"ERROR: {exc}\n")
        return EXIT_ENV
    _write_json(output / "validation.json", validation)
    if rc == EXIT_ERROR:
        return EXIT_ERROR

    tex = output / "circuit.tex"
    rc, stdout, stderr = _run("ir2tikz.py", [str(target_ir), "-o", str(tex)])
    if rc != EXIT_OK:
        sys.stderr.write(stderr or stdout)
        return EXIT_ENV if rc == EXIT_ENV else EXIT_ERROR

    png = output / "circuit.png"
    rc, stdout, stderr = _run(
        "render.py", [str(tex), "-o", str(png), "--dpi", str(dpi)]
    )
    if rc != EXIT_OK:
        sys.stderr.write(stderr or stdout)
        return EXIT_ENV if rc == EXIT_ENV else EXIT_ERROR

    rc, stdout, stderr = _run(
        "ir_fix_and_render.py", [str(target_ir), "--layout-check", "--json"]
    )
    source_layout = target_ir.with_suffix(".layout_report.json")
    if source_layout.exists():
        source_layout.replace(output / "layout_report.json")
    else:
        sys.stderr.write(stderr or stdout or "ERROR: layout report was not generated\n")
        return EXIT_ENV
    layout = json.loads((output / "layout_report.json").read_text(encoding="utf-8"))
    if rc == EXIT_ERROR:
        return EXIT_ERROR
    if rc not in (EXIT_OK, EXIT_NEEDS_HUMAN):
        return EXIT_ENV

    if source is not None:
        rc, stdout, stderr = _run(
            "compare.py",
            [str(output / "source.png"), str(png), "-o", str(output / "compare.png")],
        )
        if rc != EXIT_OK:
            sys.stderr.write(stderr or stdout)
            return EXIT_ENV

    status = "needs_human" if validation["status"] == "warn" or layout["status"] == "warn" else "ok"
    artifacts = _artifact_paths(output, include_source=source is not None)
    review = {
        "status": status,
        "validation_status": validation["status"],
        "layout_status": layout["status"],
        "artifacts": artifacts,
    }
    _write_json(output / "review.json", review)
    _write_delivery(output / "DELIVERY.md", status, artifacts)
    return EXIT_NEEDS_HUMAN if status == "needs_human" else EXIT_OK
