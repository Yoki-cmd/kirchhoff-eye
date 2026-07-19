# -*- coding: utf-8 -*-
"""Conservative electrical rules distinguish contradictions, warnings, and motifs."""
import copy
import json
from pathlib import Path

from kirchhoff_eye.electrical.models import ElectricalGraph


ROOT = Path(__file__).resolve().parents[1]


def _validated(document):
    import validate_ir

    validated = validate_ir.validate_document(document, phase="full")
    assert not validated.report.has_error(), validated.report.to_text()
    return validated


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _graph(components, *, ground=(), vcc=(), vee=(), terminals=()):
    document = {"components": components}
    graph = ElectricalGraph(document=document)
    graph.ground_nets.update(ground)
    graph.vcc_nets.update(vcc)
    graph.vee_nets.update(vee)
    graph.terminal_nets.update({index: net for index, net in enumerate(terminals)})
    dc_types = {"resistor", "inductor", "ammeter", "vsource", "battery"}
    passive_types = {"resistor", "capacitor", "polar_capacitor", "inductor"}
    for component in components:
        nets = {pin["name"]: pin["net"] for pin in component.get("pins", [])}
        graph.component_nets[component["id"]] = nets
        for pin_name, net_name in nets.items():
            graph.component_pin_net[(component["id"], pin_name)] = net_name
            graph.net_pins.setdefault(net_name, []).append(
                (component["id"], pin_name, component["type"])
            )
        if component["type"] == "transformer":
            pairs = [("A1", "A2"), ("B1", "B2")]
        elif set(nets) >= {"1", "2"}:
            pairs = [("1", "2")]
        else:
            pairs = []
        edges = [(nets[left], nets[right]) for left, right in pairs]
        graph.device_edges[component["id"]] = edges
        for left, right in edges:
            if component["type"] in dc_types:
                graph.dc_adjacency.setdefault(left, set()).add(right)
                graph.dc_adjacency.setdefault(right, set()).add(left)
            if component["type"] in passive_types:
                graph.passive_adjacency.setdefault(left, set()).add(right)
                graph.passive_adjacency.setdefault(right, set()).add(left)
    return graph


def _component(component_id, component_type, **pins):
    return {
        "id": component_id,
        "type": component_type,
        "pins": [{"name": name, "net": net} for name, net in pins.items()],
    }


def _codes(report):
    return [finding["code"] for finding in report["findings"]]


def _motifs(report):
    return [motif["code"] for motif in report["motifs"]]


def test_golden_a_passes_and_recognizes_voltage_divider(golden_a):
    from kirchhoff_eye.electrical.audit import audit_validated

    report = audit_validated(_validated(golden_a))

    assert report["verdict"] == "pass"
    assert "M001" in _motifs(report)
    assert not [finding for finding in report["findings"] if finding["severity"] != "info"]


def test_collapsed_ground_and_vcc_is_blocker():
    from kirchhoff_eye.electrical.audit import audit_graph

    report = audit_graph(_graph([], ground={"RAIL"}, vcc={"RAIL"}))

    assert report["verdict"] == "block"
    assert "EA001" in _codes(report)


def test_bypassed_component_and_transformer_winding_are_warnings():
    from kirchhoff_eye.electrical.audit import audit_graph

    report = audit_graph(_graph([
        _component("R1", "resistor", **{"1": "N", "2": "N"}),
        _component("T1", "transformer", A1="P", A2="P", B1="S1", B2="S2"),
    ], ground={"GND"}))

    assert report["verdict"] == "warn"
    assert {"EA102", "EA103"} <= set(_codes(report))


def test_bjt_main_path_collapse_warns_but_diode_connection_is_positive_motif():
    from kirchhoff_eye.electrical.audit import audit_graph

    collapsed = audit_graph(_graph([_component("Q1", "npn", B="NB", C="NC", E="NC")], ground={"GND"}))
    diode_connected = audit_graph(_graph([_component("Q1", "npn", B="NC", C="NC", E="NE")], ground={"GND"}))

    assert "EA104" in _codes(collapsed)
    assert "EA104" not in _codes(diode_connected)
    assert "M004" in _motifs(diode_connected)


