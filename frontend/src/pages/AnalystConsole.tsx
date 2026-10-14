import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Camera } from "lucide-react";
import { toast } from "sonner";
import { api, type Schemas } from "@/api/client";
import { Banner, Empty, Spinner, StatusBadge, errMsg } from "@/components/ui";
import { StockBar } from "@/components/StockBar";
import { ManageRequests } from "@/components/ManageRequests";

type Lot = Schemas["LotOut"];

export default function AnalystConsole() {
  const [tab, setTab] = useState<"requests" | "stock">("requests");
  return (
    <div>
      <h1 className="mb-4 text-[26px] font-semibold leading-tight">Lab assistant console</h1>
      <div className="mb-4 flex gap-2">
        {([["requests", "Manage requests"], ["stock", "Stock management"]] as const).map(([k, l]) => (
          <button key={k} onClick={() => setTab(k)} className={tab === k ? "btn-primary" : "btn-secondary"}>{l}</button>
        ))}
      </div>
      {tab === "requests" ? <ManageRequests /> : <Stock />}
    </div>
  );
}

function Stock() {
  const qc = useQueryClient();
  const lots = useQuery({ queryKey: ["inv-all"], queryFn: () => api<Lot[]>("/inventory") });
  const [adding, setAdding] = useState(false);
  const [act, setAct] = useState<{ lot: Lot; kind: "return" | "adjust" | "dispose" | "receive" } | null>(null);
  const [editLot, setEditLot] = useState<Lot | null>(null);
  const refresh = () => { void qc.invalidateQueries({ queryKey: ["inv-all"] }); void qc.invalidateQueries({ queryKey: ["inv"] }); };
  return (
    <div>
      <div className="mb-3 flex justify-end"><button className="btn-primary" onClick={() => setAdding(true)}>Add lot</button></div>
      {lots.isLoading && <Spinner />}
      <div className="card overflow-x-auto"><table className="w-full text-left text-sm">
        <thead className="bg-slate-50 text-slate-600"><tr>{["Reagent", "Lot", "Stock", "Usable / reserved", "Expiry", "Status", "Actions"].map((h) => <th key={h} className="px-3 py-2 font-semibold">{h}</th>)}</tr></thead>
        <tbody>{lots.data?.map((l) => (
          <tr key={l.lot_id} className="border-t border-slate-100">
            <td className="px-3 py-2">{l.name}</td><td className="px-3 py-2">{l.lot_no}</td>
            <td className="px-3 py-2"><StockBar qty={l.quantity_available} capacity={l.capacity} status={l.status} unit={l.unit} /></td>
            <td className="px-3 py-2 text-xs">usable <b>{l.usable_quantity}</b> · reserved {l.reserved_quantity}{l.availability !== "active" && <div className="font-semibold text-red-700">{l.availability}</div>}</td>
            <td className="px-3 py-2">{l.expiry_date}</td><td className="px-3 py-2"><StatusBadge status={l.status} /></td>
            <td className="px-3 py-2"><div className="flex flex-wrap gap-1">
              <button className="btn-secondary px-2 py-1" onClick={() => setAct({ lot: l, kind: "receive" })}>Receive</button>
              <button className="btn-secondary px-2 py-1" onClick={() => setEditLot(l)}>Edit</button>
              <button className="btn-secondary px-2 py-1" onClick={() => setAct({ lot: l, kind: "return" })}>Return</button>
              <button className="btn-secondary px-2 py-1" onClick={() => setAct({ lot: l, kind: "adjust" })}>Adjust</button>
              <button className="btn-secondary px-2 py-1" disabled={l.quantity_available <= 0} onClick={() => setAct({ lot: l, kind: "dispose" })}>Dispose</button></div></td>
          </tr>))}</tbody></table></div>
      {act && <ActionModal {...act} onClose={() => setAct(null)} onDone={() => { setAct(null); refresh(); }} />}
      {editLot && <EditLotModal lot={editLot} onClose={() => setEditLot(null)} onDone={() => { setEditLot(null); refresh(); }} />}
      {adding && <AddLotModal onClose={() => setAdding(false)} onDone={() => { setAdding(false); refresh(); }} />}
    </div>
  );
}

