"""Deterministic canonical-IR build, review, repair, and approval pipeline."""

import hashlib
import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import jsonschema

from .core_loader import load_core_module
from .electrical.audit import audit_validated


PACKAGE_ROOT = Path(__file__).resolve().parent
SOURCE_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = SOURCE_ROOT if (SOURCE_ROOT / "scripts" / "validate_ir.py").exists() else PACKAGE_ROOT
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
SCHEMAS_DIR = PROJECT_ROOT / "schemas"
TEMPLATES_DIR = PROJECT_ROOT / "templates"
CONFIG_PATH = PROJECT_ROOT / "config.json"

core_irlib = load_core_module("irlib", SCRIPTS_DIR)
_previous_irlib = sys.modules.get("irlib")
_previous_validate = sys.modules.get("validate_ir")
try:
    sys.modules["irlib"] = core_irlib
    core_validate = load_core_module("validate_ir", SCRIPTS_DIR)
    sys.modules["validate_ir"] = core_validate
    core_ir2tikz = load_core_module("ir2tikz", SCRIPTS_DIR)
    core_layout = load_core_module("ir_fix_and_render", SCRIPTS_DIR)
    core_compare = load_core_module("compare", SCRIPTS_DIR)
finally:
    if _previous_validate is None:
        sys.modules.pop("validate_ir", None)
    else:
        sys.modules["validate_ir"] = _previous_validate
    if _previous_irlib is None:
        sys.modules.pop("irlib", None)
    else:
        sys.modules["irlib"] = _previous_irlib

EXIT_OK = 0
EXIT_NEEDS_HUMAN = 1
EXIT_ERROR = 2
EXIT_ENV = 3
REPORT_VERSION = "kirchhoff-review/1.0"
_THREAD_LOCK_GUARD = threading.Lock()
_THREAD_LOCKS: Dict[str, threading.RLock] = {}
_WINDOWS_WAIT_OBJECT_0 = 0
_WINDOWS_INFINITE = 0xFFFFFFFF

GENERATED_ARTIFACTS = (
    "source.png", "compare.png", "circuit.tex", "circuit.debug.tex",
    "circuit.png", "circuit.debug.png", "validation.json",
    "electrical-audit.json", "layout_report.json", "review.json", "DELIVERY.md", "FEEDBACK.md",
    "description.txt", "netlist.txt", "edit-request.txt",
)


def _clear_generated_artifacts(output: Path) -> None:
    for name in GENERATED_ARTIFACTS:
        path = output / name
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    for path in output.glob("cmp_round*.png"):
        path.unlink()
    shutil.rmtree(output / "rounds", ignore_errors=True)


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


def _stage_timer(timings: Dict[str, float], name: str):
    class StageTimer:
        def __enter__(self):
            self.started = time.perf_counter()
            return self

        def __exit__(self, _exc_type, _exc, _tb):
            timings[name] = time.perf_counter() - self.started

    return StageTimer()


def _validate_ir_in_process(ir: Any) -> Tuple[Any, Dict[str, Any]]:
    validated = core_validate.validate_document(ir, phase="full")
    report = json.loads(validated.report.to_json({"phase": "full"}))
    return validated, report


def audit(ir_file: str) -> Dict[str, Any]:
    """Validate one canonical IR and return its deterministic electrical audit."""
    document = _read_json(Path(ir_file).resolve())
    validated, _validation = _validate_ir_in_process(document)
    if validated.report.exit_code() == EXIT_ERROR:
        raise ValueError("canonical IR failed full validation")
    report = audit_validated(validated)
    _validate_document(report, "electrical-audit.schema.json")
    return report


def _serialize_in_process(validated: Any, output: Path) -> None:
    core_ir2tikz.serialize_validated(validated, output)


def _layout_in_process(validated: Any, ir_path: Path) -> Dict[str, Any]:
    return core_layout.layout_report_from_validated(validated, file_name=str(ir_path))


