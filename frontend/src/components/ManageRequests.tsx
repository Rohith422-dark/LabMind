import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, type Schemas } from "@/api/client";
import { Banner, Empty, Modal, Pager, Spinner, StatusBadge, errMsg, fmtDate } from "@/components/ui";
import { StockBar } from "@/components/StockBar";

type Req = Schemas["RequestOut"];
type Detail = Schemas["RequestDetail"];
type Lot = Schemas["LotOut"];
const PAGE = 15;

export function ManageRequests() {
  const [f, setF] = useState({ status: "", reagent: "", requester: "", urgency: "", date_from: "", date_to: "" });
  const [offset, setOffset] = useState(0);
  const [open, setOpen] = useState<string | null>(null);
  const qs = new URLSearchParams({ limit: String(PAGE), offset: String(offset) });
  (Object.entries(f) as [string, string][]).forEach(([k, v]) => v && qs.set(k, v));
  const q = useQuery({ queryKey: ["manage-requests", qs.toString()], queryFn: () => api<Schemas["RequestPage"]>(`/requests?${qs}`), refetchInterval: 20000 });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => { setOffset(0); setF({ ...f, [k]: e.target.value }); };
  return (
    <div className="space-y-4">
      <div className="card grid gap-3 p-4 md:grid-cols-6">
        <select aria-label="Status" className="input" value={f.status} onChange={set("status")}><option value="">Any status</option>
          {["submitted", "under_review", "needs_clarification", "approved", "rejected", "fulfilled"].map((s) => <option key={s} value={s}>{s.replace(/_/g, " ")}</option>)}</select>
        <input aria-label="Reagent" className="input" placeholder="Reagent" value={f.reagent} onChange={set("reagent")} />
        <input aria-label="Requester" className="input" placeholder="Requester" value={f.requester} onChange={set("requester")} />
        <select aria-label="Urgency" className="input" value={f.urgency} onChange={set("urgency")}><option value="">Any urgency</option>{["urgent", "high", "normal", "low"].map((u) => <option key={u} value={u}>{u}</option>)}</select>
        <input aria-label="From date" type="date" className="input" value={f.date_from} onChange={set("date_from")} />
        <input aria-label="To date" type="date" className="input" value={f.date_to} onChange={set("date_to")} />
      </div>
      {q.isLoading && <Spinner />}
      {q.isError && <Banner tone="red">{errMsg(q.error)}</Banner>}
      {q.data?.total === 0 && <Empty title="No requests match">Requests raised by users appear here.</Empty>}
      {!!q.data?.items.length && (
        <div className="card overflow-x-auto" data-testid="manage-requests">
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-50 text-slate-600"><tr>{["Submitted", "Requester", "Reagent", "Quantity", "Reason", "Project", "Urgency", "Status", "Register"].map((h) => <th key={h} className="px-3 py-2 font-semibold">{h}</th>)}</tr></thead>
            <tbody>{q.data.items.map((r) => (
              <tr key={r.id} className="cursor-pointer border-t border-slate-100 hover:bg-slate-50" onClick={() => setOpen(r.id)}>
                <td className="px-3 py-2 whitespace-nowrap">{fmtDate(r.created_at)}</td><td className="px-3 py-2">{r.requester_name}</td>
                <td className="px-3 py-2"><button className="text-brand-700 underline" onClick={() => setOpen(r.id)}>{r.reagent_name}</button>{!r.in_register && <div className="text-xs text-slate-500">not in register</div>}</td>
                <td className="px-3 py-2">{r.quantity} {r.unit}</td><td className="px-3 py-2 max-w-[16rem]">{r.purpose}</td><td className="px-3 py-2">{r.project_name}</td>
                <td className="px-3 py-2"><StatusBadge status={r.urgency} /></td><td className="px-3 py-2"><StatusBadge status={r.status} /></td>
                <td className="px-3 py-2">{r.reagent_availability && <StatusBadge status={r.reagent_availability} />}</td>
              </tr>))}</tbody>
          </table>
        </div>)}
      {q.data && <Pager total={q.data.total} limit={PAGE} offset={offset} onChange={setOffset} />}
      {open && <ManageModal id={open} onClose={() => setOpen(null)} />}
    </div>
  );
}