def test_mos_main_path_collapse_warns_and_gate_drain_or_source_are_legal_motifs():
    from kirchhoff_eye.electrical.audit import audit_graph

    collapsed = audit_graph(_graph([_component("M1", "nmos", G="NG", D="NX", S="NX")], ground={"GND"}))
    gate_drain = audit_graph(_graph([_component("M1", "nmos", G="ND", D="ND", S="NS")], ground={"GND"}))
    gate_source = audit_graph(_graph([_component("M1", "pmos", G="NS", D="ND", S="NS")], ground={"GND"}))

    assert "EA104" in _codes(collapsed)
    assert "M005" in _motifs(gate_drain)
    assert "M005" in _motifs(gate_source)


def test_two_opamp_outputs_on_one_net_warn():
    from kirchhoff_eye.electrical.audit import audit_graph

    report = audit_graph(_graph([
        _component("U1", "opamp", inn="N1", inp="N2", out="NO"),
        _component("U2", "opamp", inn="N3", inp="N4", out="NO"),
    ], ground={"GND"}))

    assert "EA105" in _codes(report)


def test_floating_control_warns_but_terminal_or_resistor_to_rail_resolves_it():
    from kirchhoff_eye.electrical.audit import audit_graph

    floating = _graph([_component("M1", "nmos", G="NG", D="ND", S="NS")], ground={"GND"})
    external = _graph([_component("M1", "nmos", G="NG", D="ND", S="NS")], ground={"GND"}, terminals=("NG",))
    biased = _graph([
        _component("M1", "nmos", G="NG", D="ND", S="NS"),
        _component("R1", "resistor", **{"1": "NG", "2": "VCC"}),
    ], ground={"GND"}, vcc={"VCC"})

    assert "EA106" in _codes(audit_graph(floating))
    assert "EA106" not in _codes(audit_graph(external))
    assert "EA106" not in _codes(audit_graph(biased))


def test_golden_b_external_input_terminal_prevents_false_floating_base(golden_b):
    from kirchhoff_eye.electrical.audit import audit_validated

    report = audit_validated(_validated(golden_b))

    assert "EA106" not in _codes(report)
    assert report["verdict"] != "block"


def test_synthetic_opamp_recognizes_negative_feedback_without_positive_warning():
    from kirchhoff_eye.electrical.audit import audit_validated

    ir = _load(ROOT / "tests" / "fixtures" / "synthetic_ir" / "14-opamp.json")
    report = audit_validated(_validated(ir))

    assert "M003" in _motifs(report)
    assert "EA107" not in _codes(report)


def test_voltage_follower_is_recognized_and_not_positive_feedback_warning():
    from kirchhoff_eye.electrical.audit import audit_graph

    report = audit_graph(_graph([
        _component("U1", "opamp", inn="NO", inp="NI", out="NO"),
    ], ground={"GND"}, terminals=("NI",)))

    assert "M002" in _motifs(report)
    assert "EA107" not in _codes(report)


def test_positive_feedback_without_negative_path_is_warning_only():
    from kirchhoff_eye.electrical.audit import audit_graph

    graph = _graph([
        _component("U1", "opamp", inn="NN", inp="NP", out="NO"),
        _component("R1", "resistor", **{"1": "NO", "2": "NP"}),
    ], ground={"GND"}, terminals=("NN",))
    report = audit_graph(graph)

    assert report["verdict"] == "warn"
    assert "EA107" in _codes(report)


def test_no_ground_is_info_only_and_does_not_prevent_pass():
    from kirchhoff_eye.electrical.audit import audit_graph

    report = audit_graph(_graph([_component("R1", "resistor", **{"1": "A", "2": "B"})]))

    assert report["verdict"] == "pass"
    assert "EA201" in _codes(report)


def test_coverage_counts_missing_values_for_numeric_component_types():
    from kirchhoff_eye.electrical.audit import audit_graph

    report = audit_graph(_graph([
        _component("R1", "resistor", **{"1": "A", "2": "B"}),
        _component("V1", "vsource", **{"1": "B", "2": "C"}),
        _component("D1", "diode", **{"1": "C", "2": "D"}),
    ], ground={"GND"}))

    assert report["coverage"]["missing_numeric_values"] == 2


def test_findings_motifs_and_ids_are_stable_across_repeated_runs(golden_a):
    from kirchhoff_eye.electrical.audit import audit_validated

    first = audit_validated(_validated(golden_a))
    second = audit_validated(_validated(copy.deepcopy(golden_a)))

    assert first == second
    assert [finding["id"] for finding in first["findings"]] == sorted(
        (finding["id"] for finding in first["findings"]), key=lambda value: (value[:5], int(value.split("-")[1]))
    )
    assert all("-" in motif["id"] for motif in first["motifs"])
