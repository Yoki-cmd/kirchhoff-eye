"""Positive-only recognition of a deliberately small set of circuit motifs."""
from collections import deque
from itertools import combinations
from typing import Dict, List, Set


def _connected(adjacency: Dict[str, Set[str]], start: str, goal: str) -> bool:
    if start == goal:
        return True
    queue = deque([start])
    visited = {start}
    while queue:
        current = queue.popleft()
        for neighbor in adjacency.get(current, set()):
            if neighbor == goal:
                return True
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)
    return False


def _motif(code: str, kind: str, component_ids: List[str], net_names: List[str], evidence: str) -> dict:
    return {
        "id": code,
        "code": code,
        "kind": kind,
        "confidence": 1.0,
        "component_ids": sorted(set(component_ids)),
        "net_names": sorted(set(net_names)),
        "evidence": evidence,
    }


def recognize_motifs(graph) -> List[dict]:
    motifs: List[dict] = []
    components = graph.document.get("components", [])
    resistors = [component for component in components if component.get("type") == "resistor"]
    for left, right in combinations(resistors, 2):
        left_nets = set(graph.component_nets.get(left["id"], {}).values())
        right_nets = set(graph.component_nets.get(right["id"], {}).values())
        shared = left_nets & right_nets
        outer = (left_nets | right_nets) - shared
        if len(left_nets) == 2 and len(right_nets) == 2 and len(shared) == 1 and len(outer) == 2:
            motifs.append(_motif(
                "M001", "voltage_divider", [left["id"], right["id"]],
                list(shared | outer),
                "Two resistors share exactly one midpoint net and have distinct outer nets.",
            ))

    for component in components:
        component_id = component["id"]
        component_type = component.get("type")
        nets = graph.component_nets.get(component_id, {})
        if component_type == "opamp":
            output = nets.get("out")
            negative = nets.get("inn")
            if output is not None and negative is not None:
                if output == negative:
                    motifs.append(_motif(
                        "M002", "opamp_voltage_follower", [component_id], [output],
                        "The op-amp output and inverting input share the same net.",
                    ))
                elif _connected(graph.passive_adjacency, output, negative):
                    motifs.append(_motif(
                        "M003", "opamp_negative_feedback", [component_id], [output, negative],
                        "A passive path connects the op-amp output to its inverting input.",
                    ))
        elif component_type in ("npn", "pnp") and nets.get("B") == nets.get("C") and nets.get("B") is not None:
            motifs.append(_motif(
                "M004", "diode_connected_bjt", [component_id], [nets["B"]],
                "The BJT base and collector share one net.",
            ))
        elif component_type in ("nmos", "pmos"):
            gate = nets.get("G")
            drain = nets.get("D")
            source = nets.get("S")
            if gate is not None and gate in (drain, source):
                motifs.append(_motif(
                    "M005", "diode_connected_mos", [component_id],
                    [net for net in (gate, drain, source) if net is not None],
                    "The MOS gate shares a net with drain or source.",
                ))
    return motifs
