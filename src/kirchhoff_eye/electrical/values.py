"""Safe parsing for the small numeric/unit language used by circuit IR values."""
import math
import re
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ParsedValue:
    status: str
    raw: Optional[str]
    value: Optional[float] = None
    unit: Optional[str] = None


_PREFIXES = {
    "": 1.0,
    "p": 1e-12,
    "n": 1e-9,
    "u": 1e-6,
    "µ": 1e-6,
    "μ": 1e-6,
    "m": 1e-3,
    "k": 1e3,
    "M": 1e6,
    "G": 1e9,
}
_UNITS = {
    "V": "V",
    "A": "A",
    "F": "F",
    "H": "H",
    "Ohm": "Ohm",
}
_NUMBER_RE = r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"
_VALUE_RE = re.compile(
    r"^(?P<number>" + _NUMBER_RE + r")(?P<prefix>[pnuµμmkMG]?)(?P<unit>V|A|F|H|Ohm)$"
)


def _normalize(text: str) -> Optional[str]:
    if any(ord(char) < 32 for char in text):
        return None
    normalized = "".join(text.split())
    normalized = re.sub(r"\\mathrm\{([pnuµμmkMG]?)(V|A|F|H)\}", r"\1\2", normalized)
    normalized = re.sub(r"\\mathrm\{([pnuµμmkMG]?)\}", r"\1", normalized)
    normalized = re.sub(r"\\mathrm\{(V|A|F|H)\}", r"\1", normalized)
    normalized = normalized.replace(r"\Omega", "Ohm")
    if "\\" in normalized or "{" in normalized or "}" in normalized:
        return None
    return normalized


def parse_value(raw: Optional[str]) -> ParsedValue:
    """Parse a finite numeric value without evaluating TeX or expressions."""
    if raw is None or not isinstance(raw, str) or not raw.strip():
        return ParsedValue("missing", raw)
    normalized = _normalize(raw)
    if normalized is None:
        return ParsedValue("unparsed", raw)
    match = _VALUE_RE.fullmatch(normalized)
    if match is None:
        return ParsedValue("unparsed", raw)
    try:
        number = float(match.group("number"))
        value = number * _PREFIXES[match.group("prefix")]
    except (KeyError, ValueError, OverflowError):
        return ParsedValue("unparsed", raw)
    if not math.isfinite(value):
        return ParsedValue("unparsed", raw)
    return ParsedValue("known", raw, value, _UNITS[match.group("unit")])
