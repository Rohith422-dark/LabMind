from datetime import date

from app.services import intent
from app.services.inventory import lot_status
from app.services.pubchem import parse_ghs
from app.services.sanitizer import sanitize

T = date(2026, 10, 13)


def test_sanitizer_strips_identifiers():
    out = sanitize("Dr. Jane Smith (jane@lab.com) saw lot AB12345 of sample ID XY-998877 failing at 555-123-4567 see https://intranet/x")
    for leaked in ("Jane", "jane@lab.com", "AB12345", "998877", "555-123-4567", "intranet"):
        assert leaked not in out


def test_intent_rules():
    assert intent.classify("Is acetonitrile in stock and when does it expire?") == "inventory"
    assert intent.classify("how do I dilute my stock 1 to 10") == "calculator"
    assert intent.classify("What reagents are needed to calibrate the pH meter?") == "sop"
    assert intent.classify("What causes peak tailing?") == "sop"


def test_followup_rewrite():
    h = [{"role": "user", "content": "How do I calibrate the pH meter?"}, {"role": "assistant", "content": "..."}]
    assert "pH meter" in intent.standalone("and for the third buffer?", h)
    assert intent.standalone("How do I set the oven temperature for the HPLC column?", h).startswith("How do I set")


def test_lot_status_rules():
    assert lot_status(5, 1, date(2027, 1, 1), T) == "green"
    assert lot_status(5, 1, date(2026, 10, 30), T) == "amber"   # expires within 30 days
    assert lot_status(1, 1, date(2027, 1, 1), T) == "amber"     # at reorder level
    assert lot_status(5, 1, date(2026, 10, 12), T) == "red"     # expired
    assert lot_status(0, 1, date(2027, 1, 1), T) == "red"       # out of stock


def test_pubchem_ghs_parser():
    view = {"Record": {"Section": [{"Section": [{"Information": [
        {"Name": "Pictogram(s)", "Value": {"StringWithMarkup": [{"String": " ", "Markup": [{"Extra": "Flammable"}, {"Extra": "Irritant"}]}]}},
        {"Name": "GHS Hazard Statements", "Value": {"StringWithMarkup": [
            {"String": "H225 (100%): Highly Flammable liquid and vapor"}, {"String": "H319 (98.2%): Causes serious eye irritation"}]}}]}]}]}}
    classes, stmts = parse_ghs(view)
    assert classes == ["Flammable", "Irritant"]
    assert stmts == ["H225: Highly Flammable liquid and vapor", "H319: Causes serious eye irritation"]
