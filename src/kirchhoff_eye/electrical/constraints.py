"""Independent ideal-voltage source constraint analysis."""
from collections import deque
from typing import Dict, List, Optional, Tuple

from .values import parse_value


Constraint = Tuple[str, str, float, str, str]


def _finding(
    code: str,
    severity: str,
    basis: str,
    message: str,
    components: List[Tuple[int, dict]],
    net_names: List[str],
    assumptions: List[str],
    suggested_checks: List[str],
) -> dict:
    return {
        "id": code,
        "code": code,
        "severity": severity,
        "basis": basis,
        "message": message,
        "ir_paths": ["/components/%d" % index for index, _component in components],
        "component_ids": sorted(component["id"] for _index, component in components),
        "net_names": sorted(set(net_names)),
        "assumptions": assumptions,
        "confidence": 1.0,
        "suggested_checks": suggested_checks,
    }


def _path(adjacency: Dict[str, List[Tuple[str, float, str, int]]], start: str, goal: str):
    queue = deque([(start, 0.0, [])])
    visited = {start}
    while queue:
        net_name, potential, source_path = queue.popleft()
        if net_name == goal:
            return potential, source_path
        for neighbor, delta, component_id, component_index in adjacency.get(net_name, []):
            if neighbor in visited:
                continue
            visited.add(neighbor)
            queue.append((
                neighbor,
                potential + delta,
                source_path + [(component_id, component_index)],
            ))
    return None


def _close(left: float, right: float) -> bool:
    return abs(left - right) <= max(1e-9, abs(right) * 1e-9)


def audit_voltage_constraints(graph) -> List[dict]:
    components_by_id = {
        component["id"]: (index, component)
        for index, component in enumerate(graph.document.get("components", []))
    }
    adjacency: Dict[str, List[Tuple[str, float, str, int]]] = {}
    findings: List[dict] = []

    for index, component in enumerate(graph.document.get("components", [])):
        if component.get("type") not in ("vsource", "battery"):
            continue
        component_id = component["id"]
        nets = graph.component_nets.get(component_id, {})
        from_net = nets.get("1")
        to_net = nets.get("2")
        if from_net is None or to_net is None:
            continue
        parsed = parse_value(component.get("value"))
        is_known_voltage = parsed.status == "known" and parsed.unit == "V"
        if from_net == to_net:
            if is_known_voltage and not _close(parsed.value, 0.0):
                findings.append(_finding(
                    "EA002", "blocker", "ideal_constraint",
                    "A known nonzero independent voltage source is shorted.",
                    [(index, component)], [from_net],
                    ["Parsed source values are exact ideal-voltage constraints."],
                    ["Reinspect source polarity and junction/crossing evidence."],
                ))
            elif not is_known_voltage:
                findings.append(_finding(
                    "EA108", "warning", "ideal_constraint",
                    "A voltage source is shorted, but its value is missing or unparsed.",
                    [(index, component)], [from_net],
                    ["The source value cannot be assumed to be nonzero."],
                    ["Confirm the source value and whether both terminals intentionally share one net."],
                ))
            continue
        if not is_known_voltage:
            continue

        existing = _path(adjacency, from_net, to_net)
        if existing is not None:
            existing_value, existing_path = existing
            path_components = [components_by_id[component_id] for component_id, _idx in existing_path]
            all_components = path_components + [(index, component)]
            all_nets = [from_net, to_net]
            for prior_component_id, _prior_index in existing_path:
                all_nets.extend(graph.component_nets.get(prior_component_id, {}).values())
            direct_parallel = len(existing_path) == 1
            if _close(existing_value, parsed.value) and direct_parallel:
                findings.append(_finding(
                    "EA101", "warning", "ideal_constraint",
                    "Equivalent ideal voltage constraints are parallel.",
                    all_components, all_nets,
                    ["Ideal source internal resistance is zero."],
                    ["Confirm intentional source paralleling and current sharing assumptions."],
                ))
            elif not _close(existing_value, parsed.value):
                findings.append(_finding(
                    "EA003", "blocker", "ideal_constraint",
                    "Known independent ideal-voltage constraints are contradictory.",
                    all_components, all_nets,
                    ["Parsed source values are exact ideal-voltage constraints."],
                    ["Reinspect all source values, polarities, and junction/crossing evidence on the loop."],
                ))
            continue

        adjacency.setdefault(from_net, []).append((to_net, parsed.value, component_id, index))
        adjacency.setdefault(to_net, []).append((from_net, -parsed.value, component_id, index))

    return findings
