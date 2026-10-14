import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, type Schemas } from "@/api/client";
import { useAuth } from "@/context/AuthContext";
import { Banner, Modal, errMsg } from "@/components/ui";

const UNITS = ["mg", "g", "kg", "uL", "mL", "L", "umol", "mmol", "mol", "unit", "vial", "bottle", "pack"];
const NEW = "__new__";
type Summary = Schemas["ReagentSummaryOut"];

const WARN: Record<string, string> = {
  expired: "All stock of this reagent is expired and cannot be used.",
  out_of_stock: "This reagent is currently out of stock.",
  unavailable: "This reagent is currently unavailable (quarantined or not stocked).",
  awaiting_restock: "This reagent is awaiting restocking.",
  low: "Stock of this reagent is running low.",
};

/** Request any reagent: from the register, or one that is not in it yet. Works even when stock is expired/out/insufficient. */
export function RequestReagentModal({ reagentId, onClose }: { reagentId?: string; onClose: () => void }) {
  const qc = useQueryClient();
  const { can } = useAuth();
  const summaries = useQuery({ queryKey: ["reagent-summary"], queryFn: () => api<Summary[]>("/inventory/reagents/summary") });
  const projects = useQuery({ queryKey: ["projects", false], queryFn: () => api<Schemas["ProjectOut"][]>("/projects?include_archived=false"), enabled: can("projects.use") });
  const [sel, setSel] = useState(reagentId ?? "");
  const [f, setF] = useState({ name: "", quantity: "", unit: "", reason: "", details: "", urgency: "normal", project_id: "", experiment_ref: "" });
  const [error, setError] = useState<string | null>(null);
  const chosen = summaries.data?.find((s) => s.reagent_id === sel);
  const isNew = sel === NEW;
  const unit = f.unit || chosen?.unit || "";
  const qty = Number(f.quantity);
  const invalid = !sel || (isNew && !f.name.trim()) || !(qty > 0) || !(unit) || f.reason.trim().length < 3;

  const m = useMutation({
    mutationFn: () => api("/requests", { method: "POST", json: {
      reagent_id: isNew ? null : sel, reagent_name: isNew ? f.name.trim() : null, quantity: qty, unit, reason: f.reason.trim(), details: f.details || null,
      urgency: f.urgency, project_id: f.project_id || null, experiment_ref: f.experiment_ref || null } }),
    onSuccess: () => { toast.success("Request submitted. Lab assistants have been notified; track it under My Requests."); void qc.invalidateQueries({ queryKey: ["myreq"] }); onClose(); },
    onError: (e) => { setError(errMsg(e)); toast.error(errMsg(e)); },
  });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const submit = (e: FormEvent) => { e.preventDefault(); setError(null); m.mutate(); };

  return (
    <Modal title="Request a reagent" onClose={onClose}>
      <form onSubmit={submit} className="space-y-3">
        {error && <Banner tone="red">{error}</Banner>}
        <div>
          <label className="label" htmlFor="rq-reagent">Reagent</label>
          <select id="rq-reagent" className="input" required value={sel} onChange={(e) => { setSel(e.target.value); setF({ ...f, unit: "" }); }}>
            <option value="">Choose…</option>
            {summaries.data?.map((s) => <option key={s.reagent_id} value={s.reagent_id}>{s.name}{s.cas_number ? ` (${s.cas_number})` : ""} — {s.status_label}</option>)}
            <option value={NEW}>Not in the register — enter a name…</option>
          </select>
          {summaries.isLoading && <p className="mt-1 text-xs text-slate-500">Loading the register…</p>}
        </div>
        {chosen && WARN[chosen.status] && <Banner tone="amber">{WARN[chosen.status]} You can still send a request: a lab assistant will review it. Usable now: {chosen.usable_quantity} {chosen.unit}.</Banner>}
        {isNew && <div><label className="label" htmlFor="rq-name">Reagent name</label><input id="rq-name" className="input" required maxLength={200} value={f.name} onChange={set("name")} /></div>}
        <div className="grid grid-cols-2 gap-3">
          <div><label className="label" htmlFor="rq-qty">Quantity</label><input id="rq-qty" className="input" type="number" step="any" min="0" required value={f.quantity} onChange={set("quantity")} />
            {f.quantity !== "" && !(qty > 0) && <p className="mt-1 text-xs text-red-700">Quantity must be greater than zero.</p>}</div>
          <div><label className="label" htmlFor="rq-unit">Unit</label>
            <select id="rq-unit" className="input" required value={unit} onChange={set("unit")}><option value="">Choose…</option>
              {chosen?.unit && !UNITS.includes(chosen.unit) && <option value={chosen.unit}>{chosen.unit}</option>}{UNITS.map((u) => <option key={u} value={u}>{u}</option>)}</select></div>
        </div>
        <div><label className="label" htmlFor="rq-reason">Reason for the request</label><input id="rq-reason" className="input" required minLength={3} maxLength={1000} value={f.reason} onChange={set("reason")} placeholder="e.g. stock expired; new assay needs it" /></div>
        <div className="grid grid-cols-2 gap-3">
          <div><label className="label" htmlFor="rq-urg">Urgency</label><select id="rq-urg" className="input" value={f.urgency} onChange={set("urgency")}><option value="low">low</option><option value="normal">normal</option><option value="high">high</option><option value="urgent">urgent</option></select></div>
          <div><label className="label" htmlFor="rq-proj">Project (optional)</label><select id="rq-proj" className="input" value={f.project_id} onChange={set("project_id")}><option value="">None</option>{projects.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></div>
        </div>
        <div><label className="label" htmlFor="rq-exp">Experiment reference (optional)</label><input id="rq-exp" className="input" maxLength={120} value={f.experiment_ref} onChange={set("experiment_ref")} /></div>
        <div><label className="label" htmlFor="rq-det">Additional details (optional)</label><textarea id="rq-det" className="input" rows={2} maxLength={4000} value={f.details} onChange={set("details")} /></div>
        <div className="flex justify-end gap-2"><button type="button" className="btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn-primary" disabled={invalid || m.isPending}>{m.isPending ? "Submitting…" : "Submit request"}</button></div>
      </form>
    </Modal>
  );
}
