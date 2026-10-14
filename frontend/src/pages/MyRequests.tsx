import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api/client";
import type { Schemas } from "@/api/client";
import { Banner, Empty, Modal, Spinner, StatusBadge, errMsg, fmtDate } from "@/components/ui";
import { RequestReagentModal } from "@/components/RequestReagentModal";

type Req = Schemas["RequestOut"];
type Detail = Schemas["RequestDetail"];

export const STATUS_HELP: Record<string, string> = {
  submitted: "Waiting for a lab assistant to pick it up.",
  under_review: "A lab assistant is reviewing it.",
  needs_clarification: "The lab assistant needs more information from you.",
  approved: "Approved, but NOT yet fulfilled: this does not mean the reagent is in stock or has been issued.",
  rejected: "Declined.",
  fulfilled: "Done: the need was met.",
};

export default function MyRequests() {
  const [filter, setFilter] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const q = useQuery({ queryKey: ["myreq", filter], queryFn: () => api<Req[]>(`/requests/mine${filter ? `?status=${filter}` : ""}`), refetchInterval: 20000 });
  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-[26px] font-semibold leading-tight">My requests</h1>
        <div className="flex gap-2">
          <select aria-label="Filter by status" className="input w-48" value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="">All statuses</option>{Object.keys(STATUS_HELP).map((s) => <option key={s} value={s}>{s.replace(/_/g, " ")}</option>)}</select>
          <button className="btn-primary" onClick={() => setCreating(true)}><Plus size={16} />Request reagent</button>
        </div>
      </div>
      {q.isLoading && <Spinner />}
      {q.isError && <Banner tone="red">{errMsg(q.error)}</Banner>}
      {q.data?.length === 0 && <Empty title="No requests">Use “Request reagent” here or on the Inventory page.</Empty>}
      {!!q.data?.length && (
        <div className="card overflow-x-auto">
          <table className="w-full text-left text-sm" data-testid="my-requests">
            <thead className="bg-slate-50 text-slate-600"><tr>{["Submitted", "Reagent", "Quantity", "Reason", "Urgency", "Status", "Register now"].map((h) => <th key={h} className="px-3 py-2 font-semibold">{h}</th>)}</tr></thead>
            <tbody>{q.data.map((r) => (
              <tr key={r.id} className="cursor-pointer border-t border-slate-100 hover:bg-slate-50" onClick={() => setOpen(r.id)}>
                <td className="px-3 py-2 whitespace-nowrap">{fmtDate(r.created_at)}</td>
                <td className="px-3 py-2"><button className="text-left text-brand-700 underline" onClick={() => setOpen(r.id)}>{r.reagent_name}</button>{!r.in_register && <div className="text-xs text-slate-500">not in register</div>}</td>
                <td className="px-3 py-2">{r.quantity} {r.unit}</td>
                <td className="px-3 py-2">{r.purpose}{r.experiment_ref ? ` (${r.experiment_ref})` : ""}{r.project_name ? <div className="text-xs text-slate-500">project: {r.project_name}</div> : null}</td>
                <td className="px-3 py-2"><StatusBadge status={r.urgency} /></td>
                <td className="px-3 py-2"><StatusBadge status={r.status} />{r.status === "needs_clarification" && <div className="text-xs font-semibold text-orange-700">Your answer is needed</div>}</td>
                <td className="px-3 py-2">{r.reagent_availability && <StatusBadge status={r.reagent_availability} />}</td>
              </tr>))}</tbody>
          </table>
        </div>)}
      {open && <RequestModal id={open} onClose={() => setOpen(null)} />}
      {creating && <RequestReagentModal onClose={() => setCreating(false)} />}
    </div>
  );
}

