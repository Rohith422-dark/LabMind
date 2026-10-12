import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Camera } from "lucide-react";
import { toast } from "sonner";
import { api, type Schemas } from "@/api/client";
import { Banner, Empty, Spinner, StatusBadge, errMsg } from "@/components/ui";
import { StockBar } from "@/components/StockBar";

type Lot = Schemas["LotOut"];
type Req = Schemas["RequestOut"];

export default function AnalystConsole() {
  const [tab, setTab] = useState<"requests" | "stock">("requests");
  return (
    <div>
      <h1 className="mb-4 text-2xl font-bold">Analyst console</h1>
      <div className="mb-4 flex gap-2">
        {([["requests", "Pending requests"], ["stock", "Stock management"]] as const).map(([k, l]) => (
          <button key={k} onClick={() => setTab(k)} className={tab === k ? "btn-primary" : "btn-secondary"}>{l}</button>
        ))}
      </div>
      {tab === "requests" ? <Pending /> : <Stock />}
    </div>
  );
}

function Pending() {
  const qc = useQueryClient();
  const reqs = useQuery({ queryKey: ["pending"], queryFn: () => api<Req[]>("/requests/pending") });
  const lots = useQuery({ queryKey: ["inv-all"], queryFn: () => api<Lot[]>("/inventory") });
  const [pick, setPick] = useState<Record<string, string>>({});
  const [rejecting, setRejecting] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const refresh = () => { void qc.invalidateQueries({ queryKey: ["pending"] }); void qc.invalidateQueries({ queryKey: ["inv-all"] }); void qc.invalidateQueries({ queryKey: ["inv"] }); };

  const issue = useMutation({
    mutationFn: (v: { id: string; lot_id: string }) => api(`/requests/${v.id}/issue`, { method: "POST", json: { lot_id: v.lot_id } }),
    onSuccess: () => { toast.success("Issued. Stock decreased and the requester was notified."); refresh(); },
    onError: (e) => { toast.error(errMsg(e)); refresh(); },
  });
  const reject = useMutation({
    mutationFn: (id: string) => api(`/requests/${id}/reject`, { method: "POST", json: { reason } }),
    onSuccess: () => { toast.success("Request rejected"); setRejecting(null); setReason(""); refresh(); },
    onError: (e) => toast.error(errMsg(e)),
  });

  if (reqs.isLoading) return <Spinner />;
  if (!reqs.data?.length) return <Empty title="No pending requests">Requests raised by scientists appear here.</Empty>;
  return (
    <div className="space-y-4" data-testid="pending-requests">
      {reqs.data.map((r) => {
        // earliest-expiry-first among usable lots that can cover the quantity; expired lots listed but blocked
        const options = (lots.data ?? []).filter((l) => l.reagent_id === r.reagent_id)
          .sort((a, b) => (a.expiry_date ?? "9999").localeCompare(b.expiry_date ?? "9999"));
        const usable = options.filter((l) => l.status !== "red" && l.quantity_available >= r.quantity);
        const chosen = pick[r.id] ?? usable[0]?.lot_id ?? "";
        const sel = options.find((l) => l.lot_id === chosen);
        return (
          <div key={r.id} className="card space-y-3 p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div><span className="font-semibold">{r.reagent_name}</span> — {r.quantity} {r.unit}
                <div className="text-sm text-slate-500">{r.requester_name} · {r.purpose}{r.experiment_ref ? ` (${r.experiment_ref})` : ""} · {new Date(r.created_at).toLocaleString()}</div></div>
              <StatusBadge status={r.status} />
            </div>
            {options.length === 0 ? <Banner tone="red">No lots on record for this reagent.</Banner> : (
              <div className="grid gap-2 md:grid-cols-2">
                {options.map((l) => {
                  const blocked = l.status === "red" || l.quantity_available < r.quantity;
                  return (
                    <label key={l.lot_id} className={`flex cursor-pointer items-start gap-2 rounded-md border p-2 text-sm ${chosen === l.lot_id ? "border-brand-500 bg-brand-50" : "border-slate-200"} ${blocked ? "opacity-60" : ""}`}>
                      <input type="radio" name={`lot-${r.id}`} disabled={blocked} checked={chosen === l.lot_id} onChange={() => setPick({ ...pick, [r.id]: l.lot_id })} />
                      <span className="flex-1"><b>{l.lot_no}</b> · exp {l.expiry_date} <StatusBadge status={l.status} />
                        <StockBar qty={l.quantity_available} capacity={l.capacity} status={l.status} unit={l.unit} />
                        {l.status === "red" && (l.days_remaining ?? 1) <= 0 && <span className="text-xs font-bold text-red-600">EXPIRED — cannot be issued</span>}
                        {l.status === "amber" && l.days_remaining !== null && l.days_remaining !== undefined && l.days_remaining <= 30 && l.days_remaining > 0 && <span className="text-xs text-amber-700">near expiry ({l.days_remaining} d)</span>}
                        {l.quantity_available < r.quantity && l.status !== "red" && <span className="text-xs text-slate-500">not enough stock</span>}
                      </span>
                    </label>
                  );
                })}
              </div>
            )}
            {sel?.status === "amber" && sel.days_remaining !== null && sel.days_remaining !== undefined && sel.days_remaining <= 30 && <Banner tone="amber">This lot expires in {sel.days_remaining} days.</Banner>}
            {rejecting === r.id ? (
              <div className="flex gap-2"><input className="input" placeholder="Reason for rejecting (required)" value={reason} onChange={(e) => setReason(e.target.value)} />
                <button className="btn-danger" disabled={reason.trim().length < 3} onClick={() => reject.mutate(r.id)}>Confirm reject</button>
                <button className="btn-secondary" onClick={() => setRejecting(null)}>Cancel</button></div>
            ) : (
              <div className="flex gap-2">
                <button className="btn-primary" disabled={!chosen || issue.isPending} onClick={() => issue.mutate({ id: r.id, lot_id: chosen })}>Issue from selected lot</button>
                <button className="btn-secondary" onClick={() => setRejecting(r.id)}>Reject…</button>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function Stock() {
  const qc = useQueryClient();
  const lots = useQuery({ queryKey: ["inv-all"], queryFn: () => api<Lot[]>("/inventory") });
  const [adding, setAdding] = useState(false);
  const [act, setAct] = useState<{ lot: Lot; kind: "return" | "adjust" | "dispose" } | null>(null);
  const refresh = () => { void qc.invalidateQueries({ queryKey: ["inv-all"] }); void qc.invalidateQueries({ queryKey: ["inv"] }); };
  return (
    <div>
      <div className="mb-3 flex justify-end"><button className="btn-primary" onClick={() => setAdding(true)}>Add lot</button></div>
      {lots.isLoading && <Spinner />}
      <div className="card overflow-x-auto"><table className="w-full text-left text-sm">
        <thead className="bg-slate-50 text-slate-600"><tr>{["Reagent", "Lot", "Stock", "Expiry", "Status", "Actions"].map((h) => <th key={h} className="px-3 py-2 font-semibold">{h}</th>)}</tr></thead>
        <tbody>{lots.data?.map((l) => (
          <tr key={l.lot_id} className="border-t border-slate-100">
            <td className="px-3 py-2">{l.name}</td><td className="px-3 py-2">{l.lot_no}</td>
            <td className="px-3 py-2"><StockBar qty={l.quantity_available} capacity={l.capacity} status={l.status} unit={l.unit} /></td>
            <td className="px-3 py-2">{l.expiry_date}</td><td className="px-3 py-2"><StatusBadge status={l.status} /></td>
            <td className="px-3 py-2"><div className="flex gap-1">
              <button className="btn-secondary px-2 py-1" onClick={() => setAct({ lot: l, kind: "return" })}>Return</button>
              <button className="btn-secondary px-2 py-1" onClick={() => setAct({ lot: l, kind: "adjust" })}>Adjust</button>
              <button className="btn-secondary px-2 py-1" disabled={l.quantity_available <= 0} onClick={() => setAct({ lot: l, kind: "dispose" })}>Dispose</button></div></td>
          </tr>))}</tbody></table></div>
      {act && <ActionModal {...act} onClose={() => setAct(null)} onDone={() => { setAct(null); refresh(); }} />}
      {adding && <AddLotModal onClose={() => setAdding(false)} onDone={() => { setAdding(false); refresh(); }} />}
    </div>
  );
}

function ActionModal({ lot, kind, onClose, onDone }: { lot: Lot; kind: "return" | "adjust" | "dispose"; onClose: () => void; onDone: () => void }) {
  const [qty, setQty] = useState("");
  const [reason, setReason] = useState("");
  const m = useMutation({
    mutationFn: () => api(`/inventory/lots/${lot.lot_id}/${kind}`, { method: "POST",
      json: kind === "return" ? { quantity: Number(qty), reason: reason || null } : kind === "adjust" ? { new_quantity: Number(qty), reason } : { reason } }),
    onSuccess: () => { toast.success("Recorded"); onDone(); }, onError: (e) => toast.error(errMsg(e)),
  });
  const submit = (e: FormEvent) => { e.preventDefault(); m.mutate(); };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <form onSubmit={submit} className="card w-full max-w-md space-y-3 p-6">
        <h2 className="text-lg font-bold capitalize">{kind} — {lot.name} ({lot.lot_no})</h2>
        {kind !== "dispose" && <div><label className="label">{kind === "return" ? "Quantity returned" : "New quantity"} ({lot.unit})</label>
          <input className="input" type="number" step="any" min="0" required value={qty} onChange={(e) => setQty(e.target.value)} /></div>}
        <div><label className="label">Reason{kind === "return" ? " (optional)" : " (required)"}</label>
          <input className="input" required={kind !== "return"} value={reason} onChange={(e) => setReason(e.target.value)} /></div>
        <div className="flex justify-end gap-2"><button type="button" className="btn-secondary" onClick={onClose}>Cancel</button><button className="btn-primary" disabled={m.isPending}>Confirm</button></div>
      </form>
    </div>
  );
}

function AddLotModal({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const reagents = useQuery({ queryKey: ["reagents"], queryFn: () => api<Schemas["ReagentOut"][]>("/inventory/reagents") });
  const [f, setF] = useState({ reagent_name: "", cas_number: "", lot_no: "", grade: "", capacity: "", quantity_available: "", unit: "", location: "", expiry_date: "", supplier: "" });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const m = useMutation({
    mutationFn: () => api("/inventory/lots", { method: "POST", json: { ...f, capacity: Number(f.capacity), quantity_available: Number(f.quantity_available),
      cas_number: f.cas_number || null, grade: f.grade || null, unit: f.unit || null, location: f.location || null, expiry_date: f.expiry_date || null, supplier: f.supplier || null } }),
    onSuccess: () => { toast.success("Lot added"); onDone(); }, onError: (e) => toast.error(errMsg(e)),
  });
  async function readLabel(file: File) {
    const fd = new FormData(); fd.append("file", file);
    try {
      const r = await api<Schemas["LabelOut"]>("/inventory/lots/label", { method: "POST", body: fd });
      setF((p) => ({ ...p, reagent_name: r.reagent_name || p.reagent_name, cas_number: r.cas_number || p.cas_number, lot_no: r.lot_no || p.lot_no, expiry_date: r.expiry_date || p.expiry_date, supplier: r.supplier || p.supplier }));
      toast.success("Label read — please check every field before saving");
    } catch (e) { toast.error(errMsg(e)); }
  }
  const submit = (e: FormEvent) => { e.preventDefault(); m.mutate(); };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <form onSubmit={submit} className="card max-h-[90vh] w-full max-w-xl space-y-3 overflow-y-auto p-6">
        <h2 className="text-lg font-bold">Add lot</h2>
        <label className="btn-secondary cursor-pointer"><Camera size={16} />Fill from label photo
          <input type="file" accept="image/*" capture="environment" className="hidden" onChange={(e) => e.target.files?.[0] && readLabel(e.target.files[0])} /></label>
        <div className="grid gap-3 md:grid-cols-2">
          <div className="md:col-span-2"><label className="label">Reagent name</label><input list="reagent-list" className="input" required value={f.reagent_name} onChange={set("reagent_name")} />
            <datalist id="reagent-list">{reagents.data?.map((r) => <option key={r.id} value={r.name} />)}</datalist></div>
          <div><label className="label">CAS (new reagents)</label><input className="input" value={f.cas_number} onChange={set("cas_number")} /></div>
          <div><label className="label">Unit</label><input className="input" value={f.unit} onChange={set("unit")} placeholder="L, kg, g…" /></div>
          <div><label className="label">Lot no.</label><input className="input" required value={f.lot_no} onChange={set("lot_no")} /></div>
          <div><label className="label">Grade</label><input className="input" value={f.grade} onChange={set("grade")} /></div>
          <div><label className="label">Capacity</label><input className="input" type="number" step="any" required value={f.capacity} onChange={set("capacity")} /></div>
          <div><label className="label">Quantity available</label><input className="input" type="number" step="any" required value={f.quantity_available} onChange={set("quantity_available")} /></div>
          <div><label className="label">Location</label><input className="input" value={f.location} onChange={set("location")} /></div>
          <div><label className="label">Expiry date</label><input className="input" type="date" value={f.expiry_date} onChange={set("expiry_date")} /></div>
          <div className="md:col-span-2"><label className="label">Supplier</label><input className="input" value={f.supplier} onChange={set("supplier")} /></div>
        </div>
        <div className="flex justify-end gap-2"><button type="button" className="btn-secondary" onClick={onClose}>Cancel</button><button className="btn-primary" disabled={m.isPending}>Save lot</button></div>
      </form>
    </div>
  );
}