function ActionModal({ lot, kind, onClose, onDone }: { lot: Lot; kind: "return" | "adjust" | "dispose" | "receive"; onClose: () => void; onDone: () => void }) {
  const [qty, setQty] = useState("");
  const [reason, setReason] = useState("");
  const m = useMutation({
    mutationFn: () => api(`/inventory/lots/${lot.lot_id}/${kind}`, { method: "POST",
      json: kind === "return" ? { quantity: Number(qty), reason: reason || null } : kind === "receive" ? { quantity: Number(qty), reason }
        : kind === "adjust" ? { new_quantity: Number(qty), reason, expected_version: lot.row_version } : { reason } }),
    onSuccess: () => { toast.success("Recorded"); onDone(); }, onError: (e) => { toast.error(errMsg(e)); onDone(); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); m.mutate(); };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <form onSubmit={submit} className="card w-full max-w-md space-y-3 p-6">
        <h2 className="text-lg font-bold capitalize">{kind} — {lot.name} ({lot.lot_no})</h2>
        {kind !== "dispose" && <div><label className="label">{kind === "return" ? "Quantity returned" : kind === "receive" ? "Quantity received" : "New quantity"} ({lot.unit})</label>
          <input className="input" type="number" step="any" min={kind === "receive" ? "0.000001" : "0"} required value={qty} onChange={(e) => setQty(e.target.value)} /></div>}
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

function EditLotModal({ lot, onClose, onDone }: { lot: Lot; onClose: () => void; onDone: () => void }) {
  const [f, setF] = useState({ lot_no: lot.lot_no, expiry_date: lot.expiry_date ?? "", location: lot.location ?? "", storage_conditions: lot.storage_conditions ?? "", availability: lot.availability, reason: "" });
  const m = useMutation({
    mutationFn: () => api(`/inventory/lots/${lot.lot_id}`, { method: "PATCH", json: { expected_version: lot.row_version, reason: f.reason, lot_no: f.lot_no, expiry_date: f.expiry_date || null,
      location: f.location || null, storage_conditions: f.storage_conditions || null, availability: f.availability } }),
    onSuccess: () => { toast.success("Lot updated"); onDone(); },
    onError: (e) => { toast.error(errMsg(e)); },
  });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <form onSubmit={(e: FormEvent) => { e.preventDefault(); m.mutate(); }} className="card w-full max-w-md space-y-3 p-6">
        <h2 className="text-lg font-bold">Edit lot — {lot.name}</h2>
        <p className="text-xs text-slate-500">Editing version {lot.row_version}. If someone else changed this lot meanwhile, the save is rejected and you will need to reload.</p>
        <div><label className="label">Batch / lot no.</label><input className="input" required value={f.lot_no} onChange={set("lot_no")} /></div>
        <div className="grid grid-cols-2 gap-3">
          <div><label className="label">Expiry date</label><input className="input" type="date" value={f.expiry_date} onChange={set("expiry_date")} /></div>
          <div><label className="label">Availability</label><select className="input" value={f.availability} onChange={set("availability")}><option value="active">active</option><option value="quarantined">quarantined</option><option value="unavailable">unavailable</option></select></div>
        </div>
        <div><label className="label">Storage location</label><input className="input" value={f.location} onChange={set("location")} /></div>
        <div><label className="label">Storage conditions</label><input className="input" value={f.storage_conditions} onChange={set("storage_conditions")} /></div>
        <div><label className="label">Reason for the change (required)</label><input className="input" required minLength={3} value={f.reason} onChange={set("reason")} /></div>
        <div className="flex justify-end gap-2"><button type="button" className="btn-secondary" onClick={onClose}>Cancel</button><button className="btn-primary" disabled={m.isPending || f.reason.trim().length < 3}>Save</button></div>
      </form>
    </div>
  );
}
