import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { toast } from "sonner";
import { api, type Schemas } from "@/api/client";
import { useAuth } from "@/context/AuthContext";
import { Banner, Spinner, StatusBadge, errMsg } from "@/components/ui";
import { PdfView } from "@/components/PdfView";
import { downloadDoc } from "@/components/SourceDrawer";

export default function SopViewer() {
  const { id = "" } = useParams();
  const { can } = useAuth();
  const qc = useQueryClient();
  const [reason, setReason] = useState("");
  const doc = useQuery({ queryKey: ["doc", id], queryFn: () => api<Schemas["DocumentDetail"]>(`/documents/${id}`) });
  const versions = useQuery({
    queryKey: ["versions", doc.data?.doc_code], enabled: !!doc.data,
    queryFn: () => api<Schemas["DocumentOut"][]>(`/documents/${encodeURIComponent(doc.data!.doc_code)}/versions`),
  });
  const retire = useMutation({
    mutationFn: () => api(`/documents/${id}/retire`, { method: "POST", json: { reason } }),
    onSuccess: () => { toast.success("Document retired"); void qc.invalidateQueries(); },
    onError: (e) => toast.error(errMsg(e)),
  });
  if (doc.isLoading) return <Spinner label="Loading…" />;
  const d = doc.data;
  if (!d) return <Banner tone="red">{errMsg(doc.error)}</Banner>;

  return (
    <div>
      <Link to="/sops" className="text-sm text-brand-700 underline">← SOP library</Link>
      <div className="mt-2 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">{d.doc_code} <span className="font-normal text-slate-500">v{d.version}</span> <StatusBadge status={d.status} /></h1>
          <div className="text-slate-700">{d.title}</div>
          <div className="text-xs text-slate-500">{d.doc_type.replace("_", " ")} · {d.equipment ?? "—"} · {d.department ?? "—"}{d.change_note ? ` · Change note: ${d.change_note}` : ""}</div>
        </div>
        <button className="btn-secondary" onClick={() => downloadDoc(d.id, `${d.doc_code}-v${d.version}.${d.file_type}`)}><Download size={16} />Download</button>
      </div>
      {d.status !== "effective" && (
        <div className="mt-3"><Banner tone="red"><b>{d.status === "superseded" ? "SUPERSEDED" : d.status.toUpperCase()} — DO NOT USE.</b>
          {d.retire_reason ? ` Reason: ${d.retire_reason}.` : " A newer version is in force."} This copy is shown for reference only and is never used to answer questions.</Banner></div>
      )}
      <div className="mt-4 grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          {d.file_type === "pdf" ? <PdfView documentId={d.id} page={1} /> : (
            <div className="space-y-3 text-sm">{d.text_sections.map((s, i) => <div key={i} className="card p-3">
              {s.section && <div className="font-semibold">{s.section}</div>}<div className="whitespace-pre-wrap">{s.text}</div></div>)}</div>
          )}
        </div>
        <div className="space-y-4">
          <div className="card p-4">
            <h2 className="mb-2 font-semibold">Version history</h2>
            <ul className="space-y-1 text-sm">
              {versions.data?.map((v) => (
                <li key={v.id} className="flex items-center justify-between">
                  <Link className="text-brand-700 underline" to={`/sops/${v.id}`}>v{v.version}</Link>
                  <span className="text-slate-500">{v.effective_date ? new Date(v.effective_date).toLocaleDateString() : ""}</span>
                  <StatusBadge status={v.status} />
                </li>
              ))}
            </ul>
          </div>
          {d.steps.length > 0 && (
            <div className="card p-4">
              <h2 className="mb-2 font-semibold">Extracted steps</h2>
              <ol className="space-y-2 text-sm">
                {d.steps.map((s) => (
                  <li key={s.step_no}><b>{s.step_no}.</b> {s.action}{s.is_critical && <span className="ml-1 font-bold text-red-600">(critical)</span>}
                    {s.reviewed && <span className="ml-1 text-xs text-green-700">reviewed</span>}</li>
                ))}
              </ol>
            </div>
          )}
          {can("sop.manage") && d.status === "effective" && (
            <div className="card space-y-2 p-4">
              <h2 className="font-semibold">Retire this document</h2>
              <input className="input" placeholder="Reason (required)" value={reason} onChange={(e) => setReason(e.target.value)} />
              <button className="btn-danger" disabled={reason.trim().length < 3 || retire.isPending} onClick={() => retire.mutate()}>Retire</button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
