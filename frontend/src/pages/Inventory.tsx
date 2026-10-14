import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { api, type Schemas } from "@/api/client";
import { useAuth } from "@/context/AuthContext";
import { Banner, Empty, HazardBadges, Spinner, StatusBadge, errMsg } from "@/components/ui";
import { StockBar } from "@/components/StockBar";
import { RequestReagentModal } from "@/components/RequestReagentModal";

type Lot = Schemas["LotOut"];
type Summary = Schemas["ReagentSummaryOut"];

export default function Inventory() {
  const { can } = useAuth();
  const [view, setView] = useState<"reagents" | "lots">("reagents");
  const [name, setName] = useState("");
  const [status, setStatus] = useState("");
  const [hazard, setHazard] = useState("");
  const [soon, setSoon] = useState(false);
  const [req, setReq] = useState<{ reagentId?: string } | null>(null);

  const qs = new URLSearchParams();
  if (name) qs.set("name", name);
  if (status) qs.set("status", status);
  if (hazard) qs.set("hazard", hazard);
  if (soon) qs.set("expiring_soon", "true");
  const lots = useQuery({ queryKey: ["inv", name, status, hazard, soon], queryFn: () => api<Lot[]>(`/inventory?${qs}`), enabled: view === "lots" });
  const sq = new URLSearchParams();
  if (name) sq.set("name", name);
  if (status) sq.set("status", status);
  const summary = useQuery({ queryKey: ["reagent-summary", name, status], queryFn: () => api<Summary[]>(`/inventory/reagents/summary?${sq}`), enabled: view === "reagents" });

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-[26px] font-semibold leading-tight">Inventory</h1>
        <div className="flex gap-2">
          <div className="flex overflow-hidden rounded-md border border-slate-300" role="tablist" aria-label="Inventory view">
            {([["reagents", "By reagent"], ["lots", "By lot"]] as const).map(([k, l]) => (
              <button key={k} role="tab" aria-selected={view === k} onClick={() => { setView(k); setStatus(""); }} className={`px-3 py-2 text-sm ${view === k ? "bg-brand-600 text-white" : "bg-white text-slate-700 hover:bg-slate-100"}`}>{l}</button>))}
          </div>
          {can("requests.create") && <button className="btn-primary" onClick={() => setReq({})}><Plus size={16} />Request reagent</button>}
        </div>
      </div>

      <div className="card mb-4 grid gap-3 p-4 md:grid-cols-5">
        <input aria-label="Search reagents" className="input md:col-span-2" placeholder="Reagent, CAS or lot…" value={name} onChange={(e) => setName(e.target.value)} />
        {view === "reagents" ? (
          <select aria-label="Availability" className="input md:col-span-2" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">Any availability</option><option value="available">Available</option><option value="low">Running low</option><option value="out_of_stock">Out of stock</option>
            <option value="expired">Expired</option><option value="awaiting_restock">Awaiting restocking</option><option value="unavailable">Unavailable</option></select>
        ) : (
          <>
            <select aria-label="Lot status" className="input" value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">Any status</option><option value="green">In stock</option><option value="amber">Low / expiring</option><option value="red">Expired / out</option></select>
            <input aria-label="Hazard" className="input" placeholder="Hazard (e.g. flammable, H225)" value={hazard} onChange={(e) => setHazard(e.target.value)} />
            <label className="flex items-center gap-2 text-sm text-slate-600"><input type="checkbox" checked={soon} onChange={(e) => setSoon(e.target.checked)} />Expiring ≤ 30 days</label>
          </>)}
      </div>

      {view === "reagents" && (
        <>
          <p className="mb-2 text-sm text-slate-600"><b>Physical</b> = everything on the shelf · <b>Usable</b> = in date, available and not reserved · <b>Expired / unavailable</b> is never counted as usable.</p>
          {summary.isLoading && <Spinner label="Loading inventory…" />}
          {summary.isError && <Banner tone="red">{errMsg(summary.error)}</Banner>}
          {summary.data?.length === 0 && <Empty title="No reagents match these filters" />}
          {!!summary.data?.length && (
            <div className="card overflow-x-auto">
              <table className="w-full text-left text-sm" data-testid="reagent-table">
                <thead className="bg-slate-50 text-slate-600"><tr>{["Reagent", "Physical", "Usable", "Reserved", "Expired", "Unavailable", "Nearest usable expiry", "Availability", ""].map((h) => <th key={h} className="px-3 py-2 font-semibold">{h}</th>)}</tr></thead>
                <tbody>{summary.data.map((s) => (
                  <tr key={s.reagent_id} className="border-t border-slate-100 align-top">
                    <td className="px-3 py-2"><div className="font-medium">{s.name}</div><div className="text-xs text-slate-500">{s.cas_number ?? "no CAS"} · {s.lots} lot(s)</div><div className="mt-1 flex flex-wrap gap-1"><HazardBadges classes={s.hazard_classes ?? []} /></div></td>
                    <td className="px-3 py-2 whitespace-nowrap">{s.physical_quantity} {s.unit}</td>
                    <td className="px-3 py-2 whitespace-nowrap font-semibold">{s.usable_quantity} {s.unit}</td>
                    <td className="px-3 py-2 whitespace-nowrap">{s.reserved_quantity} {s.unit}</td>
                    <td className={`px-3 py-2 whitespace-nowrap ${s.expired_quantity > 0 ? "font-semibold text-red-700" : ""}`}>{s.expired_quantity} {s.unit}</td>
                    <td className="px-3 py-2 whitespace-nowrap">{s.unavailable_quantity} {s.unit}</td>
                    <td className="px-3 py-2 whitespace-nowrap">{s.nearest_usable_expiry ?? "—"}</td>
                    <td className="px-3 py-2"><StatusBadge status={s.status} /></td>
                    <td className="px-3 py-2">{can("requests.create") && <button className="btn-secondary px-3 py-1" onClick={() => setReq({ reagentId: s.reagent_id })}>Request</button>}</td>
                  </tr>))}</tbody>
              </table>
            </div>)}
        </>)}

      {view === "lots" && (
        <>
          {lots.isLoading && <Spinner label="Loading inventory…" />}
          {lots.isError && <Banner tone="red">{errMsg(lots.error)}</Banner>}
          {lots.data?.length === 0 && <Empty title="No lots match these filters" />}
          {!!lots.data?.length && (
            <div className="card overflow-x-auto">
              <table className="w-full text-left text-sm" data-testid="inventory-table">
                <thead className="bg-slate-50 text-slate-600"><tr>
                  {["Reagent", "Batch / grade", "Stock", "Usable", "Location", "Expiry", "Hazards", "Status", ""].map((h) => <th key={h} className="px-3 py-2 font-semibold">{h}</th>)}</tr></thead>
                <tbody>
                  {lots.data.map((l) => (
                    <tr key={l.lot_id} className="border-t border-slate-100 align-top">
                      <td className="px-3 py-2"><div className="font-medium">{l.name}</div><div className="text-xs text-slate-500">{l.cas_number ?? "no CAS"} · {l.formula ?? ""}</div></td>
                      <td className="px-3 py-2"><div>{l.lot_no}</div><div className="text-xs text-slate-500">{l.grade}</div></td>
                      <td className="px-3 py-2"><StockBar qty={l.quantity_available} capacity={l.capacity} status={l.status} unit={l.unit} />
                        {l.reorder_level !== null && l.reorder_level !== undefined && <div className="text-xs text-slate-400">reorder ≤ {l.reorder_level}</div>}</td>
                      <td className="px-3 py-2 whitespace-nowrap"><b>{l.usable_quantity}</b> {l.unit}{l.reserved_quantity > 0 && <div className="text-xs text-slate-500">{l.reserved_quantity} reserved</div>}
                        {l.availability !== "active" && <div className="text-xs font-semibold text-red-700">{l.availability}</div>}</td>
                      <td className="px-3 py-2"><div>{l.location}</div><div className="text-xs text-slate-500">{l.storage_conditions}</div></td>
                      <td className="px-3 py-2 whitespace-nowrap">{l.expiry_date}<div className={`text-xs ${(l.days_remaining ?? 99) <= 0 ? "font-bold text-red-600" : (l.days_remaining ?? 99) <= 30 ? "text-amber-700" : "text-slate-500"}`}>
                        {l.days_remaining === null || l.days_remaining === undefined ? "" : l.days_remaining <= 0 ? `expired ${-l.days_remaining} d ago — not usable` : `${l.days_remaining} d left`}</div></td>
                      <td className="px-3 py-2"><div className="flex max-w-[11rem] flex-wrap gap-1"><HazardBadges classes={l.hazard_classes ?? []} /></div></td>
                      <td className="px-3 py-2"><StatusBadge status={l.status} /></td>
                      <td className="px-3 py-2">{can("requests.create") && <button className="btn-secondary px-3 py-1" onClick={() => setReq({ reagentId: l.reagent_id })}>{l.status === "red" ? "Request restock" : "Request"}</button>}</td>
                    </tr>))}
                </tbody>
              </table>
            </div>)}
        </>)}
      {req && <RequestReagentModal reagentId={req.reagentId} onClose={() => setReq(null)} />}
    </div>
  );
}
