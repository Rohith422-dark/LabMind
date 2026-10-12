"""Small unit-parsing module: free text / (value, unit) -> canonical quantities.

Canonical units: temperature °C, time s, volume µL, speed rpm, mass mg,
concentration mol/L, flow mL/min, percent %, cycles (count), ph.
"""
import re
from dataclasses import dataclass

# unit token (lower-cased, no spaces) -> (kind, factor to canonical, offset)
_UNITS: dict[str, tuple[str, float, float]] = {
    "°c": ("temperature", 1, 0), "c": ("temperature", 1, 0), "degc": ("temperature", 1, 0),
    "℃": ("temperature", 1, 0), "°f": ("temperature", 5 / 9, -32 * 5 / 9), "f": ("temperature", 5 / 9, -32 * 5 / 9),
    "k": ("temperature", 1, -273.15),
    "s": ("time", 1, 0), "sec": ("time", 1, 0), "secs": ("time", 1, 0), "seconds": ("time", 1, 0), "second": ("time", 1, 0),
    "min": ("time", 60, 0), "mins": ("time", 60, 0), "minute": ("time", 60, 0), "minutes": ("time", 60, 0),
    "h": ("time", 3600, 0), "hr": ("time", 3600, 0), "hrs": ("time", 3600, 0), "hour": ("time", 3600, 0), "hours": ("time", 3600, 0),
    "µl": ("volume", 1, 0), "ul": ("volume", 1, 0), "μl": ("volume", 1, 0), "ml": ("volume", 1000, 0), "l": ("volume", 1e6, 0),
    "rpm": ("speed", 1, 0),
    "ug": ("mass", 1e-3, 0), "µg": ("mass", 1e-3, 0), "μg": ("mass", 1e-3, 0), "mg": ("mass", 1, 0),
    "g": ("mass", 1000, 0), "kg": ("mass", 1e6, 0),
    "m": ("concentration", 1, 0), "mm": ("concentration", 1e-3, 0), "µm": ("concentration", 1e-6, 0),
    "μm": ("concentration", 1e-6, 0), "um": ("concentration", 1e-6, 0), "nm": ("concentration", 1e-9, 0),
    "ml/min": ("flow", 1, 0), "µl/min": ("flow", 1e-3, 0), "ul/min": ("flow", 1e-3, 0), "l/min": ("flow", 1000, 0),
    "%": ("percent", 1, 0),
    "cycles": ("cycles", 1, 0), "cycle": ("cycles", 1, 0), "x": ("cycles", 1, 0),
    "ph": ("ph", 1, 0),
}

# default tolerance per kind: ("abs"|"rel"|"exact", amount). Overridable via TOLERANCES.
TOLERANCES: dict[str, tuple[str, float]] = {
    "temperature": ("abs", 1.0), "time": ("rel", 0.10), "volume": ("rel", 0.10), "speed": ("rel", 0.10),
    "mass": ("rel", 0.10), "concentration": ("rel", 0.10), "flow": ("rel", 0.10), "percent": ("rel", 0.10),
    "cycles": ("exact", 0.0), "ph": ("abs", 0.05),
}

_NUM = r"(-?\d+(?:[.,]\d+)?)"
_UNIT = r"(°\s?[CF]|℃|ml/min|[µμu]l/min|l/min|[mM][lL]|[µμu][lL]|[µμu]g|mg|kg|rpm|mins?|minutes?|secs?|seconds?|hrs?|hours?|[µμ]M|nM|mM|cycles?|nm|um|mm|M|g|h|s|L|m|%)"
QTY_RE = re.compile(_NUM + r"\s*" + _UNIT + r"(?![a-zA-Z])", re.I)


@dataclass(frozen=True)
class Quantity:
    kind: str
    value: float          # canonical
    raw: str


def to_canonical(value: float | str, unit: str | None) -> Quantity | None:
    """(value, unit) -> canonical Quantity; None if unit unknown."""
    try:
        v = float(str(value).replace(",", "."))
    except ValueError:
        return None
    key = (unit or "").strip().lower().replace(" ", "")
    if key not in _UNITS:
        # case-sensitive molar units: 'M' vs 'm' collide after lower(); handled by caller via parse()
        return None
    kind, factor, offset = _UNITS[key]
    canon = v * factor + offset if kind == "temperature" and key in ("°f", "f", "k") else v * factor
    if kind == "temperature" and key == "k":
        canon = v - 273.15
    return Quantity(kind, canon, f"{value} {unit}".strip())


def parse(text: str) -> list[Quantity]:
    """Extract all quantities from free text, e.g. '37 °C for 30 min' -> [temp 37, time 1800]."""
    out: list[Quantity] = []
    for m in QTY_RE.finditer(text or ""):
        num, unit = m.group(1), m.group(2)
        # distinguish molar M/mM/µM/nM (case-sensitive) from metre-ish/minute tokens
        if unit in ("m", "mm", "nm", "um"):
            continue  # ambiguous (metre / millimetre / nanometre): never treat as molar
        if unit in ("M", "mM", "µM", "μM", "nM"):
            key = {"M": "m", "mM": "mm", "µM": "µm", "μM": "μm", "nM": "nm"}[unit]
            q = to_canonical(num, key)
        else:
            q = to_canonical(num, unit)
        if q:
            out.append(Quantity(q.kind, q.value, m.group(0)))
    ph = re.search(r"\bpH\s*(\d+(?:\.\d+)?)", text or "", re.I)
    if ph:
        out.append(Quantity("ph", float(ph.group(1)), ph.group(0)))
    return out


def within_tolerance(kind: str, expected: float, actual: float,
                     overrides: dict[str, tuple[str, float]] | None = None) -> bool:
    mode, amt = (overrides or {}).get(kind) or TOLERANCES.get(kind, ("rel", 0.10))
    if mode == "exact":
        return abs(expected - actual) < 1e-9
    if mode == "abs":
        return abs(expected - actual) <= amt + 1e-9
    return abs(expected - actual) <= amt * abs(expected) + 1e-9


def describe_tolerance(kind: str, overrides: dict[str, tuple[str, float]] | None = None) -> str:
    mode, amt = (overrides or {}).get(kind) or TOLERANCES.get(kind, ("rel", 0.10))
    return "exact" if mode == "exact" else (f"±{amt:g}" if mode == "abs" else f"±{amt * 100:g}%")


def fmt(kind: str, value: float) -> str:
    """Human-readable canonical value."""
    if kind == "temperature":
        return f"{value:g} °C"
    if kind == "time":
        return f"{value / 60:g} min" if value >= 60 and value % 60 == 0 else f"{value:g} s"
    if kind == "volume":
        return f"{value / 1000:g} mL" if value >= 1000 else f"{value:g} µL"
    if kind == "speed":
        return f"{value:g} rpm"
    if kind == "mass":
        return f"{value / 1000:g} g" if value >= 1000 else f"{value:g} mg"
    if kind == "cycles":
        return f"{value:g} cycles"
    if kind == "percent":
        return f"{value:g} %"
    if kind == "ph":
        return f"pH {value:g}"
    if kind == "flow":
        return f"{value:g} mL/min"
    if kind == "concentration":
        for f, u in ((1, "M"), (1e-3, "mM"), (1e-6, "µM"), (1e-9, "nM")):
            if value >= f:
                return f"{value / f:g} {u}"
        return f"{value:g} M"
    return f"{value:g}"