def _compare_in_process(source: Path, rendered: Path, output: Path) -> None:
    original_image = core_compare.load_rgb(str(source))
    rendered_image = core_compare.load_rgb(str(rendered))
    height = core_irlib.load_config().get("compare", {}).get("side_height_px", 1200)
    core_compare.make_side(original_image, rendered_image, height).save(str(output))


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", prefix=path.name + ".", suffix=".tmp",
        dir=str(path.parent), delete=False,
    )
    temp = Path(handle.name)
    try:
        with handle:
            handle.write(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    """Publish a JSON document with a unique same-directory temporary file."""
    _write_json(Path(path), data)


def _read_json(path: Path) -> Dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return data


def _canonical_json(data: Any) -> bytes:
    return json.dumps(
        data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def _document_hash(data: Any) -> str:
    return hashlib.sha256(_canonical_json(data)).hexdigest()


def _json_file_hash(path: Path) -> str:
    return _document_hash(_read_json(path))


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _resolve_pointer(document: Any, pointer: str) -> Any:
    current = document
    for raw in pointer.lstrip("/").split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            if not token.isdigit() or int(token) >= len(current):
                raise ValueError(f"IR path does not exist: {pointer}")
            current = current[int(token)]
        elif isinstance(current, dict) and token in current:
            current = current[token]
        else:
            raise ValueError(f"IR path does not exist: {pointer}")
    return current


def _changed_paths(before: Any, after: Any, path: str = "") -> List[str]:
    if type(before) is not type(after):
        return [path or "/"]
    if isinstance(before, dict):
        changed: List[str] = []
        for key in sorted(set(before) | set(after)):
            child = f"{path}/{key}"
            if key not in before or key not in after:
                changed.append(child)
            else:
                changed.extend(_changed_paths(before[key], after[key], child))
        return changed
    if isinstance(before, list):
        changed = []
        for index in range(max(len(before), len(after))):
            child = f"{path}/{index}"
            if index >= len(before) or index >= len(after):
                changed.append(child)
            else:
                changed.extend(_changed_paths(before[index], after[index], child))
        return changed
    return [] if before == after else [path or "/"]


def _try_pointer(document: Any, pointer: str) -> Tuple[bool, Any]:
    try:
        return True, _resolve_pointer(document, pointer)
    except ValueError:
        return False, None


def _pointer_parent(document: Any, pointer: str) -> Tuple[Any, str]:
    tokens = pointer.lstrip("/").split("/")
    token = tokens[-1].replace("~1", "/").replace("~0", "~")
    parent_pointer = "/" + "/".join(tokens[:-1]) if len(tokens) > 1 else ""
    return (_resolve_pointer(document, parent_pointer) if parent_pointer else document), token


def _declared_patch_change(
    before: Any, after: Any, pointer: str, operation: str,
) -> Tuple[bool, bool, Any, bool, Any]:
    before_exists, before_value = _try_pointer(before, pointer)
    after_exists, after_value = _try_pointer(after, pointer)
    if not operation.startswith(("ADD_", "REMOVE_")):
        return (
            after_exists and (not before_exists or before_value != after_value),
            before_exists, before_value, after_exists, after_value,
        )
    try:
        before_parent, token = _pointer_parent(before, pointer)
        after_parent, after_token = _pointer_parent(after, pointer)
    except ValueError:
        return False, before_exists, before_value, after_exists, after_value
    if token != after_token or not isinstance(before_parent, list) or not isinstance(after_parent, list):
        valid = (not before_exists and after_exists) if operation.startswith("ADD_") else (
            before_exists and not after_exists
        )
        return valid, before_exists, before_value, after_exists, after_value
    if not token.isdigit():
        return False, before_exists, before_value, after_exists, after_value
    index = int(token)
    if operation.startswith("ADD_"):
        valid = (
            len(after_parent) == len(before_parent) + 1
            and index < len(after_parent)
            and before_parent[:index] == after_parent[:index]
            and before_parent[index:] == after_parent[index + 1:]
        )
        return valid, False, None, valid, (after_parent[index] if valid else after_value)
    valid = (
        len(before_parent) == len(after_parent) + 1
        and index < len(before_parent)
        and before_parent[:index] == after_parent[:index]
        and before_parent[index + 1:] == after_parent[index:]
    )
    return valid, valid, (before_parent[index] if valid else before_value), False, None


def _path_declared(path: str, operation: Dict[str, Any]) -> bool:
    declared = operation["ir_path"]
    if path == declared or path.startswith(declared + "/"):
        return True
    if not operation["operation"].startswith(("ADD_", "REMOVE_")):
        return False
    declared_parts = declared.strip("/").split("/")
    path_parts = path.strip("/").split("/")
    if len(declared_parts) != 2 or len(path_parts) < 2 or declared_parts[0] != path_parts[0]:
        return False
    return (
        declared_parts[1].isdigit() and path_parts[1].isdigit()
        and int(path_parts[1]) >= int(declared_parts[1])
    )


def _reported_changed_paths(
    changed_paths: Sequence[str], operations: Sequence[Dict[str, Any]],
) -> List[str]:
    reported: List[str] = []
    for path in changed_paths:
        value = path
        for operation in operations:
            if operation["operation"].startswith(("ADD_", "REMOVE_")) and _path_declared(path, operation):
                value = operation["ir_path"]
                break
        if value not in reported:
            reported.append(value)
    return reported


PATCH_PATH_RULES = {
    "ADD_COMPONENT": r"^/components/[0-9]+$",
    "REMOVE_COMPONENT": r"^/components/[0-9]+$",
    "CHANGE_TYPE": r"^/components/[0-9]+/type$",
    "MOVE": r"^/(components|unknowns|texts)/[0-9]+/(at|from|to|label_at)$",
    "ROTATE": r"^/components/[0-9]+/rotate$",
    "MIRROR": r"^/components/[0-9]+/mirror$",
    "SET_VALUE": r"^/components/[0-9]+/value$",
    "SET_LABEL": r"^/components/[0-9]+/label$",
    "SET_LABEL_SIDE": r"^/components/[0-9]+/label_side$",
    "SET_LABEL_AT": r"^/components/[0-9]+/label_at$",
    "REWIRE": r"^/components/[0-9]+/(from|to|pins)$",
    "ADD_WIRE": r"^/wires/[0-9]+$",
    "REMOVE_WIRE": r"^/wires/[0-9]+$",
    "SET_WAYPOINTS": r"^/wires/[0-9]+/points$",
    "ADD_JUNCTION": r"^/junctions/[0-9]+$",
    "REMOVE_JUNCTION": r"^/junctions/[0-9]+$",
    "ADD_CROSSING": r"^/crossings/[0-9]+$",
    "MOVE_TEXT": r"^/texts/[0-9]+/at$",
    "SET_REGION": r"^/regions/[0-9]+/(name|component_ids)$",
}


def _validate_operation_path(operation: str, pointer: str) -> None:
    pattern = PATCH_PATH_RULES.get(operation)
    if pattern is None or re.fullmatch(pattern, pointer) is None:
        raise ValueError(f"patch operation {operation} is not valid for IR path {pointer}")


def _load_json_output(stdout: str, tool: str) -> Dict[str, Any]:
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{tool} returned invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"{tool} returned a non-object JSON document")
    return data


def _load_max_rounds() -> int:
    config = _read_json(CONFIG_PATH)
    value = config.get("max_rounds", 3)
    if not isinstance(value, int) or value < 1:
        raise RuntimeError("config max_rounds must be a positive integer")
    return value


def _artifact_paths(out_dir: Path, include_source: bool, round_number: int) -> Dict[str, str]:
    names = {
        "circuit_ir": "circuit.ir.json",
        "circuit_tex": "circuit.tex",
        "circuit_debug_tex": "circuit.debug.tex",
        "circuit_png": "circuit.png",
        "circuit_debug_png": "circuit.debug.png",
        "validation_json": "validation.json",
        "electrical_audit_json": "electrical-audit.json",
        "layout_report_json": "layout_report.json",
        "review_json": "review.json",
        "delivery_md": "DELIVERY.md",
        "feedback_md": "FEEDBACK.md",
    }
    if include_source:
        names["source_png"] = "source.png"
        names["compare_png"] = f"cmp_round{round_number}.png"
    return {key: str((out_dir / name).resolve()) for key, name in names.items()}


def _status_exit(status: str) -> int:
    if status not in ("valid", "needs_review", "needs_human", "approved"):
        raise ValueError(f"unknown workflow status: {status}")
    return EXIT_OK


def _append_reason(state: Dict[str, Any], code: str) -> None:
    if code not in state["reason_codes"]:
        state["reason_codes"].append(code)


def _patch_path_reason(rounds: Sequence[Dict[str, Any]]) -> Optional[str]:
    counts: Dict[str, int] = {}
    for item in rounds:
        paths = {
            operation.get("ir_path") for operation in item.get("applied_patches", [])
            if isinstance(operation.get("ir_path"), str)
        }
        for path in paths:
            counts[path] = counts.get(path, 0) + 1
            if counts[path] >= 3:
                return f"patch_path_frozen:{path}"
    return None


def _derive_initial_workflow_state(
    validation: Dict[str, Any], layout: Dict[str, Any], electrical_audit: Dict[str, Any],
    include_source: bool,
) -> Tuple[str, List[str]]:
    validation_warnings = [
        finding for finding in validation.get("findings", [])
        if finding.get("severity") == "W"
    ]
    layout_warnings = [
        finding for finding in layout.get("findings", [])
        if finding.get("severity") == "W"
    ]
    validation_codes = {finding.get("code") for finding in validation_warnings}
    layout_codes = {finding.get("code") for finding in layout_warnings}
    reasons: List[str] = []
    if "W108" in validation_codes:
        reasons.append("blocking_unknown")
    if "W103" in validation_codes | layout_codes:
        reasons.append("blocking_pose_warning")
    if any(
        finding.get("code") == "E003"
        and str(finding.get("path", "")).startswith(("/components/", "/wires/"))
        for finding in validation_warnings + layout_warnings
    ):
        reasons.append("blocking_alignment_warning")
    if any(code and code.startswith("BLOCKING_") for code in validation_codes | layout_codes):
        reasons.append("blocking_ambiguity")
    if electrical_audit.get("verdict") == "block":
        reasons.append("blocking_electrical_audit")
    if reasons:
        return "needs_human", reasons
    return ("needs_review" if include_source else "valid"), reasons


def _copy_feedback(output: Path) -> None:
    shutil.copy2(TEMPLATES_DIR / "FEEDBACK.md", output / "FEEDBACK.md")


def _task_record(kind: str, input_artifact: Optional[str] = None) -> Dict[str, Any]:
    task: Dict[str, Any] = {"kind": kind}
    if input_artifact is not None:
        task["input_artifact"] = input_artifact
    return task


def _write_delivery(output: Path, state: Dict[str, Any]) -> None:
    status = state["status"]
    current_round = state["current_round"]
    max_rounds = state["max_rounds"]
    task_kind = state["task"]["kind"]
    latest_round = state["rounds"][-1]
    artifacts = state["artifacts"]
    staged_audit_path = output / "electrical-audit.json"
    audit_path = staged_audit_path if staged_audit_path.is_file() else Path(
        artifacts["electrical_audit_json"]
    )
    electrical_audit = _read_json(audit_path)
    assessment = latest_round.get("electrical_assessment")
    lines = [
        "# Kirchhoff-eye Delivery",
        "",
        f"- Status: **{status}**",
        f"- Task: `{task_kind}`",
        f"- Round: **{current_round}/{max_rounds}**",
        f"- Validation: `{state['validation_status']}`",
        f"- Layout: `{state['layout_status']}`",
        "",
        "## 产物",
        "",
        "| 键 | 绝对路径 |",
        "|---|---|",
    ]
    lines.extend(f"| {name} | `{artifact}` |" for name, artifact in artifacts.items())
    coverage = electrical_audit["coverage"]
    lines.extend([
        "",
        "## Electrical plausibility",
        "",
        f"- Deterministic audit verdict: **{electrical_audit['verdict']}**",
        f"- Statement: {electrical_audit['summary']['statement']}",
        f"- Net graph coverage: `{coverage['net_graph']}`",
        f"- Known/missing/unparsed numeric values: "
        f"{coverage['known_numeric_values']}/{coverage['missing_numeric_values']}/"
        f"{coverage['unparsed_numeric_values']}",
        "- Limitations: " + ("; ".join(coverage["limitations"]) or "None recorded."),
        "",
        "### Findings",
        "",
        "| ID | Severity | Message | Components | Nets |",
        "|---|---|---|---|---|",
    ])
    if electrical_audit["findings"]:
        for finding in electrical_audit["findings"]:
            lines.append(
                f"| {finding['id']} | {finding['severity']} | {finding['message']} | "
                f"{', '.join(finding['component_ids']) or '-'} | "
                f"{', '.join(finding['net_names']) or '-'} |"
            )
    else:
        lines.append("| - | - | No findings. | - | - |")
    lines.extend([
        "",
        "### Recognized motifs",
        "",
    ])
    if electrical_audit["motifs"]:
        lines.extend(
            f"- `{motif['id']}` {motif['kind']}: {motif['evidence']}"
            for motif in electrical_audit["motifs"]
        )
    else:
        lines.append("- None recognized; motif absence is not an error.")
    lines.extend(["", "### AI electrical assessment", ""])
    if assessment is None:
        lines.append("- Pending for this source-backed round." if state.get("electrical_review_required")
                     else "- Not required for a source-less render.")
    else:
        lines.extend([
            f"- Verdict: **{assessment['verdict']}**",
            f"- Summary: {assessment['summary']}",
        ])
        actionable = [
            claim for claim in assessment["claims"]
            if claim["disposition"] in ("reinspect_source", "repair_ir", "needs_context")
        ]
        if actionable:
            lines.append("- Pending actions:")
            lines.extend(
                f"  - `{claim['id']}` {claim['disposition']}: {claim['rationale']}"
                for claim in actionable
            )
        else:
            lines.append("- Pending actions: none.")
    lines.extend(["", "## 逐区核对结论", "", "| 区 | 结论 |", "|---|---|"])
    if not state.get("review_required", False):
        lines.append("| N/A | 不适用：此任务没有 source 对比 |")
    elif not latest_round.get("reviewed"):
        for region in latest_round.get("regions", []):
            lines.append(f"| {region['name']} | 等待审读 |")
        if not latest_round.get("regions"):
            lines.append("| N/A | 等待审读 |")
    else:
        for region in latest_round.get("regions", []):
            conclusion = "无差异" if region["conclusion"] == "no_difference" else region["summary"]
            lines.append(f"| {region['name']} | {conclusion} |")
    lines.extend([
        "",
        "## 差异与 Patch 记录",
        "",
        "| 轮次 | 差异数 | 已应用 patch |",
        "|---:|---:|---:|",
    ])
    for item in state["rounds"]:
        lines.append(
            f"| {item['round']} | {len(item.get('differences', []))} | "
            f"{len(item.get('applied_patches', []))} |"
        )
    unresolved = latest_round.get("differences", [])
    lines.extend(["", "## 遗留问题", ""])
    if unresolved:
        lines.extend([
            "| # | 位置 | 类别 | 描述 | Patch | IR path |",
            "|---|---|---|---|---|---|",
        ])
        for diff in unresolved:
            lines.append(
                f"| {diff['id']} | {diff['location']} | {diff['category']} | "
                f"{diff['description']} | {diff['patch_operation']} | `{diff['ir_path']}` |"
            )
    elif status == "needs_human":
        reasons = ", ".join(state.get("reason_codes", [])) or "blocking_warning"
        lines.append(f"- 阻塞原因：`{reasons}`")
    else:
        lines.append("- 无。")
    lines.extend([
        "",
        "## 反馈方式",
        "",
        "见同目录 `FEEDBACK.md`。所有反馈先落到 `circuit.ir.json`，再通过 repair 生成下一轮。",
    ])
    if status == "needs_review" and state.get("ready_for_approval"):
        lines.extend(["", "> 当前逐区审读无差异；仍需显式执行 approve 才能进入 approved。"])
    output.joinpath("DELIVERY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _snapshot_round(output: Path, round_number: int) -> None:
    snapshot = output / "rounds" / f"round-{round_number:02d}"
    snapshot.mkdir(parents=True, exist_ok=True)
    for name in (
        "source.png", "circuit.ir.json", "circuit.tex", "circuit.debug.tex", "circuit.png",
        "circuit.debug.png", "validation.json", "electrical-audit.json", "layout_report.json",
        f"cmp_round{round_number}.png",
    ):
        source = output / name
        if source.exists():
            shutil.copy2(source, snapshot / name)


def _round_artifacts(output: Path, round_number: int, include_source: bool) -> Dict[str, str]:
    snapshot = output / "rounds" / f"round-{round_number:02d}"
    artifacts = {
        "circuit_ir": str((snapshot / "circuit.ir.json").resolve()),
        "circuit_png": str((snapshot / "circuit.png").resolve()),
        "circuit_debug_png": str((snapshot / "circuit.debug.png").resolve()),
        "electrical_audit_json": str((snapshot / "electrical-audit.json").resolve()),
    }
    if include_source:
        artifacts["compare_png"] = str((snapshot / f"cmp_round{round_number}.png").resolve())
    return artifacts


def _atomic_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=target.name + ".", suffix=".tmp", dir=str(target.parent)
    )
    os.close(fd)
    temp = Path(temp_name)
    try:
        shutil.copy2(source, temp)
        temp.replace(target)
    finally:
        temp.unlink(missing_ok=True)


def _thread_lock(output: Path) -> threading.RLock:
    key = os.path.normcase(str(output.resolve()))
    with _THREAD_LOCK_GUARD:
        lock = _THREAD_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _THREAD_LOCKS[key] = lock
        return lock


def _windows_mutex_name(output: Path) -> str:
    digest = hashlib.sha256(os.path.normcase(str(output.resolve())).encode("utf-8")).hexdigest()
    return "Local\\KirchhoffEye-" + digest


@contextmanager
def _windows_job_mutex(output: Path):
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.WaitForSingleObject.restype = ctypes.c_uint32
    kernel32.ReleaseMutex.argtypes = [ctypes.c_void_p]
    kernel32.ReleaseMutex.restype = ctypes.c_bool
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_bool
    handle = kernel32.CreateMutexW(None, False, _windows_mutex_name(output))
    if not handle:
        raise OSError(ctypes.get_last_error(), "CreateMutexW failed")
    acquired = False
    try:
        result = kernel32.WaitForSingleObject(handle, _WINDOWS_INFINITE)
        if result != _WINDOWS_WAIT_OBJECT_0:
            raise OSError(ctypes.get_last_error(), "WaitForSingleObject failed")
        acquired = True
        yield
    finally:
        if acquired and not kernel32.ReleaseMutex(handle):
            raise OSError(ctypes.get_last_error(), "ReleaseMutex failed")
        if not kernel32.CloseHandle(handle):
            raise OSError(ctypes.get_last_error(), "CloseHandle failed")


@contextmanager
def _job_lock(output: Path):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    lock = _thread_lock(output)
    with lock:
        if os.name == "nt":
            with _windows_job_mutex(output):
                yield
            return
        lock_path = output / ".kirchhoff-eye.lock"
        lock_path.touch(exist_ok=True)
        handle = lock_path.open("r+b")
        acquired = False
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            acquired = True
            yield
        finally:
            try:
                if acquired:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()


def _publish_stage(stage: Path, output: Path, round_number: int) -> None:
    relative_paths = [
        Path(name) for name in (
            "circuit.ir.json", "circuit.tex", "circuit.debug.tex", "circuit.png",
            "circuit.debug.png", "validation.json", "electrical-audit.json", "layout_report.json",
            f"cmp_round{round_number}.png", "compare.png", "FEEDBACK.md",
            "review.json", "DELIVERY.md",
        )
        if (stage / name).is_file()
    ]
    snapshot = stage / "rounds" / f"round-{round_number:02d}"
    if snapshot.is_dir():
        relative_paths.extend(path.relative_to(stage) for path in snapshot.rglob("*") if path.is_file())
    _publish_relative_paths(stage, output, relative_paths)


def _publish_relative_paths(stage: Path, output: Path, relative_paths: Sequence[Path]) -> None:
    backup = Path(tempfile.mkdtemp(prefix="kirchhoff-publish-", dir=str(output.parent)))
    existing = set()
    try:
        for relative in relative_paths:
            target = output / relative
            if target.is_file():
                existing.add(relative)
                _atomic_copy(target, backup / relative)
        for relative in relative_paths:
            _atomic_copy(stage / relative, output / relative)
    except Exception:
        for relative in relative_paths:
            target = output / relative
            saved = backup / relative
            if relative in existing:
                _atomic_copy(saved, target)
            else:
                target.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(backup, ignore_errors=True)


def _publish_state_and_delivery(output: Path, state: Dict[str, Any]) -> None:
    stage = Path(tempfile.mkdtemp(prefix="kirchhoff-state-", dir=str(output.parent)))
    try:
        relative_paths = [Path("review.json"), Path("DELIVERY.md")]
        latest = state["rounds"][-1]
        assessment = latest.get("electrical_assessment")
        if assessment is not None:
            assessment_relative = Path("rounds") / f"round-{state['current_round']:02d}" / \
                "electrical-assessment.json"
            (stage / assessment_relative).parent.mkdir(parents=True, exist_ok=True)
            _write_json(stage / assessment_relative, assessment)
            relative_paths.append(assessment_relative)
        _write_json(stage / "review.json", state)
        _write_delivery(stage, state)
        _publish_relative_paths(stage, output, relative_paths)
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def _validate_document(data: Dict[str, Any], schema_name: str) -> None:
    schema = _read_json(SCHEMAS_DIR / schema_name)
    try:
        jsonschema.Draft7Validator(schema).validate(data)
    except jsonschema.ValidationError as exc:
        location = "/" + "/".join(str(part) for part in exc.absolute_path)
        raise ValueError(f"{schema_name} invalid at {location or '/'}: {exc.message}") from exc


def _load_state(job_dir: str) -> Tuple[Path, Dict[str, Any]]:
    output = Path(job_dir).resolve()
    state_path = output / "review.json"
    if not state_path.is_file():
        raise OSError(f"missing review state: {state_path}")
    state = _read_json(state_path)
    _validate_document(state, "review-state.schema.json")
    if state["current_round"] != len(state["rounds"]):
        raise ValueError("review state current_round does not match round history")
    return output, state


def _verify_round_evidence(output: Path, state: Dict[str, Any]) -> Tuple[str, str, str, str]:
    round_number = state["current_round"]
    latest = state["rounds"][-1]
    snapshot = output / "rounds" / f"round-{round_number:02d}"
    live_ir_hash = _json_file_hash(output / "circuit.ir.json")
    source_hash = _file_hash(output / "source.png")
    comparison_hash = _file_hash(output / f"cmp_round{round_number}.png")
    electrical_audit_hash = _json_file_hash(output / "electrical-audit.json")
    expected = {
        "ir_sha256": live_ir_hash,
        "source_sha256": source_hash,
        "comparison_sha256": comparison_hash,
        "electrical_audit_sha256": electrical_audit_hash,
    }
    for key, actual in expected.items():
        if latest.get(key) != actual:
            raise ValueError(f"current round evidence hash mismatch: {key}")
    if _json_file_hash(snapshot / "circuit.ir.json") != live_ir_hash:
        raise ValueError("round snapshot IR differs from the live IR")
    if _file_hash(snapshot / "source.png") != source_hash:
        raise ValueError("round snapshot source differs from the live source")
    if _file_hash(snapshot / f"cmp_round{round_number}.png") != comparison_hash:
        raise ValueError("round snapshot comparison differs from the live comparison")
    if _json_file_hash(snapshot / "electrical-audit.json") != electrical_audit_hash:
        raise ValueError("round snapshot electrical audit differs from the live audit")
    return live_ir_hash, source_hash, comparison_hash, electrical_audit_hash


def _live_deterministic_reports(output: Path) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    ir_document = _read_json(output / "circuit.ir.json")
    validated, validation = _validate_ir_in_process(ir_document)
    if validated.report.exit_code() == EXIT_ERROR:
        raise ValueError("live circuit IR no longer passes full validation")
    layout = _layout_in_process(validated, output / "circuit.ir.json")
    if layout.get("errors"):
        raise ValueError("live circuit IR no longer passes layout validation")
    electrical_audit = audit_validated(validated)
    _validate_document(electrical_audit, "electrical-audit.schema.json")
    if _document_hash(electrical_audit) != _json_file_hash(output / "electrical-audit.json"):
        raise ValueError("live deterministic electrical audit differs from the persisted audit")
    return validation, layout, electrical_audit


def _validate_electrical_assessment(
    assessment: Dict[str, Any], audit_report: Dict[str, Any], latest: Dict[str, Any],
    differences: Sequence[Dict[str, Any]],
) -> Tuple[bool, bool]:
    _validate_document(assessment, "electrical-assessment.schema.json")
    if assessment["candidate_ir_sha256"] != latest["ir_sha256"]:
        raise ValueError("electrical assessment IR hash does not match the current round")
    if assessment["audit_sha256"] != latest["electrical_audit_sha256"]:
        raise ValueError("electrical assessment audit hash does not match the current round")
    all_findings = {
        finding["id"]: finding for finding in audit_report.get("findings", [])
    }
    warning_blockers = {
        finding["id"]: finding for finding in audit_report.get("findings", [])
        if finding.get("severity") in ("warning", "blocker")
    }
    claims = assessment.get("claims", [])
    claim_ids = [claim["id"] for claim in claims]
    if len(claim_ids) != len(set(claim_ids)):
        raise ValueError("electrical assessment claim IDs must be unique")
    referenced = [claim.get("audit_finding_id") for claim in claims if claim.get("audit_finding_id")]
    if any(finding_id not in all_findings for finding_id in referenced):
        raise ValueError("electrical assessment references an unknown audit finding")
    required_referenced = [finding_id for finding_id in referenced if finding_id in warning_blockers]
    if len(required_referenced) != len(set(required_referenced)):
        raise ValueError("each audit finding may be referenced by exactly one claim")
    if set(required_referenced) != set(warning_blockers):
        raise ValueError("each deterministic warning/blocker must have exactly one disposition claim")
    differences_by_id = {difference["id"]: difference for difference in differences}
    dispositions = {claim["disposition"] for claim in claims}
    for claim in claims:
        if claim["disposition"] == "repair_ir":
            difference = differences_by_id.get(claim.get("linked_difference_id"))
            if difference is None:
                raise ValueError("repair_ir claim must link an existing source-review difference")
            if difference["ir_path"] not in claim["ir_paths"]:
                raise ValueError("repair_ir claim and linked difference must share an IR path")
    verdict = assessment["verdict"]
    if verdict == "pass" and warning_blockers:
        raise ValueError("pass assessment cannot contain deterministic warning/blocker findings")
    if verdict == "pass" and dispositions - {"accept_as_plausible", "confirm_source_intended"}:
        raise ValueError("pass assessment cannot contain claims that require action")
    if verdict == "warn" and dispositions - {"accept_as_plausible", "confirm_source_intended"}:
        raise ValueError("warn assessment cannot hide repair, reinspect, or context actions")
    if verdict == "requires_repair" and "repair_ir" not in dispositions:
        raise ValueError("requires_repair assessment needs at least one repair_ir claim")
    if verdict == "needs_context" and "needs_context" not in dispositions:
        raise ValueError("needs_context assessment needs at least one needs_context claim")
    ready = verdict in ("pass", "warn") and not (
        dispositions & {"repair_ir", "reinspect_source", "needs_context"}
    )
    needs_human = verdict == "needs_context" or "reinspect_source" in dispositions
    return ready, needs_human


def _validate_patch_manifest(
    previous_ir: Dict[str, Any], candidate_ir: Dict[str, Any], state: Dict[str, Any], patch_doc: Dict[str, Any]
) -> Dict[str, Any]:
    by_id = {item["id"]: item for item in state["rounds"][-1]["differences"]}
    before_hash = _document_hash(previous_ir)
    after_hash = _document_hash(candidate_ir)
    if before_hash == after_hash:
        raise ValueError("repair candidate IR is unchanged")
    changed_paths = _changed_paths(previous_ir, candidate_ir)
    difference_ids = [operation["difference_id"] for operation in patch_doc["operations"]]
    if len(difference_ids) != len(set(difference_ids)):
        raise ValueError("a difference_id cannot be referenced more than once per repair round")
    for operation in patch_doc["operations"]:
        difference = by_id.get(operation["difference_id"])
        if difference is None:
            raise ValueError(f"unknown difference_id: {operation['difference_id']}")
        if operation["ir_path"] != difference["ir_path"]:
            raise ValueError("patch ir_path must match its unresolved difference")
        if operation["operation"] != difference["patch_operation"]:
            raise ValueError("patch operation must match its unresolved difference")
        _validate_operation_path(operation["operation"], operation["ir_path"])
        valid_shape, before_exists, before_value, after_exists, after_value = _declared_patch_change(
            previous_ir, candidate_ir, operation["ir_path"], operation["operation"]
        )
        if not valid_shape:
            raise ValueError(f"patch did not produce the declared change at {operation['ir_path']}")
        operation.update({
            "before_exists": before_exists,
            "after_exists": after_exists,
            "before": before_value,
            "after": after_value,
        })
    undeclared = [
        path for path in changed_paths
        if not any(_path_declared(path, operation) for operation in patch_doc["operations"])
    ]
    if undeclared:
        raise ValueError(f"candidate IR has undeclared changes: {undeclared}")
    return {
        "before_sha256": before_hash,
        "after_sha256": after_hash,
        "changed_paths": _reported_changed_paths(changed_paths, patch_doc["operations"]),
    }


def _load_regions(ir_path: Path, *, require_complete: bool = False) -> List[str]:
    ir = _read_json(ir_path)
    regions = ir.get("regions", [])
    names = [item["name"] for item in regions if isinstance(item, dict) and isinstance(item.get("name"), str)]
    if require_complete:
        if not names:
            raise ValueError("source-backed workflow requires at least one review region")
        if len(names) != len(set(names)):
            raise ValueError("IR region names must be unique")
        expected_ids = {
            item["id"] for collection in ("components", "unknowns")
            for item in ir.get(collection, []) if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        covered_ids = {
            component_id for region in regions if isinstance(region, dict)
            for component_id in region.get("component_ids", [])
        }
        missing = sorted(expected_ids - covered_ids)
        if missing:
            raise ValueError(f"review regions do not cover all components/unknowns: {missing}")
    return names


def _copy_task_input(
    output: Path,
    task_input: Optional[Tuple[str, str]],
) -> Optional[str]:
    if task_input is None:
        return None
    source_path, artifact_name = task_input
    target = output / artifact_name
    shutil.copy2(Path(source_path).resolve(), target)
    return str(target.resolve())


def build(
    ir_file: str,
    out_dir: str,
    source: Optional[str] = None,
    dpi: int = 300,
    task_kind: Optional[str] = None,
    task_input: Optional[Tuple[str, str]] = None,
    preserve_history: bool = False,
    patches_file: Optional[str] = None,
) -> int:
    output = Path(out_dir).resolve()
    try:
        with _job_lock(output):
            return _build(
                ir_file,
                str(output),
                source=source,
                dpi=dpi,
                task_kind=task_kind,
                task_input=task_input,
                preserve_history=preserve_history,
                patches_file=patches_file,
            )
    except (OSError, RuntimeError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        sys.stderr.write(f"ERROR: build environment failure: {exc}\n")
        return EXIT_ENV
    except (ValueError, jsonschema.ValidationError) as exc:
        sys.stderr.write(f"ERROR: canonical workflow input: {exc}\n")
        return EXIT_ERROR


def _build(
    ir_file: str,
    out_dir: str,
    source: Optional[str] = None,
    dpi: int = 300,
    task_kind: Optional[str] = None,
    task_input: Optional[Tuple[str, str]] = None,
    preserve_history: bool = False,
    patches_file: Optional[str] = None,
) -> int:
    build_started = time.perf_counter()
    source_ir = Path(ir_file).resolve()
    output = Path(out_dir).resolve()
    previous: Optional[Dict[str, Any]] = None
    max_rounds = _load_max_rounds()
    if preserve_history:
        output, previous = _load_state(str(output))
        max_rounds = previous["max_rounds"]
        if previous["current_round"] >= max_rounds:
            raise ValueError("max_rounds reached; no additional repair round is allowed")
    round_number = previous["current_round"] + 1 if previous else 1
    work_output = (
        Path(tempfile.mkdtemp(prefix=".next-round-", dir=str(output)))
        if preserve_history else output
    )
    work_ir = work_output / "circuit.ir.json"
    try:
        output.mkdir(parents=True, exist_ok=True)
        if not preserve_history:
            _clear_generated_artifacts(output)
        else:
            work_output.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_ir, work_ir)
        if source is not None:
            shutil.copy2(Path(source).resolve(), output / "source.png")
        elif preserve_history and not (output / "source.png").exists():
            raise OSError("repair requires the original source.png in the job directory")
        elif preserve_history:
            shutil.copy2(output / "source.png", work_output / "source.png")
        task_input_artifact = _copy_task_input(output, task_input)
    except OSError as exc:
        shutil.rmtree(work_output, ignore_errors=True) if preserve_history else None
        sys.stderr.write(f"ERROR: unable to prepare inputs: {exc}\n")
        return EXIT_ENV

    def abort(code: int, message: str = "") -> int:
        if preserve_history:
            shutil.rmtree(work_output, ignore_errors=True)
        if message:
            sys.stderr.write(message)
        return code

    timings: Dict[str, float] = {}
    try:
        ir_document = json.loads(work_ir.read_text(encoding="utf-8"))
        with _stage_timer(timings, "validation"):
            validated, validation = _validate_ir_in_process(ir_document)
        _write_json(work_output / "validation.json", validation)
    except (OSError, ValueError, jsonschema.ValidationError) as exc:
        return abort(EXIT_ENV, f"ERROR: validation failed: {exc}\n")
    if validated.report.exit_code() == EXIT_ERROR:
        return abort(EXIT_ERROR)

    try:
        with _stage_timer(timings, "electrical_audit"):
            electrical_audit = audit_validated(validated)
        _validate_document(electrical_audit, "electrical-audit.schema.json")
        _write_json(work_output / "electrical-audit.json", electrical_audit)
    except (OSError, ValueError, jsonschema.ValidationError) as exc:
        return abort(EXIT_ENV, f"ERROR: electrical audit failed: {exc}\n")

    tex = work_output / "circuit.tex"
    try:
        with _stage_timer(timings, "serialization"):
            _serialize_in_process(validated, tex)
    except (OSError, ValueError) as exc:
        return abort(EXIT_ENV, f"ERROR: serialization failed: {exc}\n")

    png = work_output / "circuit.png"
    with _stage_timer(timings, "render"):
        rc, stdout, stderr = _run(
            "render.py", [str(tex), "-o", str(png), "--dpi", str(dpi)]
        )
    if rc != EXIT_OK:
        return abort(EXIT_ENV if rc == EXIT_ENV else EXIT_ERROR, stderr or stdout)

    try:
        with _stage_timer(timings, "layout"):
            layout = _layout_in_process(validated, work_ir)
        _write_json(work_output / "layout_report.json", layout)
    except (OSError, ValueError) as exc:
        return abort(EXIT_ENV, f"ERROR: layout check failed: {exc}\n")
    if layout["errors"]:
        return abort(EXIT_ERROR)

    include_source = source is not None or (preserve_history and (output / "source.png").exists())
    if include_source:
        compare = work_output / f"cmp_round{round_number}.png"
        try:
            with _stage_timer(timings, "compare"):
                _compare_in_process(work_output / "source.png", png, compare)
        except (OSError, ValueError) as exc:
            return abort(EXIT_ENV, f"ERROR: compare failed: {exc}\n")

    if include_source:
        shutil.copy2(work_output / f"cmp_round{round_number}.png", work_output / "compare.png")

    target_ir = work_ir
    png = work_output / "circuit.png"
    status, reason_codes = _derive_initial_workflow_state(
        validation, layout, electrical_audit, include_source
    )
    if include_source:
        try:
            region_names = _load_regions(target_ir, require_complete=True)
        except ValueError:
            region_names = _load_regions(target_ir)
            if "incomplete_review_regions" not in reason_codes:
                reason_codes.append("incomplete_review_regions")
            status = "needs_human"
    else:
        region_names = []
    regions = (
        [{"name": name, "conclusion": "pending", "summary": "等待审读"}
         for name in region_names]
        if include_source else []
    )
    applied_patches: List[Dict[str, Any]] = []
    if patches_file is not None:
        patch_doc = _read_json(Path(patches_file).resolve())
        _validate_document(patch_doc, "patch-operations.schema.json")
        applied_patches = patch_doc["operations"]
    current_round = {
        "round": round_number,
        "reviewed": False,
        "regions": regions,
        "differences": [],
        "applied_patches": applied_patches,
        "artifacts": {},
        "ir_sha256": _json_file_hash(target_ir),
        "electrical_audit_sha256": _json_file_hash(work_output / "electrical-audit.json"),
    }
    if include_source:
        current_round["source_sha256"] = _file_hash(work_output / "source.png")
        current_round["comparison_sha256"] = _file_hash(work_output / f"cmp_round{round_number}.png")
    if patches_file is not None and patch_doc.get("change_evidence"):
        current_round["change_evidence"] = patch_doc["change_evidence"]
    rounds = list(previous["rounds"]) if previous else []
    rounds.append(current_round)
    task_kind = task_kind or ("redraw-image" if include_source else "render")
    task_input_artifact = task_input_artifact or (
        previous.get("task", {}).get("input_artifact") if previous else None
    )
    artifacts = _artifact_paths(output, include_source=include_source, round_number=round_number)
    if task_input_artifact is not None:
        artifacts["task_input"] = task_input_artifact
    state = {
        "report_version": REPORT_VERSION,
        "status": status,
        "task": _task_record(task_kind, task_input_artifact),
        "validation_status": validation["status"],
        "layout_status": layout["status"],
        "current_round": round_number,
        "max_rounds": max_rounds,
        "review_required": include_source,
        "ready_for_approval": False,
        "electrical_audit_status": electrical_audit["verdict"],
        "electrical_review_required": include_source,
        "electrical_ready_for_approval": False,
        "reason_codes": reason_codes,
        "rounds": rounds,
        "artifacts": artifacts,
        "timings": {**timings, "total": time.perf_counter() - build_started},
    }
    frozen_reason = _patch_path_reason(rounds)
    if frozen_reason is not None:
        state["status"] = "needs_human"
        _append_reason(state, frozen_reason)
    publish_output = work_output if preserve_history else output
    try:
        _copy_feedback(publish_output)
        _snapshot_round(publish_output, round_number)
        current_round["artifacts"] = _round_artifacts(output, round_number, include_source)
        _validate_document(state, "review-state.schema.json")
        _write_json(publish_output / "review.json", state)
        _write_delivery(publish_output, state)
        if preserve_history:
            _publish_stage(work_output, output, round_number)
    finally:
        if preserve_history:
            shutil.rmtree(work_output, ignore_errors=True)
    return _status_exit(state["status"])


def review(job_dir: str, review_file: str) -> int:
    output = Path(job_dir).resolve()
    try:
        with _job_lock(output):
            return _review_locked(output, review_file)
    except (OSError, RuntimeError) as exc:
        sys.stderr.write(f"ERROR: review environment failure: {exc}\n")
        return EXIT_ENV
    except (ValueError, jsonschema.ValidationError) as exc:
        sys.stderr.write(f"ERROR: invalid review: {exc}\n")
        return EXIT_ERROR


def _review_locked(output: Path, review_file: str) -> int:
    output, state = _load_state(str(output))
    try:
        report = _read_json(Path(review_file).resolve())
    except json.JSONDecodeError as exc:
        raise ValueError(f"review JSON is malformed: {exc}") from exc
    _validate_document(report, "review.schema.json")
    if not state.get("review_required"):
        raise ValueError("job has no source comparison and cannot accept a source review")
    if state["status"] not in ("needs_review", "needs_human"):
        raise ValueError(f"job status {state['status']} cannot accept a source review")
    if report["round"] != state["current_round"]:
        raise ValueError("review round does not match current_round")
    expected_regions = _load_regions(output / "circuit.ir.json", require_complete=True)
    actual_regions = [item["name"] for item in report["regions"]]
    if len(actual_regions) != len(set(actual_regions)):
        raise ValueError("review region names must be unique")
    if set(actual_regions) != set(expected_regions):
        raise ValueError("review must contain exactly one conclusion for every IR region")
    assessment = report.get("electrical_assessment")
    if assessment is None:
        raise ValueError("source-backed review requires electrical_assessment")
    differences = report["differences"]
    difference_ids = [item["id"] for item in differences]
    if len(difference_ids) != len(set(difference_ids)):
        raise ValueError("review difference IDs must be unique")
    region_conclusions = {item["name"]: item["conclusion"] for item in report["regions"]}
    difference_regions = {item["region"] for item in differences}
    if not difference_regions <= set(expected_regions):
        raise ValueError("review difference references an unknown region")
    for region, conclusion in region_conclusions.items():
        has_differences = region in difference_regions
        if (conclusion == "differences") != has_differences:
            raise ValueError("each region conclusion must agree with its bound differences")
    latest = state["rounds"][-1]
    if latest.get("reviewed"):
        raise ValueError("current round is already reviewed and immutable")
    live_ir_hash, source_hash, comparison_hash, electrical_audit_hash = _verify_round_evidence(
        output, state
    )
    audit_report = _read_json(output / "electrical-audit.json")
    electrical_ready, electrical_needs_human = _validate_electrical_assessment(
        assessment, audit_report, latest, differences
    )
    if audit_report["verdict"] == "block":
        electrical_ready = False
    latest["reviewed"] = True
    latest["regions"] = report["regions"]
    latest["differences"] = differences
    latest["reviewed_ir_sha256"] = live_ir_hash
    latest["reviewed_source_sha256"] = source_hash
    latest["reviewed_comparison_sha256"] = comparison_hash
    latest["reviewed_electrical_audit_sha256"] = electrical_audit_hash
    latest["electrical_assessment"] = assessment
    latest["electrical_assessment_sha256"] = _document_hash(assessment)
    latest["artifacts"]["electrical_assessment_json"] = str((
        output / "rounds" / f"round-{state['current_round']:02d}" /
        "electrical-assessment.json"
    ).resolve())
    if differences and len(state["rounds"]) >= 2:
        previous_differences = state["rounds"][-2].get("differences", [])
        if previous_differences and len(differences) >= len(previous_differences):
            _append_reason(state, "difference_count_not_decreasing")
    state["electrical_ready_for_approval"] = electrical_ready
    if electrical_needs_human:
        _append_reason(state, "electrical_needs_context")
    state["ready_for_approval"] = (
        not differences and electrical_ready and not state["reason_codes"]
    )
    if differences and state["current_round"] >= state["max_rounds"]:
        state["status"] = "needs_human"
        _append_reason(state, "max_rounds_reached")
        state["ready_for_approval"] = False
    elif state["reason_codes"]:
        state["status"] = "needs_human"
    else:
        state["status"] = "needs_review"
    _validate_document(state, "review-state.schema.json")
    _publish_state_and_delivery(output, state)
    return _status_exit(state["status"])

def approve(job_dir: str, note: str = "") -> int:
    output = Path(job_dir).resolve()
    try:
        with _job_lock(output):
            return _approve_locked(output, note)
    except (OSError, RuntimeError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"ERROR: approval environment failure: {exc}\n")
        return EXIT_ENV
    except ValueError as exc:
        sys.stderr.write(f"ERROR: approval rejected: {exc}\n")
        return EXIT_ERROR


def _approve_locked(output: Path, note: str) -> int:
    output, state = _load_state(str(output))
    latest = state["rounds"][-1]
    if not state.get("review_required") or not latest.get("reviewed"):
        raise ValueError("job is not ready for approval; complete a clean region review first")
    _load_regions(output / "circuit.ir.json", require_complete=True)
    if latest.get("differences"):
        raise ValueError("job has unresolved source-review differences")
    reviewed_regions = latest.get("regions", [])
    if not reviewed_regions or any(item.get("conclusion") != "no_difference" for item in reviewed_regions):
        raise ValueError("approval requires a complete zero-difference region review")
    live_ir_hash, source_hash, comparison_hash, electrical_audit_hash = _verify_round_evidence(
        output, state
    )
    if live_ir_hash != latest.get("reviewed_ir_sha256"):
        raise ValueError("live circuit IR differs from the reviewed IR")
    if source_hash != latest.get("reviewed_source_sha256"):
        raise ValueError("source evidence differs from the reviewed source")
    if comparison_hash != latest.get("reviewed_comparison_sha256"):
        raise ValueError("comparison evidence differs from the reviewed comparison")
    if electrical_audit_hash != latest.get("reviewed_electrical_audit_sha256"):
        raise ValueError("electrical audit differs from the reviewed audit")
    assessment = latest.get("electrical_assessment")
    if assessment is None:
        raise ValueError("reviewed electrical assessment is missing")
    electrical_assessment_hash = _document_hash(assessment)
    if electrical_assessment_hash != latest.get("electrical_assessment_sha256"):
        raise ValueError("electrical assessment differs from reviewed evidence")
    assessment_path = latest.get("artifacts", {}).get("electrical_assessment_json")
    if not assessment_path:
        raise ValueError("reviewed electrical assessment artifact is missing")
    persisted_assessment = _read_json(Path(assessment_path))
    if _document_hash(persisted_assessment) != electrical_assessment_hash:
        raise ValueError("persisted electrical assessment differs from reviewed evidence")
    live_validation, live_layout, audit_report = _live_deterministic_reports(output)
    if audit_report["candidate_ir_sha256"] != live_ir_hash:
        raise ValueError("electrical audit candidate hash differs from live circuit IR")
    _live_status, live_reasons = _derive_initial_workflow_state(
        live_validation, live_layout, audit_report, include_source=True
    )
    if live_reasons:
        raise ValueError("live deterministic evidence has blocking reasons: %s" % ", ".join(live_reasons))
    electrical_ready, electrical_needs_human = _validate_electrical_assessment(
        persisted_assessment, audit_report, latest, latest.get("differences", [])
    )
    if audit_report["verdict"] == "block" or electrical_needs_human or not electrical_ready:
        raise ValueError("live electrical evidence is not eligible for approval")
    convergence_reasons = {
        code for code in state.get("reason_codes", [])
        if code in {"difference_count_not_decreasing", "max_rounds_reached"}
        or code.startswith("patch_path_frozen:")
    }
    if convergence_reasons:
        raise ValueError("job is frozen by a convergence stop rule")
    state["reason_codes"] = []
    state["electrical_audit_status"] = audit_report["verdict"]
    state["electrical_ready_for_approval"] = electrical_ready
    if state["status"] == "approved":
        if state.get("approval", {}).get("ir_sha256") != live_ir_hash:
            raise ValueError("approved IR hash differs from live circuit IR")
        if state.get("approval", {}).get("electrical_audit_sha256") != electrical_audit_hash:
            raise ValueError("approved electrical audit hash differs from live audit")
        if state.get("approval", {}).get("electrical_assessment_sha256") != electrical_assessment_hash:
            raise ValueError("approved electrical assessment hash differs from live assessment")
        return EXIT_OK
    state["status"] = "approved"
    state["approval"] = {
        "note": note,
        "ir_sha256": live_ir_hash,
        "electrical_audit_sha256": electrical_audit_hash,
        "electrical_assessment_sha256": electrical_assessment_hash,
    }
    state["ready_for_approval"] = False
    _validate_document(state, "review-state.schema.json")
    _publish_state_and_delivery(output, state)
    return EXIT_OK

def repair(
    job_dir: str,
    ir_file: str,
    patches_file: str,
    dpi: int = 300,
) -> int:
    output = Path(job_dir).resolve()
    try:
        with _job_lock(output):
            return _repair_locked(output, ir_file, patches_file, dpi)
    except (OSError, RuntimeError) as exc:
        sys.stderr.write(f"ERROR: repair environment failure: {exc}\n")
        return EXIT_ENV
    except ValueError as exc:
        sys.stderr.write(f"ERROR: repair rejected: {exc}\n")
        return EXIT_ERROR


def _repair_locked(output: Path, ir_file: str, patches_file: str, dpi: int) -> int:
    output, state = _load_state(str(output))
    stop_reasons = {"difference_count_not_decreasing", "max_rounds_reached"}
    if stop_reasons.intersection(state.get("reason_codes", [])) or any(
        code.startswith("patch_path_frozen:") for code in state.get("reason_codes", [])
    ):
        raise ValueError("job is frozen by a convergence stop rule")
    if state["status"] not in ("needs_review", "needs_human"):
        raise ValueError(f"job status {state['status']} cannot be repaired")
    if not state["rounds"][-1].get("reviewed"):
        raise ValueError("current round must be reviewed before repair")
    if not state["rounds"][-1].get("differences"):
        raise ValueError("clean review must be approved, not repaired")
    try:
        patch_doc = _read_json(Path(patches_file).resolve())
    except json.JSONDecodeError as exc:
        raise ValueError(f"patch JSON is malformed: {exc}") from exc
    _validate_document(patch_doc, "patch-operations.schema.json")
    previous_ir = _read_json(output / "circuit.ir.json")
    candidate_ir = _read_json(Path(ir_file).resolve())
    change_evidence = _validate_patch_manifest(previous_ir, candidate_ir, state, patch_doc)
    patch_doc["change_evidence"] = change_evidence
    fd, verified_name = tempfile.mkstemp(
        prefix=".verified-patches-", suffix=".json", dir=str(output)
    )
    os.close(fd)
    verified_patches = Path(verified_name)
    _write_json(verified_patches, patch_doc)
    try:
        return _build(
            ir_file,
            str(output),
            dpi=dpi,
            task_kind=state["task"]["kind"],
            preserve_history=True,
            patches_file=str(verified_patches),
        )
    finally:
        verified_patches.unlink(missing_ok=True)