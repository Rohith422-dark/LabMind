"""Reagent master data from PubChem PUG REST / PUG View (free, public). CID kept as provenance."""
import asyncio
import re

import httpx

BASE = "https://pubchem.ncbi.nlm.nih.gov/rest"
HCODE = re.compile(r"^(H\d{3}[A-Za-z]*)\s*(?:\([^)]*\))?\s*:?\s*(.*)$")


def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def parse_ghs(view: dict) -> tuple[list[str], list[str]]:
    """(hazard_classes, hazard_statements) from a PUG View GHS Classification record."""
    classes: list[str] = []
    stmts: dict[str, str] = {}
    for d in _walk(view):
        name = d.get("Name")
        if name == "Pictogram(s)":
            for sv in d.get("Value", {}).get("StringWithMarkup", []):
                for m in sv.get("Markup", []):
                    extra = m.get("Extra")
                    if extra and extra not in classes:
                        classes.append(extra)
        elif name == "GHS Hazard Statements":
            for sv in d.get("Value", {}).get("StringWithMarkup", []):
                m = HCODE.match(sv.get("String", "").strip())
                if m and m.group(1) not in stmts:
                    stmts[m.group(1)] = m.group(2).strip()
    return classes, [f"{c}: {t}" if t else c for c, t in sorted(stmts.items())]


async def fetch(client: httpx.AsyncClient, cas: str) -> dict | None:
    """Look up a reagent by CAS number. Returns None if PubChem has no match."""
    r = await client.get(f"{BASE}/pug/compound/name/{cas}/cids/JSON")
    if r.status_code != 200:
        return None
    cid = r.json()["IdentifierList"]["CID"][0]
    await asyncio.sleep(0.25)
    p = await client.get(f"{BASE}/pug/compound/cid/{cid}/property/MolecularFormula,Title/JSON")
    props = p.json()["PropertyTable"]["Properties"][0] if p.status_code == 200 else {}
    await asyncio.sleep(0.25)
    g = await client.get(f"{BASE}/pug_view/data/compound/{cid}/JSON", params={"heading": "GHS Classification"})
    classes, stmts = parse_ghs(g.json()) if g.status_code == 200 else ([], [])
    await asyncio.sleep(0.25)
    return {"cid": cid, "formula": props.get("MolecularFormula"), "title": props.get("Title"),
            "hazard_classes": classes, "hazard_statements": stmts}
