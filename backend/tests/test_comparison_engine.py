import pytest

from app.services import units
from app.services.troubleshoot_engine import (
    CONFIRM, DEVIATION, FOLLOWED, MISSING, OUT_OF_ORDER, clarifying_questions, compare,
    heuristic_align, heuristic_structure, longest_increasing_subsequence,
)

# Synthetic SOP used ONLY for tests (test fixtures never reach the demo DB).
SOP = [
    {"step_no": 1, "action": "Prepare mobile phase and degas", "parameters": {}, "is_critical": False},
    {"step_no": 2, "action": "Equilibrate column", "parameters": {"time": {"value": 30, "unit": "min"}}, "is_critical": True},
    {"step_no": 3, "action": "Set column oven temperature", "parameters": {"temperature": {"value": 40, "unit": "°C"}}, "is_critical": True},
    {"step_no": 4, "action": "Inject sample", "parameters": {"volume": {"value": 10, "unit": "µL"}}, "is_critical": False},
    {"step_no": 5, "action": "Run gradient", "parameters": {"cycles": {"value": 3, "unit": None}}, "is_critical": False},
]


def N(order, action, no, **params):
    return {"order": order, "action": action, "aligned_step_no": no, "parameters": params}


@pytest.mark.parametrize("text,kind,value", [
    ("37 °C", "temperature", 37), ("98 ℃", "temperature", 98), ("30 min", "time", 1800), ("2 h", "time", 7200),
    ("90 s", "time", 90), ("10 µL", "volume", 10), ("0.5 mL", "volume", 500), ("12000 rpm", "speed", 12000),
    ("5 mg", "mass", 5), ("2 g", "mass", 2000), ("5 mM", "concentration", 0.005), ("1.0 mL/min", "flow", 1.0),
])
def test_unit_parsing(text, kind, value):
    q = units.parse(text)
    assert len(q) == 1 and q[0].kind == kind and q[0].value == pytest.approx(value)


def test_ambiguous_lowercase_mm_is_not_molar():
    assert units.parse("a 4.6 mm column") == []


def test_tolerances():
    assert units.within_tolerance("temperature", 40, 40.9)
    assert not units.within_tolerance("temperature", 40, 41.5)
    assert units.within_tolerance("time", 1800, 1900)        # +5.5 %
    assert not units.within_tolerance("time", 1800, 1200)    # -33 %
    assert units.within_tolerance("cycles", 3, 3)
    assert not units.within_tolerance("cycles", 3, 4)
    assert units.within_tolerance("time", 100, 120, {"time": ("rel", 0.25)})


def test_lis():
    seq = [1, 3, 2, 4]
    keep = longest_increasing_subsequence(seq)
    assert len(keep) == 3 and {seq[i] for i in keep} in ({1, 3, 4}, {1, 2, 4})
    assert longest_increasing_subsequence([]) == set()


def test_all_followed():
    narr = [
        N(1, "prepared and degassed mobile phase", 1),
        N(2, "equilibrated 30 min", 2, time={"value": 30, "unit": "min"}),
        N(3, "oven at 40 C", 3, temperature={"value": 40, "unit": "°C"}),
        N(4, "injected 10 uL", 4, volume={"value": 10, "unit": "µL"}),
        N(5, "ran gradient 3 cycles", 5, cycles={"value": 3, "unit": None}),
    ]
    assert [r.status for r in compare(SOP, narr)] == [FOLLOWED] * 5


def test_missing_and_deviation_scenario():
    narr = [
        N(1, "prepared mobile phase", 1),
        N(2, "equilibrated 10 min", 2, time={"value": 10, "unit": "min"}),   # deviation (critical)
        # step 3 omitted -> missing (critical)
        N(3, "injected 10 uL", 4, volume={"value": 10, "unit": "µL"}),
        N(4, "ran gradient", 5),                                              # cycles unstated -> confirm
    ]
    rows = {r.step_no: r for r in compare(SOP, narr)}
    assert rows[2].status == DEVIATION and rows[2].is_critical
    f = rows[2].findings[0]
    assert (f.expected_text, f.actual_text) == ("30 min", "10 min")
    assert rows[3].status == MISSING
    assert rows[4].status == FOLLOWED
    assert rows[5].status == CONFIRM


def test_out_of_order():
    narr = [N(1, "a", 1), N(2, "b", 4, volume={"value": 10, "unit": "µL"}), N(3, "c", 2, time={"value": 30, "unit": "min"}),
            N(4, "d", 3, temperature={"value": 40, "unit": "°C"}), N(5, "e", 5, cycles={"value": 3, "unit": None})]
    rows = {r.step_no: r for r in compare(SOP, narr)}
    assert rows[4].status == OUT_OF_ORDER


def test_extra_step_flagged():
    rows = compare(SOP, [N(1, "did something unusual", None)])
    extra = [r for r in rows if r.step_no is None]
    assert len(extra) == 1 and extra[0].status == DEVIATION


def test_questions_only_for_missing_or_confirm_max_three_critical_first():
    rows = compare(SOP, [N(1, "prepared", 1)])
    qs = clarifying_questions(rows)
    assert len(qs) == 3 and qs[0]["step_no"] in (2, 3)
    assert all(q["key"].startswith(("missing", "confirm")) for q in qs)
    again = clarifying_questions(rows, asked={q["key"] for q in qs})
    assert {q["key"] for q in again}.isdisjoint({q["key"] for q in qs})


def test_heuristic_pipeline_end_to_end():
    text = "I made and degassed the mobile phase. Equilibrated the column for 10 min. Injected 10 uL of sample."
    narr = heuristic_align(SOP, heuristic_structure(text))
    rows = {r.step_no: r for r in compare(SOP, narr)}
    assert rows[2].status == DEVIATION
    assert rows[3].status == MISSING
