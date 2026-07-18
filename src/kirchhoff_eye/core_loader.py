"""Load deterministic Core scripts under private module names.

The scripts remain directly executable CLIs, while the package avoids importing generic
names such as ``compare`` from a long-lived host process's ``sys.modules``.
"""
from importlib.util import module_from_spec, spec_from_file_location
import hashlib
from pathlib import Path
import sys
from types import ModuleType


CORE_NAMESPACE = "kirchhoff_eye._core"


def load_core_module(name: str, scripts_dir: Path) -> ModuleType:
    scripts_dir = scripts_dir.resolve()
    source_id = hashlib.sha256(str(scripts_dir).encode("utf-8")).hexdigest()[:16]
    private_name = f"{CORE_NAMESPACE}.{source_id}.{name}"
    existing = sys.modules.get(private_name)
    if existing is not None:
        return existing
    path = scripts_dir / f"{name}.py"
    spec = spec_from_file_location(private_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"unable to load Kirchhoff Core module: {path}")
    module = module_from_spec(spec)
    sys.modules[private_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(private_name, None)
        raise
    return module
