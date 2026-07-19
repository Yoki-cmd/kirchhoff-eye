# -*- coding: utf-8 -*-
"""Electrical audit graph is derived from validated connectivity, never proximity."""
import copy
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _validated(document):
    import validate_ir

    validated = validate_ir.validate_document(document, phase="full")
    assert not validated.report.has_error(), validated.report.to_text()
    return validated


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_golden_a_maps_pins_terminals_and_rails_to_canonical_nets(golden_a):
    from kirchhoff_eye.electrical.graph import build_graph

    graph = build_graph(_validated(golden_a))

    assert graph.component_pin_net[("R1", "1")] == "N_IN"
    assert graph.component_pin_net[("R1", "2")] == "N_MID"
    assert graph.component_nets["C1"] == {"1": "N_MID", "2": "GND"}
    assert graph.terminal_nets[0] == "N_MID"
    assert graph.ground_nets == {"GND"}
    assert graph.vcc_nets == set()
    assert graph.vee_nets == set()
    assert graph.limitations == []


def test_power_rail_types_are_recorded_by_semantic_net(golden_b):
    from kirchhoff_eye.electrical.graph import build_graph

    graph = build_graph(_validated(golden_b))

    assert graph.ground_nets == {"GND"}
    assert graph.vcc_nets == {"VCC"}
    assert graph.vee_nets == set()


def test_transformer_creates_only_winding_edges():
    from kirchhoff_eye.electrical.graph import build_graph

    ir = _load(ROOT / "tests" / "fixtures" / "synthetic_ir" / "15-transformer.json")
    graph = build_graph(_validated(ir))

    assert {frozenset(edge) for edge in graph.device_edges["T1"]} == {
        frozenset(("N_PRI1", "N_PRI2")),
        frozenset(("N_SEC1", "N_SEC2")),
    }
    assert "N_SEC1" not in graph.dc_adjacency["N_PRI1"]
    assert "N_PRI1" not in graph.dc_adjacency["N_SEC1"]


def test_opamp_and_transistor_are_not_deterministic_dc_edges(golden_b):
    from kirchhoff_eye.electrical.graph import build_graph

    opamp_ir = _load(ROOT / "tests" / "fixtures" / "synthetic_ir" / "14-opamp.json")
    opamp_graph = build_graph(_validated(opamp_ir))
    bjt_graph = build_graph(_validated(golden_b))

    assert opamp_graph.device_edges["U1"] == []
    assert bjt_graph.device_edges["Q1"] == []
    # The feedback resistor may connect N_OUT/N_FB in the aggregate DC graph;
    # the device-level edge list proves the op-amp itself was not treated as a path.
    assert all(edge not in opamp_graph.device_edges["U1"] for edge in [("N_OUT", "N_FB")])
    assert all(edge not in bjt_graph.device_edges["Q1"] for edge in [("N_C", "N_B")])


def test_terminal_without_unique_net_is_limited_not_guessed(golden_a):
    from kirchhoff_eye.electrical.graph import build_graph

    ir = copy.deepcopy(golden_a)
    ir["terminals"].append({
        "at": [6.5, 4.5], "style": "ocirc", "label": "floating", "label_side": "right"
    })
    graph = build_graph(_validated(ir))

    assert graph.terminal_nets[0] == "N_MID"
    assert graph.terminal_nets[1] is None
    assert graph.limitations == ["Terminal 1 does not resolve to exactly one canonical net."]


def test_net_pin_entries_are_stably_sorted(golden_a):
    from kirchhoff_eye.electrical.graph import build_graph

    first = build_graph(_validated(golden_a))
    second = build_graph(_validated(copy.deepcopy(golden_a)))

    assert first.net_pins == second.net_pins
    assert first.net_pins["N_MID"] == sorted(first.net_pins["N_MID"])