function RequestModal({ id, onClose }: { id: string; onClose: () => void }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["req", id], queryFn: () => api<Detail>(`/requests/${id}`) });
  const [reply, setReply] = useState("");
  const send = useMutation({
    mutationFn: () => api<Detail>(`/requests/${id}/respond`, { method: "POST", json: { comment: reply } }),
    onSuccess: () => { toast.success("Sent to the lab assistant"); setReply(""); void qc.invalidateQueries({ queryKey: ["req", id] }); void qc.invalidateQueries({ queryKey: ["myreq"] }); },
    onError: (e) => toast.error(errMsg(e)),
  });
  const r = q.data;
  return (
    <Modal title={r ? `${r.reagent_name} — ${r.quantity} ${r.unit ?? ""}` : "Request"} onClose={onClose} wide>
      {q.isLoading && <Spinner />}
      {q.isError && <Banner tone="red">{errMsg(q.error)}</Banner>}
      {r && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2"><StatusBadge status={r.status} /><StatusBadge status={r.urgency} />
            {r.reagent_availability && <span className="text-sm text-slate-600">Reagent in register: <StatusBadge status={r.reagent_availability} /></span>}</div>
          <Banner tone={r.status === "needs_clarification" ? "amber" : r.status === "rejected" ? "red" : r.status === "fulfilled" ? "green" : "blue"}>{STATUS_HELP[r.status]}</Banner>
          <dl className="grid gap-2 text-sm md:grid-cols-2">
            <div><dt className="text-slate-500">Reason</dt><dd>{r.purpose}</dd></div>
            <div><dt className="text-slate-500">Submitted</dt><dd>{fmtDate(r.created_at)}</dd></div>
            {r.details && <div className="md:col-span-2"><dt className="text-slate-500">Details</dt><dd className="whitespace-pre-wrap">{r.details}</dd></div>}
            {r.project_name && <div><dt className="text-slate-500">Project</dt><dd>{r.project_name}</dd></div>}
            {r.experiment_ref && <div><dt className="text-slate-500">Experiment</dt><dd>{r.experiment_ref}</dd></div>}
            {r.handler_name && <div><dt className="text-slate-500">Handled by</dt><dd>{r.handler_name}</dd></div>}
            {r.reject_reason && <div className="md:col-span-2"><dt className="text-slate-500">Reason for rejection</dt><dd className="text-red-700">{r.reject_reason}</dd></div>}
            {r.fulfilment_note && <div className="md:col-span-2"><dt className="text-slate-500">How it was fulfilled</dt><dd>{r.fulfilment_note}</dd></div>}
          </dl>
          <div>
            <h3 className="mb-2 font-semibold">History</h3>
            <ol className="space-y-2 border-l-2 border-slate-200 pl-4" data-testid="request-timeline">{r.events.map((e) => (
              <li key={e.id} className="text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  {e.kind === "status" ? <><StatusBadge status={e.to_status ?? ""} />{e.from_status && <span className="text-xs text-slate-500">from {e.from_status.replace(/_/g, " ")}</span>}</> : <span className="badge bg-slate-100 text-slate-700">comment</span>}
                  <span className="text-xs text-slate-500">{e.actor_name} ({e.actor_role?.replace(/_/g, " ")}) · {fmtDate(e.created_at)}</span></div>
                {e.comment && <div className="mt-0.5 whitespace-pre-wrap text-slate-800">{e.comment}</div>}
              </li>))}</ol>
          </div>
          {r.status === "needs_clarification" && (
            <form className="space-y-2 rounded-md border border-orange-300 bg-orange-50 p-3" onSubmit={(e) => { e.preventDefault(); send.mutate(); }}>
              <label className="label" htmlFor="reply">Provide the requested information</label>
              <textarea id="reply" className="input" rows={3} required maxLength={2000} value={reply} onChange={(e) => setReply(e.target.value)} />
              <div className="flex justify-end"><button className="btn-primary" disabled={send.isPending || !reply.trim()}>{send.isPending ? "Sending…" : "Send answer"}</button></div>
            </form>)}
        </div>)}
    </Modal>
  );
}
