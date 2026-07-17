"""Deterministic canonical-IR build, review, repair, and approval pipeline."""

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import jsonschema


PACKAGE_ROOT = Path(__file__).resolve().parent
SOURCE_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = SOURCE_ROOT if (SOURCE_ROOT / "scripts" / "validate_ir.py").exists() else PACKAGE_ROOT
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
SCHEMAS_DIR = PROJECT_ROOT / "schemas"
TEMPLATES_DIR = PROJECT_ROOT / "templates"
CONFIG_PATH = PROJECT_ROOT / "config.json"

EXIT_OK = 0
EXIT_NEEDS_HUMAN = 1
EXIT_ERROR = 2
EXIT_ENV = 3
REPORT_VERSION = "kirchhoff-review/1.0"

GENERATED_ARTIFACTS = (
    "source.png", "compare.png", "circuit.tex", "circuit.debug.tex",
    "circuit.png", "circuit.debug.png", "validation.json",
    "layout_report.json", "review.json", "DELIVERY.md", "FEEDBACK.md",
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


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)


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
    validation: Dict[str, Any], layout: Dict[str, Any], include_source: bool
) -> Tuple[str, List[str]]:
    validation_codes = {
        finding.get("code") for finding in validation.get("findings", [])
        if finding.get("severity") == "W"
    }
    layout_codes = {
        finding.get("code") for finding in layout.get("findings", [])
        if finding.get("severity") == "W"
    }
    reasons: List[str] = []
    if "W108" in validation_codes:
        reasons.append("blocking_unknown")
    if any(code and code.startswith("BLOCKING_") for code in validation_codes | layout_codes):
        reasons.append("blocking_ambiguity")
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
        "circuit.debug.png", "validation.json", "layout_report.json",
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
    }
    if include_source:
        artifacts["compare_png"] = str((snapshot / f"cmp_round{round_number}.png").resolve())
    return artifacts


def _atomic_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + ".tmp")
    shutil.copy2(source, temp)
    temp.replace(target)


def _publish_stage(stage: Path, output: Path, round_number: int) -> None:
    relative_paths = [
        Path(name) for name in (
            "circuit.ir.json", "circuit.tex", "circuit.debug.tex", "circuit.png",
            "circuit.debug.png", "validation.json", "layout_report.json",
            f"cmp_round{round_number}.png", "compare.png", "FEEDBACK.md",
            "review.json", "DELIVERY.md",
        )
        if (stage / name).is_file()
    ]
    snapshot = stage / "rounds" / f"round-{round_number:02d}"
    if snapshot.is_dir():
        relative_paths.extend(path.relative_to(stage) for path in snapshot.rglob("*") if path.is_file())
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
        shutil.rmtree(output / "rounds" / f"round-{round_number:02d}", ignore_errors=True)
        raise
    finally:
        shutil.rmtree(backup, ignore_errors=True)


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


