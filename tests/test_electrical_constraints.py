# -*- coding: utf-8 -*-
"""Known independent ideal-voltage constraints catch only narrow contradictions."""
from kirchhoff_eye.electrical.models import ElectricalGraph


def _graph(sources):
    document = {"components": []}
    graph = ElectricalGraph(document=document)
    for component_id, from_net, to_net, value in sources:
        component = {
            "id": component_id,
            "type": "vsource",
            "pins": [{"name": "1", "net": from_net}, {"name": "2", "net": to_net}],
        }
        if value is not None:
            component["value"] = value
        document["components"].append(component)
        graph.component_nets[component_id] = {"1": from_net, "2": to_net}
    return graph


def _by_code(findings, code):
    return [finding for finding in findings if finding["code"] == code]


def test_nonzero_known_voltage_source_shorted_is_blocker():
    from kirchhoff_eye.electrical.constraints import audit_voltage_constraints

    findings = audit_voltage_constraints(_graph([("V1", "N1", "N1", r"6\mathrm{V}")]))

    assert len(_by_code(findings, "EA002")) == 1
    assert _by_code(findings, "EA002")[0]["severity"] == "blocker"


def test_different_parallel_voltage_sources_are_conflicting_constraints():
    from kirchhoff_eye.electrical.constraints import audit_voltage_constraints

    findings = audit_voltage_constraints(_graph([
        ("V1", "GND", "N1", "5V"),
        ("V2", "GND", "N1", "6V"),
    ]))

    conflict = _by_code(findings, "EA003")[0]
    assert conflict["component_ids"] == ["V1", "V2"]
    assert conflict["net_names"] == ["GND", "N1"]


def test_inconsistent_three_source_loop_cites_entire_constraint_path():
    from kirchhoff_eye.electrical.constraints import audit_voltage_constraints

    findings = audit_voltage_constraints(_graph([
        ("V1", "A", "B", "5V"),
        ("V2", "B", "C", "5V"),
        ("V3", "C", "A", "1V"),
    ]))

    conflict = _by_code(findings, "EA003")[0]
    assert conflict["component_ids"] == ["V1", "V2", "V3"]
    assert conflict["net_names"] == ["A", "B", "C"]


def test_identical_parallel_voltage_sources_are_warning_not_blocker():
    from kirchhoff_eye.electrical.constraints import audit_voltage_constraints

    findings = audit_voltage_constraints(_graph([
        ("V1", "GND", "N1", "5V"),
        ("V2", "GND", "N1", "5V"),
    ]))

    duplicate = _by_code(findings, "EA101")[0]
    assert duplicate["severity"] == "warning"
    assert not _by_code(findings, "EA003")


def test_unknown_or_unparsed_shorted_source_is_warning_not_blocker():
    from kirchhoff_eye.electrical.constraints import audit_voltage_constraints

    findings = audit_voltage_constraints(_graph([
        ("V1", "N1", "N1", None),
        ("V2", "N2", "N2", r"\input{bad}"),
    ]))

    assert len(_by_code(findings, "EA108")) == 2
    assert not _by_code(findings, "EA002")


def test_from_is_negative_and_to_is_positive_for_constraint_polarity():
    from kirchhoff_eye.electrical.constraints import audit_voltage_constraints

    findings = audit_voltage_constraints(_graph([
        ("V1", "A", "B", "5V"),
        ("V2", "B", "A", "-5V"),
    ]))

    assert len(_by_code(findings, "EA101")) == 1
    assert not _by_code(findings, "EA003")


def test_battery_is_also_an_independent_ideal_voltage_constraint():
    from kirchhoff_eye.electrical.constraints import audit_voltage_constraints

    graph = _graph([("BT1", "GND", "N1", "9V"), ("V2", "GND", "N1", "12V")])
    graph.document["components"][0]["type"] = "battery"

    assert len(_by_code(audit_voltage_constraints(graph), "EA003")) == 1


def test_consistent_multi_source_loop_is_not_mislabeled_as_parallel_sources():
    from kirchhoff_eye.electrical.constraints import audit_voltage_constraints

    findings = audit_voltage_constraints(_graph([
        ("V1", "A", "B", "5V"),
        ("V2", "B", "C", "5V"),
        ("V3", "A", "C", "10V"),
    ]))

    assert not _by_code(findings, "EA003")
    assert not _by_code(findings, "EA101")


def test_non_voltage_units_never_enter_ideal_voltage_constraints():
    from kirchhoff_eye.electrical.constraints import audit_voltage_constraints

    for wrong_unit in ("5A", "5F", "5H", r"5\Omega"):
        findings = audit_voltage_constraints(_graph([
            ("V1", "GND", "N1", wrong_unit),
            ("V2", "GND", "N1", "6V"),
        ]))

        assert not _by_code(findings, "EA002")
        assert not _by_code(findings, "EA003")
        assert not _by_code(findings, "EA101")
