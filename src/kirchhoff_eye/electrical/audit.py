"""Conservative deterministic electrical plausibility audit."""
import hashlib
import json
from collections import deque
from typing import Dict, Iterable, List, Set, Tuple

from .constraints import audit_voltage_constraints
from .graph import build_graph
from .motifs import recognize_motifs
from .values import parse_value


_BYPASS_TYPES = frozenset({
    "resistor", "potentiometer", "capacitor", "polar_capacitor", "inductor",
    "diode", "zener", "led",
})
_REFERENCE_TYPES = frozenset({"ground", "vcc", "vee"})
_SCOPE_LIMIT_TYPES = frozenset({"cvsource", "cisource", "switch_spst", "spdt"})
_NUMERIC_VALUE_TYPES = frozenset({
    "resistor", "potentiometer", "capacitor", "polar_capacitor", "inductor",
    "battery", "vsource", "isource",
})


def _canonical_hash(document: dict) -> str:
    payload = json.dumps(
        document, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _component_index(graph) -> Dict[str, int]:
    return {
        component["id"]: index
        for index, component in enumerate(graph.document.get("components", []))
    }


def _finding(
    graph,
    code: str,
    severity: str,
    basis: str,
    message: str,
    component_ids: Iterable[str] = (),
    net_names: Iterable[str] = (),
    assumptions: Iterable[str] = (),
    suggested_checks: Iterable[str] = (),
    confidence: float = 1.0,
    ir_paths: Iterable[str] = (),
) -> dict:
    indexes = _component_index(graph)
    components = sorted(set(component_ids))
    paths = list(ir_paths) or ["/components/%d" % indexes[item] for item in components if item in indexes]
    return {
        "id": code,
        "code": code,
        "severity": severity,
        "basis": basis,
        "message": message,
        "ir_paths": sorted(set(paths)),
        "component_ids": components,
        "net_names": sorted(set(net_names)),
        "assumptions": list(assumptions),
        "confidence": confidence,
        "suggested_checks": list(suggested_checks),
    }


def _reachable(adjacency: Dict[str, Set[str]], start: str, targets: Set[str]) -> bool:
    if start in targets:
        return True
    queue = deque([start])
    visited = {start}
    while queue:
        current = queue.popleft()
        for neighbor in adjacency.get(current, set()):
            if neighbor in targets:
                return True
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)
    return False


def _same_net_findings(graph) -> List[dict]:
    findings = []
    for component in graph.document.get("components", []):
        component_id = component["id"]
        component_type = component.get("type")
        nets = graph.component_nets.get(component_id, {})
        if component_type in _BYPASS_TYPES and nets.get("1") is not None and nets.get("1") == nets.get("2"):
            findings.append(_finding(
                graph, "EA102", "warning", "device_semantics",
                "A two-terminal component is bypassed because both pins share one net.",
                [component_id], [nets["1"]],
                ["The canonical pin-to-net mapping is intentional."],
                ["Reinspect the component endpoints and nearby junctions."],
            ))
        elif component_type == "transformer":
            for left, right in (("A1", "A2"), ("B1", "B2")):
                if nets.get(left) is not None and nets.get(left) == nets.get(right):
                    findings.append(_finding(
                        graph, "EA103", "warning", "device_semantics",
                        "A transformer winding is shorted in the canonical net graph.",
                        [component_id], [nets[left]],
                        ["Each winding is modeled as a separate two-terminal path."],
                        ["Reinspect the winding pins and any crossing/junction at the transformer."],
                    ))
        elif component_type in ("npn", "pnp") and nets.get("C") is not None and nets.get("C") == nets.get("E"):
            findings.append(_finding(
                graph, "EA104", "warning", "device_semantics",
                "The BJT collector and emitter share one net.",
                [component_id], [nets["C"]],
                ["Base-collector diode connection is legal and is checked separately."],
                ["Reinspect collector/emitter pin identity and attached wires."],
            ))
        elif component_type in ("nmos", "pmos") and nets.get("D") is not None and nets.get("D") == nets.get("S"):
            findings.append(_finding(
                graph, "EA104", "warning", "device_semantics",
                "The MOS drain and source share one net.",
                [component_id], [nets["D"]],
                ["Gate-drain and gate-source diode connections may be intentional."],
                ["Reinspect drain/source pin identity and attached wires."],
            ))
    return findings