function ManageModal({ id, onClose }: { id: string; onClose: () => void }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["req", id], queryFn: () => api<Detail>(`/requests/${id}`) });
  const r = q.data;
  const lots = useQuery({ enabled: !!r?.reagent_id, queryKey: ["lots-for", r?.reagent_id], queryFn: () => api<Lot[]>(`/inventory?name=${encodeURIComponent(r!.reagent_name)}`) });
  const mine = (lots.data ?? []).filter((l) => l.reagent_id === r?.reagent_id).sort((a, b) => (a.expiry_date ?? "9999").localeCompare(b.expiry_date ?? "9999"));
  const [comment, setComment] = useState("");
  const [reserve, setReserve] = useState("");
  const [lot, setLot] = useState("");
  const [issue, setIssue] = useState(true);
  const [note, setNote] = useState("");
  const refresh = () => { void qc.invalidateQueries({ queryKey: ["req", id] }); void qc.invalidateQueries({ queryKey: ["manage-requests"] }); void qc.invalidateQueries({ queryKey: ["lots-for"] }); void qc.invalidateQueries({ queryKey: ["inv-all"] }); void qc.invalidateQueries({ queryKey: ["reagent-summary"] }); };
  const transition = useMutation({
    mutationFn: (to: string) => api(`/requests/${id}/transition`, { method: "POST", json: { to_status: to, comment: comment || null, reserve_lot_id: to === "approved" && reserve ? reserve : null } }),
    onSuccess: (_, to) => { toast.success(`Request moved to ${to.replace(/_/g, " ")}. The requester was notified.`); setComment(""); refresh(); }, onError: (e) => toast.error(errMsg(e)),
  });
  const addComment = useMutation({
    mutationFn: () => api(`/requests/${id}/comment`, { method: "POST", json: { comment } }),
    onSuccess: () => { toast.success("Comment sent to the requester"); setComment(""); refresh(); }, onError: (e) => toast.error(errMsg(e)),
  });
  const fulfil = useMutation({
    mutationFn: () => api(`/requests/${id}/fulfil`, { method: "POST", json: { note, lot_id: lot || null, issue_from_lot: !!lot && issue } }),
    onSuccess: () => { toast.success("Marked fulfilled"); setNote(""); refresh(); }, onError: (e) => { toast.error(errMsg(e)); refresh(); },
  });
  const next = new Set(r?.allowed_next ?? []);
  const needsComment = (s: string) => s === "rejected" || s === "needs_clarification";

  return (
    <Modal title={r ? `${r.reagent_name} — ${r.quantity} ${r.unit ?? ""}` : "Request"} onClose={onClose} wide>
      {q.isLoading && <Spinner />}
      {q.isError && <Banner tone="red">{errMsg(q.error)}</Banner>}
      {r && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2"><StatusBadge status={r.status} /><StatusBadge status={r.urgency} />
            {r.reagent_availability && <span className="text-sm">Register: <StatusBadge status={r.reagent_availability} /></span>}</div>
          <dl className="grid gap-2 text-sm md:grid-cols-3">
            <div><dt className="text-slate-500">Requester</dt><dd>{r.requester_name}</dd></div><div><dt className="text-slate-500">Submitted</dt><dd>{fmtDate(r.created_at)}</dd></div>
            <div><dt className="text-slate-500">Project / experiment</dt><dd>{r.project_name ?? "—"} {r.experiment_ref ? `· ${r.experiment_ref}` : ""}</dd></div>
            <div className="md:col-span-3"><dt className="text-slate-500">Reason</dt><dd>{r.purpose}{r.details ? ` — ${r.details}` : ""}</dd></div>
            {r.reserved_lot_id && <div className="md:col-span-3"><dt className="text-slate-500">Stock set aside</dt><dd>{r.reserved_quantity} {r.unit}</dd></div>}
          </dl>
          <ol className="space-y-2 border-l-2 border-slate-200 pl-4">{r.events.map((e) => (
            <li key={e.id} className="text-sm"><div className="flex flex-wrap items-center gap-2">
              {e.kind === "status" ? <StatusBadge status={e.to_status ?? ""} /> : <span className="badge bg-slate-100 text-slate-700">comment</span>}
              <span className="text-xs text-slate-500">{e.actor_name} · {fmtDate(e.created_at)}</span></div>{e.comment && <div className="whitespace-pre-wrap">{e.comment}</div>}</li>))}</ol>

          {r.status !== "rejected" && r.status !== "fulfilled" && (
            <div className="space-y-3 rounded-md border border-slate-200 p-3">
              <h3 className="font-semibold">Review</h3>
              <div><label className="label" htmlFor="mr-comment">Comment to the requester{next.has("rejected") ? " (required to reject or ask for clarification)" : ""}</label>
                <textarea id="mr-comment" className="input" rows={2} maxLength={2000} value={comment} onChange={(e) => setComment(e.target.value)} /></div>
              {next.has("approved") && r.reagent_id && mine.length > 0 && (
                <div><label className="label" htmlFor="mr-reserve">Optionally set stock aside when approving (approval alone changes no stock)</label>
                  <select id="mr-reserve" className="input" value={reserve} onChange={(e) => setReserve(e.target.value)}><option value="">Do not reserve</option>
                    {mine.filter((l) => l.usable_quantity > 0).map((l) => <option key={l.lot_id} value={l.lot_id}>Lot {l.lot_no} · usable {l.usable_quantity} {l.unit} · exp {l.expiry_date}</option>)}</select></div>)}
              <div className="flex flex-wrap gap-2">
                {next.has("under_review") && <button className="btn-secondary" disabled={transition.isPending} onClick={() => transition.mutate("under_review")}>{r.status === "needs_clarification" ? "Back to review" : "Start review"}</button>}
                {next.has("needs_clarification") && <button className="btn-secondary" disabled={transition.isPending || comment.trim().length < 3} onClick={() => transition.mutate("needs_clarification")}>Ask for clarification</button>}
                {next.has("approved") && <button className="btn-primary" disabled={transition.isPending} onClick={() => transition.mutate("approved")}>Approve</button>}
                {next.has("rejected") && <button className="btn-danger" disabled={transition.isPending || comment.trim().length < 3} onClick={() => transition.mutate("rejected")}>Reject</button>}
                <button className="btn-secondary" disabled={addComment.isPending || !comment.trim()} onClick={() => addComment.mutate()}>Comment only</button>
              </div>
              {needsComment("rejected") && comment.trim().length < 3 && <p className="text-xs text-slate-500">Rejecting or asking for clarification needs a written explanation.</p>}
            </div>)}

          {r.status === "approved" && (
            <div className="space-y-3 rounded-md border border-indigo-300 bg-indigo-50 p-3">
              <h3 className="font-semibold">Fulfil</h3>
              <Banner tone="blue">Approved is not fulfilled. Mark it fulfilled only when the need has actually been met.</Banner>
              {r.reagent_id ? (
                mine.length === 0 ? <Banner tone="red">No lots are recorded for this reagent. Receive stock under Stock management first.</Banner> : (
                  <div className="grid gap-2 md:grid-cols-2">{mine.map((l) => {
                    const blocked = l.usable_quantity <= 0 && !(l.lot_id === r.reserved_lot_id);
                    return (
                      <label key={l.lot_id} className={`flex cursor-pointer items-start gap-2 rounded-md border p-2 text-sm ${lot === l.lot_id ? "border-brand-500 bg-white" : "border-slate-200 bg-white"} ${blocked ? "opacity-60" : ""}`}>
                        <input type="radio" name="fulfil-lot" disabled={blocked} checked={lot === l.lot_id} onChange={() => setLot(l.lot_id)} />
                        <span className="flex-1"><b>{l.lot_no}</b> · exp {l.expiry_date} <StatusBadge status={l.status} />
                          <StockBar qty={l.quantity_available} capacity={l.capacity} status={l.status} unit={l.unit} />
                          <span className="text-xs text-slate-500">usable {l.usable_quantity} · reserved {l.reserved_quantity}</span>
                          {l.status === "red" && (l.days_remaining ?? 1) <= 0 && <span className="block text-xs font-bold text-red-600">EXPIRED — cannot be used</span>}</span>
                      </label>);
                  })}</div>)
              ) : <p className="text-sm text-slate-600">This reagent is not in the register; describe how the need was met (e.g. ordered and received).</p>}
              {r.reagent_id && lot && <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={issue} onChange={(e) => setIssue(e.target.checked)} />Issue from this lot now (reduces its stock by {r.quantity} {r.unit})</label>}
              <div><label className="label" htmlFor="mr-note">How was it fulfilled? (required)</label><input id="mr-note" className="input" maxLength={2000} value={note} onChange={(e) => setNote(e.target.value)} /></div>
              <div className="flex justify-end"><button className="btn-primary" disabled={fulfil.isPending || note.trim().length < 3 || (!!r.reagent_id && !lot)} onClick={() => fulfil.mutate()}>{fulfil.isPending ? "Saving…" : "Mark fulfilled"}</button></div>
            </div>)}
        </div>)}
    </Modal>
  );
}
