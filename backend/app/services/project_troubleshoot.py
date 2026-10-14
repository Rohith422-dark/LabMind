"""Deterministic comparison of one experiment against the rest of its project.

Everything here is computed from recorded numbers - no model involved - so a figure the assistant quotes can always be
traced to experiment records (ids + versions are attached to every finding). The output deliberately separates:
  observed   facts read straight from the records or arithmetic on them
  hypotheses patterns worth checking, never causes: "differs between successful and failed runs" is a correlation
  unknown    data the target experiment does not contain that comparable experiments do
"""
import statistics
from typing import Any

MIN_HISTORY = 3          # need this many comparable earlier values before calling something unusual
Z_UNUSUAL = 2.5
DIFF_PCT = 10.0


def _key(name: str) -> str:
    return " ".join(str(name).lower().split())


def _numeric(exp: dict) -> dict[str, tuple[float, str]]:
    out: dict[str, tuple[float, str]] = {}
    for p in exp.get("parameters") or []:
        v = p.get("value")
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[_key(p.get("name", ""))] = (float(v), (p.get("unit") or "").strip())
    return out


def _ref(e: dict) -> dict:
    return {"id": str(e["id"]), "identifier": e["identifier"], "version": e["version"], "outcome": e.get("outcome")}


def _items(e: dict) -> set[str]:
    s = {f"reagent:{_key(r.get('name', ''))}" for r in e.get("reagents") or [] if r.get("name")}
    s |= {f"equipment:{_key(x.get('name', x) if isinstance(x, dict) else x)}" for x in e.get("equipment") or []}
    s |= {f"condition:{_key(k)}={_key(v)}" for k, v in (e.get("conditions") or {}).items()}
    return s


def analyse(target: dict, others: list[dict]) -> dict[str, Any]:
    others = [o for o in others if str(o["id"]) != str(target["id"]) and not o.get("voided")]
    tnum = _numeric(target)
    onum = [(o, _numeric(o)) for o in others]

    parameters = []
    for name, (val, unit) in tnum.items():
        hist = [(o, n[name][0]) for o, n in onum if name in n and n[name][1] == unit]
        other_units = sorted({n[name][1] for _, n in onum if name in n and n[name][1] != unit})
        row: dict[str, Any] = {"parameter": name, "value": val, "unit": unit, "history_count": len(hist),
                               "flags": [], "history_refs": [_ref(o) for o, _ in hist][:10]}
        if other_units:
            row["flags"].append(f"other experiments record this in different units ({', '.join(u or 'none' for u in other_units)}); not compared")
        if hist:
            vals = [v for _, v in hist]
            mean = statistics.fmean(vals)
            row.update(min=min(vals), max=max(vals), mean=round(mean, 6))
            if len(vals) >= 2:
                sd = statistics.stdev(vals)
                row["stdev"] = round(sd, 6)
            if len(vals) >= MIN_HISTORY:
                if val < min(vals) or val > max(vals):
                    row["flags"].append("outside the range of all earlier recorded values")
                sd = statistics.pstdev(vals)
                if sd > 0 and abs(val - mean) / sd >= Z_UNUSUAL:
                    row["flags"].append(f"{abs(val - mean) / sd:.1f} standard deviations from the earlier mean")
            if mean:
                row["pct_from_mean"] = round((val - mean) / abs(mean) * 100, 1)
        else:
            row["flags"].append("no comparable earlier measurement of this parameter (same name and unit)")
        parameters.append(row)

    t_items = _items(target)
    similar = []
    for o in others:
        oi = _items(o)
        if t_items and oi:
            j = len(t_items & oi) / len(t_items | oi)
            if j > 0:
                similar.append({**_ref(o), "similarity": round(j, 2), "shared": sorted(t_items & oi)[:8],
                                "differs": sorted(t_items ^ oi)[:8]})
    similar.sort(key=lambda x: x["similarity"], reverse=True)

    pool = onum + [(target, tnum)]          # the experiment under investigation belongs to its own outcome group
    succ = [(o, n) for o, n in pool if o.get("outcome") == "success"]
    fail = [(o, n) for o, n in pool if o.get("outcome") == "failure"]
    contrast = []
    if succ and fail:
        names = {k for _, n in succ + fail for k in n}
        for name in sorted(names):
            for unit in {n[name][1] for _, n in succ + fail if name in n}:
                s = [n[name][0] for _, n in succ if name in n and n[name][1] == unit]
                f = [n[name][0] for _, n in fail if name in n and n[name][1] == unit]
                if s and f:
                    ms, mf = statistics.fmean(s), statistics.fmean(f)
                    base = abs((ms + mf) / 2)
                    pct = abs(ms - mf) / base * 100 if base else (100.0 if ms != mf else 0.0)
                    if pct >= DIFF_PCT:
                        contrast.append({"parameter": name, "unit": unit, "mean_successful": round(ms, 6),
                                         "mean_failed": round(mf, 6), "n_successful": len(s), "n_failed": len(f),
                                         "difference_pct": round(pct, 1)})

    counts: dict[str, int] = {}
    for _, n in onum:
        for k in n:
            counts[k] = counts.get(k, 0) + 1
    need = max(2, len(onum) // 2) if onum else 0
    missing = sorted(k for k, c in counts.items() if c >= need and k not in tnum) if onum else []

    observed = []
    for r in parameters:
        if r["history_count"]:
            observed.append(f"{r['parameter']} = {r['value']:g}{(' ' + r['unit']) if r['unit'] else ''}; earlier experiments "
                            f"recorded {r['min']:g}-{r['max']:g}{(' ' + r['unit']) if r['unit'] else ''} "
                            f"(n={r['history_count']}, mean {r['mean']:g})")
    hypotheses = [f"{c['parameter']} averaged {c['mean_successful']:g} in successful runs vs {c['mean_failed']:g} in failed runs "
                  f"({c['difference_pct']:g}% apart, n={c['n_successful']}/{c['n_failed']}). This is a correlation in the "
                  "records, not an established cause." for c in contrast]
    unknown = [f"'{m}' is recorded in most comparable experiments but not in this one." for m in missing]
    return {"experiment": _ref(target), "compared_with": len(others), "parameters": parameters, "similar_experiments": similar[:5],
            "success_vs_failure": contrast, "missing_parameters": missing,
            "observed": observed, "hypotheses": hypotheses, "unknown": unknown,
            "caution": "Correlation in recorded data does not establish a cause."}


def as_passage_text(a: dict) -> str:
    """Prose form of an analysis, so the same validation rules (numbers must appear in the cited text) apply in chat."""
    t = a["experiment"]
    lines = [f"Computed comparison of experiment {t['identifier']} (record v{t['version']}) with {a['compared_with']} other "
             "experiments in this project, calculated from the recorded values."]
    lines += [o + "." for o in a["observed"]]
    for r in a["parameters"]:
        for f in r["flags"]:
            lines.append(f"Flag for {r['parameter']}: {f}.")
    for s in a["similar_experiments"]:
        lines.append(f"Experiment {s['identifier']} (outcome {s['outcome']}) is similar: similarity {s['similarity']:g}.")
    lines += a["hypotheses"] + a["unknown"]
    return " ".join(lines)