def _rail_findings(graph) -> List[dict]:
    findings = []
    conflicts = (
        (graph.ground_nets & graph.vcc_nets, "ground and VCC"),
        (graph.ground_nets & graph.vee_nets, "ground and VEE"),
        (graph.vcc_nets & graph.vee_nets, "VCC and VEE"),
    )
    for nets, label in conflicts:
        for net_name in sorted(nets):
            component_ids = [
                component["id"] for component in graph.document.get("components", [])
                if component.get("type") in _REFERENCE_TYPES
                and net_name in graph.component_nets.get(component["id"], {}).values()
            ]
            findings.append(_finding(
                graph, "EA001", "blocker", "power_rail",
                "One canonical net is simultaneously %s." % label,
                component_ids, [net_name],
                ["Power-rail symbols with the same canonical net are electrically identical."],
                ["Reinspect rail labels, junctions, and crossings."],
            ))
    return findings


def _output_contention_findings(graph) -> List[dict]:
    findings = []
    for net_name, records in sorted(graph.net_pins.items()):
        outputs = sorted(component_id for component_id, pin_name, component_type in records
                         if component_type == "opamp" and pin_name == "out")
        if len(outputs) >= 2:
            findings.append(_finding(
                graph, "EA105", "warning", "device_semantics",
                "Multiple op-amp outputs share one net.", outputs, [net_name],
                ["No explicit tri-state or isolation behavior is modeled."],
                ["Confirm intentional output sharing or inspect the junction/crossing evidence."],
            ))
    return findings


def _floating_input_findings(graph, motifs: List[dict]) -> List[dict]:
    findings = []
    external = {net for net in graph.terminal_nets.values() if net is not None}
    targets = set(graph.ground_nets) | set(graph.vcc_nets) | set(graph.vee_nets) | external
    feedback_components = {
        component_id for motif in motifs if motif["code"] in ("M002", "M003")
        for component_id in motif["component_ids"]
    }
    for component in graph.document.get("components", []):
        component_id = component["id"]
        component_type = component.get("type")
        if component_type in ("npn", "pnp"):
            control_pins = ("B",)
        elif component_type in ("nmos", "pmos"):
            control_pins = ("G",)
        elif component_type == "opamp":
            control_pins = ("inn", "inp")
        else:
            continue
        for pin_name in control_pins:
            net_name = graph.component_nets.get(component_id, {}).get(pin_name)
            if net_name is None:
                continue
            if component_type == "opamp" and component_id in feedback_components and pin_name == "inn":
                continue
            if _reachable(graph.dc_adjacency, net_name, targets):
                continue
            indexes = _component_index(graph)
            findings.append(_finding(
                graph, "EA106", "warning", "dc_path",
                "A transistor control pin or op-amp input has no deterministic DC path to a rail, reference, or terminal.",
                [component_id], [net_name],
                ["Capacitors, diodes, semiconductor channels, op-amps, and unknown switch states are not deterministic DC paths."],
                ["Confirm external drive, bias components, and low-contrast source wires."],
                ir_paths=["/components/%d/pins/%d" % (
                    indexes[component_id],
                    next((index for index, pin in enumerate(component.get("pins", [])) if pin.get("name") == pin_name), 0),
                )],
            ))
    return findings


def _positive_feedback_findings(graph, motifs: List[dict]) -> List[dict]:
    findings = []
    negative_feedback = {component_id for motif in motifs if motif["code"] in ("M002", "M003")
                         for component_id in motif["component_ids"]}
    for component in graph.document.get("components", []):
        if component.get("type") != "opamp" or component["id"] in negative_feedback:
            continue
        nets = graph.component_nets.get(component["id"], {})
        output, positive, negative = nets.get("out"), nets.get("inp"), nets.get("inn")
        if output is None or positive is None or negative is None:
            continue
        if _reachable(graph.passive_adjacency, output, {positive}) and not _reachable(
            graph.passive_adjacency, output, {negative}
        ):
            findings.append(_finding(
                graph, "EA107", "warning", "engineering_heuristic",
                "The op-amp has passive positive feedback without a passive negative-feedback path.",
                [component["id"]], [output, positive, negative],
                ["Comparator and Schmitt-trigger operation may be intentional."],
                ["Confirm whether positive feedback is intended and whether a negative path was missed."],
                confidence=0.9,
            ))
    return findings


