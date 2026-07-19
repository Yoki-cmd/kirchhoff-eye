"""Validation helpers for the perception evidence sidecar.

The JSON Schema owns structural validation. This module adds referential rules that
JSON Schema draft-07 cannot express cleanly: selected alternatives must exist and every
unresolved candidate must be represented in the prioritized review queue.
"""
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from jsonschema import Draft7Validator


def _default_schema_path() -> Path:
    source_root = Path(__file__).resolve().parents[3]
    source_schema = source_root / "schemas" / "perception-evidence.schema.json"
    if source_schema.is_file():
        return source_schema
    packaged_schema = Path(__file__).resolve().parents[1] / "schemas" / "perception-evidence.schema.json"
    return packaged_schema


def _format_schema_error(error) -> str:
    path = "/" + "/".join(str(item) for item in error.absolute_path)
    if error.validator == "oneOf":
        missing = sorted(
            {
                required
                for context in error.context
                if context.validator == "required"
                for required in context.validator_value
                if required not in context.instance
            }
        )
        if missing:
            return f"{path}: missing required field(s): {', '.join(missing)}"
    return f"{path}: {error.message}"


def validate_evidence_document(
    document: Dict[str, Any], schema_path: Optional[Path] = None
) -> List[str]:
    """Return deterministic validation messages; an empty list means valid."""
    path = Path(schema_path) if schema_path is not None else _default_schema_path()
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft7Validator.check_schema(schema)
    validator = Draft7Validator(schema)
    errors = sorted(validator.iter_errors(document), key=lambda item: list(item.absolute_path))
    messages = [_format_schema_error(error) for error in errors]
    if not isinstance(document, dict):
        return messages

    candidates = document.get("candidates", [])
    queue = document.get("review_queue", [])
    if not isinstance(candidates, list) or not isinstance(queue, list):
        return messages
    candidate_ids = [candidate.get("id") for candidate in candidates]
    if len(candidate_ids) != len(set(candidate_ids)):
        messages.append("/candidates: candidate ids must be unique")

    queue_ids = [item.get("candidate_id") for item in queue]
    if len(queue_ids) != len(set(queue_ids)):
        messages.append("/review_queue: candidate_id entries must be unique")

    by_id = {candidate.get("id"): candidate for candidate in candidates}
    for index, candidate in enumerate(candidates):
        resolution = candidate.get("resolution", {})
        alternatives = {item.get("id") for item in candidate.get("alternatives", [])}
        if resolution.get("status") == "selected":
            selected = resolution.get("selected_alternative_id")
            if selected not in alternatives:
                messages.append(
                    f"/candidates/{index}/resolution/selected_alternative_id: "
                    f"{selected!r} is not a declared alternative"
                )
        elif resolution.get("status") == "unresolved" and candidate.get("id") not in queue_ids:
            messages.append(
                f"/review_queue: unresolved candidate {candidate.get('id')!r} must have an entry"
            )

    for index, item in enumerate(queue):
        candidate = by_id.get(item.get("candidate_id"))
        if candidate is None:
            messages.append(
                f"/review_queue/{index}/candidate_id: {item.get('candidate_id')!r} is unknown"
            )
            continue
        if candidate.get("resolution", {}).get("status") != "unresolved":
            messages.append(
                f"/review_queue/{index}: selected candidate {item.get('candidate_id')!r} cannot remain queued"
            )
        reason = candidate.get("resolution", {}).get("blocking_reason_code")
        if item.get("reason_code") != reason:
            messages.append(
                f"/review_queue/{index}/reason_code: must equal candidate blocking reason {reason!r}"
            )
        if item.get("priority") != candidate.get("priority"):
            messages.append(
                f"/review_queue/{index}/priority: must equal candidate priority {candidate.get('priority')!r}"
            )

    return messages
