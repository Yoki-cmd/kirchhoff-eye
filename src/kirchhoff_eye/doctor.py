"""Environment diagnostics for the deterministic Kirchhoff-eye backend."""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict


PACKAGE_ROOT = Path(__file__).resolve().parent
SOURCE_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = SOURCE_ROOT if (SOURCE_ROOT / "schemas").exists() else PACKAGE_ROOT

EXIT_OK = 0
EXIT_ENV = 3

RESOURCE_PATHS = {
    "schema": Path("schemas/ir.schema.json"),
    "label_schema": Path("schemas/label-positions.schema.json"),
    "catalog": Path("catalog/components.json"),
    "template": Path("templates/standalone_head.tex"),
    "anchors": Path("templates/anchors.json"),
    "config": Path("config.json"),
    "validate_script": Path("scripts/validate_ir.py"),
    "serializer_script": Path("scripts/ir2tikz.py"),
    "render_script": Path("scripts/render.py"),
}


def _tool(name: str) -> Dict[str, Any]:
    path = shutil.which(name)
    return {"available": path is not None, "path": path}


def _resource(relative: Path) -> Dict[str, Any]:
    path = PROJECT_ROOT / relative
    return {"available": path.is_file(), "path": str(path.resolve())}


def _compile_probe(engine: str) -> Dict[str, Any]:
    if not shutil.which(engine):
        return {"available": False, "ok": False, "detail": f"{engine} not found"}
    tex = (
        "\\documentclass[margin=2pt]{standalone}\n"
        "\\usepackage[american]{circuitikz}\n"
        "\\begin{document}\\begin{circuitikz}\n"
        "\\draw (0,0) to[R] (2,0);\n"
        "\\end{circuitikz}\\end{document}\n"
    )
    try:
        with tempfile.TemporaryDirectory(prefix="kirchhoff-eye-doctor-") as directory:
            root = Path(directory)
            source = root / "probe.tex"
            source.write_text(tex, encoding="utf-8")
            proc = subprocess.run(
                [engine, "-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error", source.name],
                cwd=root,
                capture_output=True,
                timeout=60,
            )
            pdf = root / "probe.pdf"
            ok = proc.returncode == 0 and pdf.is_file() and pdf.stat().st_size > 0
            return {
                "available": True,
                "ok": ok,
                "detail": "circuitikz probe compiled" if ok else "circuitikz probe failed",
            }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"available": True, "ok": False, "detail": str(exc)}


def _writable_output_probe() -> Dict[str, Any]:
    try:
        with tempfile.TemporaryDirectory(prefix="kirchhoff-eye-output-") as directory:
            probe = Path(directory) / "probe.txt"
            probe.write_text("ok", encoding="utf-8")
            ok = probe.read_text(encoding="utf-8") == "ok"
            return {"ok": ok, "path": str(Path(directory).resolve())}
    except OSError as exc:
        return {"ok": False, "path": None, "detail": str(exc)}


def diagnose() -> Dict[str, Any]:
    resources = {name: _resource(path) for name, path in RESOURCE_PATHS.items()}
    tools = {name: _tool(name) for name in ("pdflatex", "lualatex", "pdftoppm")}
    compile_probe = _compile_probe("pdflatex")
    output_probe = _writable_output_probe()
    ok = (
        all(item["available"] for item in resources.values())
        and tools["pdftoppm"]["available"]
        and compile_probe["ok"]
        and output_probe["ok"]
    )
    return {
        "status": "ok" if ok else "error",
        "python": {"version": sys.version.split()[0], "executable": sys.executable},
        "package": {"root": str(PACKAGE_ROOT), "imports": "ok"},
        "resources": resources,
        "tools": tools,
        "circuitikz_compile_probe": compile_probe,
        "writable_output": output_probe,
    }


def _print_text(report: Dict[str, Any]) -> None:
    print(f"Kirchhoff-eye doctor: {report['status']}")
    print(f"Python: {report['python']['version']} ({report['python']['executable']})")
    print("Package imports: ok")
    for name, item in report["resources"].items():
        print(f"Resource {name}: {'ok' if item['available'] else 'missing'} ({item['path']})")
    for name, item in report["tools"].items():
        print(f"Tool {name}: {item['path'] or 'missing'}")
    compile_probe = report["circuitikz_compile_probe"]
    print(f"Circuitikz compile probe: {'ok' if compile_probe['ok'] else 'failed'}")
    print(f"Writable output directory: {'ok' if report['writable_output']['ok'] else 'failed'}")


def run(json_output: bool = False) -> int:
    report = diagnose()
    if json_output:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        _print_text(report)
    return EXIT_OK if report["status"] == "ok" else EXIT_ENV