def _coverage_findings(graph) -> Tuple[List[dict], dict]:
    findings = []
    known = missing = unparsed = 0
    limitations = list(graph.limitations)
    for component in graph.document.get("components", []):
        if "value" not in component:
            if component.get("type") in _NUMERIC_VALUE_TYPES:
                missing += 1
            continue
        parsed = parse_value(component.get("value"))
        if parsed.status == "known":
            known += 1
        elif parsed.status == "missing":
            missing += 1
        else:
            unparsed += 1
            findings.append(_finding(
                graph, "EA202", "info", "coverage",
                "A component value is present but outside the safe numeric parser language.",
                [component["id"]], graph.component_nets.get(component["id"], {}).values(),
                ["Unsupported value text is not guessed or evaluated as TeX."],
                ["Normalize the value text if numeric analysis is required."],
            ))
    scoped = sorted({component.get("type") for component in graph.document.get("components", [])
                     if component.get("type") in _SCOPE_LIMIT_TYPES})
    if scoped:
        limitations.append("Unmodeled control/state semantics: %s." % ", ".join(scoped))
    if limitations:
        findings.append(_finding(
            graph, "EA203", "info", "coverage",
            "Part of the circuit is outside the deterministic electrical-analysis scope.",
            assumptions=["No hidden device models, switch states, or external context are inferred."],
            suggested_checks=limitations,
        ))
    coverage = {
        "net_graph": "limited" if graph.limitations else "complete",
        "ideal_voltage_constraints": "known-independent-sources-only",
        "dc_bias_paths": "heuristic",
        "nonlinear_operating_point": "not_analyzed",
        "frequency_response": "not_analyzed",
        "transient": "not_analyzed",
        "external_context": "not_inferred",
        "known_numeric_values": known,
        "missing_numeric_values": missing,
        "unparsed_numeric_values": unparsed,
        "limitations": sorted(set(limitations)),
    }
    return findings, coverage


def _stable_ids(items: List[dict]) -> List[dict]:
    ordered = sorted(items, key=lambda item: (
        item["code"], item.get("component_ids", []), item.get("net_names", []),
        item.get("ir_paths", []), item.get("message", ""), item.get("kind", ""),
    ))
    counts: Dict[str, int] = {}
    for item in ordered:
        code = item["code"]
        counts[code] = counts.get(code, 0) + 1
        item["id"] = "%s-%d" % (code, counts[code])
    return ordered


def audit_graph(graph) -> dict:
    motifs = recognize_motifs(graph)
    findings = []
    findings.extend(_rail_findings(graph))
    findings.extend(audit_voltage_constraints(graph))
    findings.extend(_same_net_findings(graph))
    findings.extend(_output_contention_findings(graph))
    findings.extend(_floating_input_findings(graph, motifs))
    findings.extend(_positive_feedback_findings(graph, motifs))
    if not graph.ground_nets:
        findings.append(_finding(
            graph, "EA201", "info", "coverage",
            "No explicit ground/reference node is present.",
            assumptions=["A floating circuit can still be valid; only absolute-potential analysis is limited."],
            suggested_checks=["Add or confirm a reference node only if the source diagram contains one."],
        ))
    coverage_findings, coverage = _coverage_findings(graph)
    findings.extend(coverage_findings)
    findings = _stable_ids(findings)
    motifs = _stable_ids(motifs)
    blockers = sum(finding["severity"] == "blocker" for finding in findings)
    warnings = sum(finding["severity"] == "warning" for finding in findings)
    infos = sum(finding["severity"] == "info" for finding in findings)
    verdict = "block" if blockers else ("warn" if warnings else "pass")
    if verdict == "block":
        statement = "Deterministic electrical contradictions require human review."
    elif verdict == "warn":
        statement = "No deterministic contradiction found; engineering warnings require disposition."
    else:
        statement = "No contradiction found within the analyzed scope."
    return {
        "version": "kirchhoff-electrical-audit/1.0",
        "candidate_ir_sha256": _canonical_hash(graph.document),
        "verdict": verdict,
        "summary": {
            "blockers": blockers,
            "warnings": warnings,
            "info": infos,
            "recognized_motifs": len(motifs),
            "statement": statement,
        },
        "coverage": coverage,
        "findings": findings,
        "motifs": motifs,
    }


def audit_validated(validated) -> dict:
    return audit_graph(build_graph(validated))