def _verify_round_evidence(output: Path, state: Dict[str, Any]) -> Tuple[str, str, str]:
    round_number = state["current_round"]
    latest = state["rounds"][-1]
    snapshot = output / "rounds" / f"round-{round_number:02d}"
    live_ir_hash = _json_file_hash(output / "circuit.ir.json")
    source_hash = _file_hash(output / "source.png")
    comparison_hash = _file_hash(output / f"cmp_round{round_number}.png")
    expected = {
        "ir_sha256": live_ir_hash,
        "source_sha256": source_hash,
        "comparison_sha256": comparison_hash,
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
    return live_ir_hash, source_hash, comparison_hash


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
    try:
        return _build(
            ir_file,
            out_dir,
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
    work_output = output / ".next-round" if preserve_history else output
    work_ir = work_output / "circuit.ir.json"
    try:
        output.mkdir(parents=True, exist_ok=True)
        if not preserve_history:
            _clear_generated_artifacts(output)
        else:
            shutil.rmtree(work_output, ignore_errors=True)
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

    rc, stdout, stderr = _run(
        "validate_ir.py", [str(work_ir), "--phase", "full", "--json"]
    )
    if rc == EXIT_ENV:
        return abort(EXIT_ENV, stderr or stdout)
    validation = _load_json_output(stdout, "validate_ir.py")
    _write_json(work_output / "validation.json", validation)
    if rc == EXIT_ERROR:
        return abort(EXIT_ERROR)

    tex = work_output / "circuit.tex"
    rc, stdout, stderr = _run("ir2tikz.py", [str(work_ir), "-o", str(tex)])
    if rc != EXIT_OK:
        return abort(EXIT_ENV if rc == EXIT_ENV else EXIT_ERROR, stderr or stdout)

    png = work_output / "circuit.png"
    rc, stdout, stderr = _run(
        "render.py", [str(tex), "-o", str(png), "--dpi", str(dpi)]
    )
    if rc != EXIT_OK:
        return abort(EXIT_ENV if rc == EXIT_ENV else EXIT_ERROR, stderr or stdout)

    rc, stdout, stderr = _run(
        "ir_fix_and_render.py", [str(work_ir), "--layout-check", "--json"]
    )
    source_layout = work_ir.with_suffix(".layout_report.json")
    if source_layout.exists():
        source_layout.replace(work_output / "layout_report.json")
    else:
        return abort(EXIT_ENV, stderr or stdout or "ERROR: layout report was not generated\n")
    layout = _read_json(work_output / "layout_report.json")
    if rc == EXIT_ERROR:
        return abort(EXIT_ERROR)
    if rc not in (EXIT_OK, EXIT_NEEDS_HUMAN):
        return abort(EXIT_ENV)

    include_source = source is not None or (preserve_history and (output / "source.png").exists())
    if include_source:
        compare = work_output / f"cmp_round{round_number}.png"
        rc, stdout, stderr = _run(
            "compare.py",
            [str(work_output / "source.png"), str(png), "-o", str(compare)],
        )
        if rc != EXIT_OK:
            return abort(EXIT_ENV, stderr or stdout)

    if include_source:
        shutil.copy2(work_output / f"cmp_round{round_number}.png", work_output / "compare.png")

    target_ir = work_ir
    png = work_output / "circuit.png"
    status, reason_codes = _derive_initial_workflow_state(validation, layout, include_source)
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
        "reason_codes": reason_codes,
        "rounds": rounds,
        "artifacts": artifacts,
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
    try:
        output, state = _load_state(job_dir)
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
        live_ir_hash, source_hash, comparison_hash = _verify_round_evidence(output, state)
        latest["reviewed"] = True
        latest["regions"] = report["regions"]
        latest["differences"] = differences
        latest["reviewed_ir_sha256"] = live_ir_hash
        latest["reviewed_source_sha256"] = source_hash
        latest["reviewed_comparison_sha256"] = comparison_hash
        if differences and len(state["rounds"]) >= 2:
            previous_differences = state["rounds"][-2].get("differences", [])
            if previous_differences and len(differences) >= len(previous_differences):
                _append_reason(state, "difference_count_not_decreasing")
        state["ready_for_approval"] = not differences and not state["reason_codes"]
        if differences and state["current_round"] >= state["max_rounds"]:
            state["status"] = "needs_human"
            _append_reason(state, "max_rounds_reached")
            state["ready_for_approval"] = False
        elif state["reason_codes"]:
            state["status"] = "needs_human"
        else:
            state["status"] = "needs_review"
        _write_json(output / "review.json", state)
        _write_delivery(output, state)
        return _status_exit(state["status"])
    except (OSError, RuntimeError) as exc:
        sys.stderr.write(f"ERROR: review environment failure: {exc}\n")
        return EXIT_ENV
    except (ValueError, jsonschema.ValidationError) as exc:
        sys.stderr.write(f"ERROR: invalid review: {exc}\n")
        return EXIT_ERROR


def approve(job_dir: str, note: str = "") -> int:
    try:
        output, state = _load_state(job_dir)
        if state["status"] == "approved":
            return EXIT_OK
        latest = state["rounds"][-1]
        if not state.get("review_required") or not latest.get("reviewed"):
            raise ValueError("job is not ready for approval; complete a clean region review first")
        _load_regions(output / "circuit.ir.json", require_complete=True)
        if latest.get("differences") or state.get("reason_codes"):
            raise ValueError("job has unresolved differences or blocking reasons")
        reviewed_regions = latest.get("regions", [])
        if not reviewed_regions or any(item.get("conclusion") != "no_difference" for item in reviewed_regions):
            raise ValueError("approval requires a complete zero-difference region review")
        live_ir_hash, source_hash, comparison_hash = _verify_round_evidence(output, state)
        if live_ir_hash != latest.get("reviewed_ir_sha256"):
            raise ValueError("live circuit IR differs from the reviewed IR")
        if source_hash != latest.get("reviewed_source_sha256"):
            raise ValueError("source evidence differs from the reviewed source")
        if comparison_hash != latest.get("reviewed_comparison_sha256"):
            raise ValueError("comparison evidence differs from the reviewed comparison")
        state["status"] = "approved"
        state["approval"] = {"note": note, "ir_sha256": live_ir_hash}
        state["ready_for_approval"] = False
        _validate_document(state, "review-state.schema.json")
        _write_json(output / "review.json", state)
        _write_delivery(output, state)
        return EXIT_OK
    except (OSError, RuntimeError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"ERROR: approval environment failure: {exc}\n")
        return EXIT_ENV
    except ValueError as exc:
        sys.stderr.write(f"ERROR: approval rejected: {exc}\n")
        return EXIT_ERROR


def repair(
    job_dir: str,
    ir_file: str,
    patches_file: str,
    dpi: int = 300,
) -> int:
    try:
        output, state = _load_state(job_dir)
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
        verified_patches = output / ".verified-patches.json"
        _write_json(verified_patches, patch_doc)
        try:
            return build(
                ir_file,
                str(output),
                dpi=dpi,
                task_kind=state["task"]["kind"],
                preserve_history=True,
                patches_file=str(verified_patches),
            )
        finally:
            verified_patches.unlink(missing_ok=True)
    except (OSError, RuntimeError) as exc:
        sys.stderr.write(f"ERROR: repair environment failure: {exc}\n")
        return EXIT_ENV
    except ValueError as exc:
        sys.stderr.write(f"ERROR: repair rejected: {exc}\n")
        return EXIT_ERROR
