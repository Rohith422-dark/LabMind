import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, type Schemas } from "@/api/client";
import { useAuth } from "@/context/AuthContext";
import { Empty, HazardBadges, Spinner, StatusBadge, errMsg } from "@/components/ui";
import { StockBar } from "@/components/StockBar";

type Lot = Schemas["LotOut"];

export default function Inventory() {
  const { can } = useAuth();
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [status, setStatus] = useState("");
  const [hazard, setHazard] = useState("");
  const [soon, setSoon] = useState(false);
  const [req, setReq] = useState<Lot | null>(null);
  const qs = new URLSearchParams();
  if (name) qs.set("name", name);
  if (status) qs.set("status", status);
  if (hazard) qs.set("hazard", hazard);
  if (soon) qs.set("expiring_soon", "true");
  const lots = useQuery({ queryKey: ["inv", name, status, hazard, soon], queryFn: () => api<Lot[]>(`/inventory?${qs}`) });

  return (
    <div>
      <h1 className="mb-4 text-2xl font-bold">Inventory</h1>
      <div className="card mb-4 grid gap-3 p-4 md:grid-cols-5">
        <input className="input md:col-span-2" placeholder="Reagent, CAS or lot…" value={name} onChange={(e) => setName(e.target.value)} />
        <select className="input" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">Any status</option><option value="green">In stock</option><option value="amber">Low / expiring</option><option value="red">Expired / out</option></select>
        <input className="input" placeholder="Hazard (e.g. flammable, H225)" value={hazard} onChange={(e) => setHazard(e.target.value)} />
        <label className="flex items-center gap-2 text-sm text-slate-600"><input type="checkbox" checked={soon} onChange={(e) => setSoon(e.target.checked)} />Expiring ≤ 30 days</label>
      </div>
      {lots.isLoading && <Spinner label="Loading inventory…" />}
      {lots.data?.length === 0 && <Empty title="No lots match these filters" />}
      {!!lots.data?.length && (
        <div className="card overflow-x-auto">
          <table className="w-full text-left text-sm" data-testid="inventory-table">
            <thead className="bg-slate-50 text-slate-600"><tr>
              {["Reagent", "Lot / grade", "Stock", "Location", "Expiry", "Hazards", "Status", ""].map((h) => <th key={h} className="px-3 py-2 font-semibold">{h}</th>)}</tr></thead>
            <tbody>
              {lots.data.map((l) => (
                <tr key={l.lot_id} className="border-t border-slate-100 align-top">
                  <td className="px-3 py-2"><div className="font-medium">{l.name}</div><div className="text-xs text-slate-500">{l.cas_number ?? "no CAS"} · {l.formula ?? ""}</div></td>
                  <td className="px-3 py-2"><div>{l.lot_no}</div><div className="text-xs text-slate-500">{l.grade}</div></td>
                  <td className="px-3 py-2"><StockBar qty={l.quantity_available} capacity={l.capacity} status={l.status} unit={l.unit} />
                    {l.reorder_level !== null && l.reorder_level !== undefined && <div className="text-xs text-slate-400">reorder ≤ {l.reorder_level}</div>}</td>
                  <td className="px-3 py-2"><div>{l.location}</div><div className="text-xs text-slate-500">{l.storage_conditions}</div></td>
                  <td className="px-3 py-2 whitespace-nowrap">{l.expiry_date}<div className={`text-xs ${(l.days_remaining ?? 99) <= 0 ? "font-bold text-red-600" : (l.days_remaining ?? 99) <= 30 ? "text-amber-700" : "text-slate-500"}`}>
                    {l.days_remaining === null || l.days_remaining === undefined ? "" : l.days_remaining <= 0 ? `expired ${-l.days_remaining} d ago` : `${l.days_remaining} d left`}</div></td>
                  <td className="px-3 py-2"><div className="flex max-w-[11rem] flex-wrap gap-1"><HazardBadges classes={l.hazard_classes ?? []} /></div></td>
                  <td className="px-3 py-2"><StatusBadge status={l.status} /></td>
                  <td className="px-3 py-2">{can("requests.create") && <button className="btn-secondary px-3 py-1" disabled={l.status === "red"} onClick={() => setReq(l)}>Request</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {req && <RequestModal lot={req} onClose={() => setReq(null)} onDone={() => { setReq(null); void qc.invalidateQueries({ queryKey: ["myreq"] }); }} />}
    </div>
  );
}

function RequestModal({ lot, onClose, onDone }: { lot: Lot; onClose: () => void; onDone: () => void }) {
  const [qty, setQty] = useState("");
  const [purpose, setPurpose] = useState("");
  const [ref, setRef] = useState("");
  const m = useMutation({
    mutationFn: () => api("/requests", { method: "POST", json: { reagent_id: lot.reagent_id, quantity: Number(qty), purpose, experiment_ref: ref || null } }),
    onSuccess: () => { toast.success("Request raised. A Lab Analyst will review it."); onDone(); },
    onError: (e) => toast.error(errMsg(e)),
  });
  const submit = (e: FormEvent) => { e.preventDefault(); m.mutate(); };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <form onSubmit={submit} className="card w-full max-w-md space-y-3 p-6">
        <h2 className="text-lg font-bold">Request {lot.name}</h2>
        <div><label className="label">Quantity ({lot.unit})</label><input className="input" type="number" step="any" min="0" required value={qty} onChange={(e) => setQty(e.target.value)} /></div>
        <div><label className="label">Purpose</label><input className="input" required value={purpose} onChange={(e) => setPurpose(e.target.value)} /></div>
        <div><label className="label">Experiment reference</label><input className="input" value={ref} onChange={(e) => setRef(e.target.value)} /></div>
        <div className="flex justify-end gap-2"><button type="button" className="btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn-primary" disabled={m.isPending || !Number(qty)}>Raise request</button></div>
      </form>
    </div>
  );
}
