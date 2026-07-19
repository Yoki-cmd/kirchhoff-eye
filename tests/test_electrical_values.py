# -*- coding: utf-8 -*-
"""Safe, deliberately narrow component-value parsing."""
import math

import pytest


@pytest.mark.parametrize(
    "text, expected_value, expected_unit",
    [
        (r"6\mathrm{V}", 6.0, "V"),
        (r"+12\mathrm{V}", 12.0, "V"),
        (r"4.7\mathrm{k}\Omega", 4700.0, "Ohm"),
        (r"100\mathrm{nF}", 1e-7, "F"),
        ("1mV", 1e-3, "V"),
        ("1MV", 1e6, "V"),
        ("2.2 µF", 2.2e-6, "F"),
        ("3 μA", 3e-6, "A"),
    ],
)
def test_parse_supported_numeric_values(text, expected_value, expected_unit):
    from kirchhoff_eye.electrical.values import parse_value

    parsed = parse_value(text)

    assert parsed.status == "known"
    assert parsed.unit == expected_unit
    assert math.isclose(parsed.value, expected_value, rel_tol=1e-12, abs_tol=1e-15)


@pytest.mark.parametrize("value", [None, "", "   "])
def test_missing_values_remain_missing(value):
    from kirchhoff_eye.electrical.values import parse_value

    parsed = parse_value(value)

    assert parsed.status == "missing"
    assert parsed.value is None
    assert parsed.unit is None


@pytest.mark.parametrize(
    "value",
    [
        r"\input{secret}",
        r"1\frac{1}{2}V",
        "not-a-value",
        "NaN V",
        "+Inf V",
        "1e309 V",
        "1m",  # prefix without a base unit is intentionally ambiguous
        "1vv",
    ],
)
def test_unsupported_or_unsafe_values_are_unparsed(value):
    from kirchhoff_eye.electrical.values import parse_value

    parsed = parse_value(value)

    assert parsed.status == "unparsed"
    assert parsed.value is None
    assert parsed.unit is None


def test_parser_preserves_original_text_for_coverage_reporting():
    from kirchhoff_eye.electrical.values import parse_value

    assert parse_value(r"4.7\mathrm{k}\Omega").raw == r"4.7\mathrm{k}\Omega"
    assert parse_value(None).raw is None
