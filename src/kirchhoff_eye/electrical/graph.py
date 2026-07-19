"""Derive a net/device graph from a fully validated canonical circuit IR."""
from typing import Dict, Iterable, Optional, Set, Tuple

from .models import ElectricalGraph


_DC_TYPES = frozenset({"resistor", "inductor", "ammeter", "vsource", "battery"})
_PASSIVE_TYPES = frozenset({"resistor", "capacitor", "polar_capacitor", "inductor"})


def _add_edge(adjacency: Dict[str, Set[str]], left: str, right: str) -> None:
    adjacency.setdefault(left, set()).add(right)
    adjacency.setdefault(right, set()).add(left)


def _resolved_pin_net(validated, component: dict, pin_name: str, declared: Optional[str]) -> Optional[str]:
    if declared:
        return declared
    positions = validated.model.pin_positions(component) or {}
    position = positions.get(pin_name)
    if position is None:
        return None
    nets = validated.geometry.net_of_root(validated.geometry.root_of(position))
    return next(iter(nets)) if len(nets) == 1 else None


def _two_pin_edge(nets: Dict[str, str]) -> Iterable[Tuple[str, str]]:
    left = nets.get("1")
    right = nets.get("2")
    if left is not None and right is not None:
        yield left, right


def _transformer_edges(nets: Dict[str, str]) -> Iterable[Tuple[str, str]]:
    for left_name, right_name in (("A1", "A2"), ("B1", "B2")):
        left = nets.get(left_name)
        right = nets.get(right_name)
        if left is not None and right is not None:
            yield left, right


def build_graph(validated) -> ElectricalGraph:
    if validated.phase != "full" or validated.model is None or validated.geometry is None:
        raise ValueError("electrical graph requires a fully validated IR")
    if validated.report.has_error():
        raise ValueError("electrical graph cannot be built from an invalid IR")

    graph = ElectricalGraph(document=validated.document)
    for component in validated.document.get("components", []):
        component_id = component["id"]
        component_type = component["type"]
        declared = {pin.get("name"): pin.get("net") for pin in component.get("pins", [])}
        positions = validated.model.pin_positions(component) or {}
        pin_names = sorted(set(declared) | set(positions))
        resolved: Dict[str, str] = {}
        for pin_name in pin_names:
            net_name = _resolved_pin_net(validated, component, pin_name, declared.get(pin_name))
            if net_name is None:
                graph.limitations.append(
                    "Component %s pin %s does not resolve to exactly one canonical net."
                    % (component_id, pin_name)
                )
                continue
            resolved[pin_name] = net_name
            graph.component_pin_net[(component_id, pin_name)] = net_name
            graph.net_pins.setdefault(net_name, []).append((component_id, pin_name, component_type))
        graph.component_nets[component_id] = resolved

        if component_type == "ground":
            graph.ground_nets.update(resolved.values())
        elif component_type == "vcc":
            graph.vcc_nets.update(resolved.values())
        elif component_type == "vee":
            graph.vee_nets.update(resolved.values())

        if component_type == "transformer":
            edges = list(_transformer_edges(resolved))
        elif validated.model.kind_of(component) == "two":
            edges = list(_two_pin_edge(resolved))
        else:
            edges = []
        graph.device_edges[component_id] = edges
        if component_type in _DC_TYPES:
            for left, right in edges:
                _add_edge(graph.dc_adjacency, left, right)
        if component_type in _PASSIVE_TYPES:
            for left, right in edges:
                _add_edge(graph.passive_adjacency, left, right)

    for net_name in set(graph.net_pins) | graph.ground_nets | graph.vcc_nets | graph.vee_nets:
        graph.dc_adjacency.setdefault(net_name, set())
        graph.passive_adjacency.setdefault(net_name, set())
    for records in graph.net_pins.values():
        records.sort()

    for index, terminal in enumerate(validated.document.get("terminals", [])):
        nets = validated.geometry.net_of_root(validated.geometry.root_of(tuple(terminal["at"])))
        graph.terminal_nets[index] = next(iter(nets)) if len(nets) == 1 else None
        if len(nets) != 1:
            graph.limitations.append(
                "Terminal %d does not resolve to exactly one canonical net." % index
            )
    return graph
