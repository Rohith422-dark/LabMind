import { useState } from "react";

const num = (s: string) => (s.trim() === "" ? NaN : Number(s));
const fmt = (n: number) => (Number.isFinite(n) ? Number(n.toPrecision(6)).toString() : "—");

function Field({ label, value, set, unit }: { label: string; value: string; set: (v: string) => void; unit?: string }) {
  return (
    <div><label className="label">{label}{unit ? ` (${unit})` : ""}</label>
      <input className="input" inputMode="decimal" value={value} onChange={(e) => set(e.target.value)} /></div>
  );
}

function Dilution() {
  const [c1, setC1] = useState(""); const [v1, setV1] = useState(""); const [c2, setC2] = useState(""); const [v2, setV2] = useState("");
  const vals = { c1: num(c1), v1: num(v1), c2: num(c2), v2: num(v2) };
  const missing = Object.entries(vals).filter(([, v]) => Number.isNaN(v)).map(([k]) => k);
  let out = "Fill any three values to solve for the fourth.";
  if (missing.length === 1) {
    const { c1: a, v1: b, c2: c, v2: d } = vals;
    const r = missing[0] === "c1" ? (c * d) / b : missing[0] === "v1" ? (c * d) / a : missing[0] === "c2" ? (a * b) / d : (a * b) / c;
    out = `${missing[0].toUpperCase()} = ${fmt(r)}  (C1·V1 = C2·V2; use consistent units)`;
  }
  return (
    <div className="card space-y-3 p-5"><h2 className="font-semibold">Dilution (C1·V1 = C2·V2)</h2>
      <div className="grid grid-cols-2 gap-3"><Field label="C1 stock conc." value={c1} set={setC1} /><Field label="V1 stock volume" value={v1} set={setV1} />
        <Field label="C2 final conc." value={c2} set={setC2} /><Field label="V2 final volume" value={v2} set={setV2} /></div>
      <div className="rounded-md bg-slate-50 p-3 font-mono text-sm" data-testid="dilution-result">{out}</div></div>
  );
}

function Molarity() {
  const [mw, setMw] = useState(""); const [m, setM] = useState(""); const [v, setV] = useState("");
  const mass = num(mw) * num(m) * num(v);
  return (
    <div className="card space-y-3 p-5"><h2 className="font-semibold">Mass for a molar solution</h2>
      <div className="grid grid-cols-3 gap-3"><Field label="Molecular weight" unit="g/mol" value={mw} set={setMw} /><Field label="Molarity" unit="mol/L" value={m} set={setM} /><Field label="Volume" unit="L" value={v} set={setV} /></div>
      <div className="rounded-md bg-slate-50 p-3 font-mono text-sm">Mass to weigh = {fmt(mass)} g</div></div>
  );
}

function Percent() {
  const [w, setW] = useState(""); const [p, setP] = useState(""); const [v, setV] = useState("");
  const grams = (num(p) / 100) * num(v);
  return (
    <div className="card space-y-3 p-5"><h2 className="font-semibold">% (w/v) solution</h2>
      <div className="grid grid-cols-3 gap-3"><Field label="Target" unit="% w/v" value={p} set={setP} /><Field label="Final volume" unit="mL" value={v} set={setV} /><Field label="Purity (optional)" unit="%" value={w} set={setW} /></div>
      <div className="rounded-md bg-slate-50 p-3 font-mono text-sm">Solute = {fmt(num(w) > 0 ? grams / (num(w) / 100) : grams)} g in {fmt(num(v))} mL</div></div>
  );
}

export default function Calculators() {
  return (
    <div className="space-y-4"><h1 className="text-2xl font-bold">Calculators</h1>
      <p className="text-sm text-slate-600">Quick arithmetic helpers. Always double-check against your approved method before use.</p>
      <div className="grid gap-4 lg:grid-cols-3"><Dilution /><Molarity /><Percent /></div></div>
  );
}
