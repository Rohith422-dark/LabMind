import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, Plus, RefreshCw, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api, type Schemas } from "@/api/client";
import { useAuth } from "@/context/AuthContext";
import { Empty, Spinner, StatusBadge, errMsg } from "@/components/ui";
import SopManagement from "@/pages/SopManagement";

const TYPES = [["", "All types"], ["SOP", "SOP"], ["protocol", "Protocol"], ["troubleshooting_guide", "Troubleshooting guide"], ["manual", "Manual"]];

export default function SopLibrary() {
  const { can } = useAuth();
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const manage = can("sop.manage");
  const updateCode = params.get("update") ?? undefined;
  const [uploading, setUploading] = useState(!!params.get("gap"));
  const [q, setQ] = useState("");
  const [type, setType] = useState("");
  const [equipment, setEquipment] = useState("");
  const [showOld, setShowOld] = useState(false);
  const qs = new URLSearchParams();
  if (q) qs.set("q", q);
  if (type) qs.set("type", type);
  if (equipment) qs.set("equipment", equipment);
  if (!showOld) qs.set("status", "effective");
  const docs = useQuery({ queryKey: ["docs", q, type, equipment, showOld], queryFn: () => api<Schemas["DocumentOut"][]>(`/documents?${qs}`) });
  const all = useQuery({ queryKey: ["docs-all"], queryFn: () => api<Schemas["DocumentOut"][]>("/documents?status=effective") });
  const equipments = [...new Set((all.data ?? []).map((d) => d.equipment).filter(Boolean))] as string[];
  const del = useMutation({
    mutationFn: (code: string) => api(`/documents/code/${encodeURIComponent(code)}`, { method: "DELETE" }),
    onSuccess: () => { toast.success("Document and all its versions deleted"); void qc.invalidateQueries(); }, onError: (e) => toast.error(errMsg(e)),
  });
  const panelOpen = manage && (uploading || !!updateCode);
  const closePanel = () => { setUploading(false); if (updateCode) setParams({}, { replace: true }); void qc.invalidateQueries(); };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div><h1 className="text-[26px] font-semibold leading-tight">SOP library</h1>
          <p className="text-sm text-slate-600">{manage ? "Browse, upload, update and delete documents. Opening a document shows its current version; earlier versions are in its history." : "The current approved version of each document."}</p></div>
        {manage && !panelOpen && <button className="btn-primary" onClick={() => setUploading(true)}><Plus size={16} />Upload document</button>}
      </div>
      {panelOpen && (
        <div className="card p-4"><div className="mb-2 flex items-center justify-between"><h2 className="font-semibold">{updateCode ? `Update ${updateCode}` : "Upload a new document"}</h2>
          <button className="btn-secondary px-3 py-1" onClick={closePanel}>Close</button></div>
          <SopManagement embedded forceCode={updateCode} onClose={closePanel} /></div>)}
      <div className="card grid gap-3 p-4 md:grid-cols-4">
        <input className="input md:col-span-2" placeholder="Search code, title, equipment or content…" value={q} onChange={(e) => setQ(e.target.value)} />
        <select className="input" value={type} onChange={(e) => setType(e.target.value)}>{TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
        <select className="input" value={equipment} onChange={(e) => setEquipment(e.target.value)}>
          <option value="">All equipment</option>{equipments.map((e) => <option key={e}>{e}</option>)}</select>
        <label className="flex items-center gap-2 text-sm text-slate-600"><input type="checkbox" checked={showOld} onChange={(e) => setShowOld(e.target.checked)} />Include superseded / retired</label>
      </div>
      {docs.isLoading && <Spinner label="Loading documents…" />}
      {docs.data?.length === 0 && <Empty title="No documents match">{manage ? "Upload a document to get started." : "Try a different search, or ask a Senior Analyst to upload the document."}</Empty>}
      <div className="grid gap-3 md:grid-cols-2">
        {docs.data?.map((d) => (
          <div key={d.id} className="card flex flex-col gap-3 p-4 transition hover:border-brand-500">
            <Link to={`/sops/${d.id}`} className="flex gap-3">
              <FileText className="mt-1 shrink-0 text-brand-600" />
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2"><span className="font-semibold">{d.doc_code}</span>
                  <span className="text-sm text-slate-500">v{d.version}</span><StatusBadge status={d.status} /></div>
                <div className="truncate text-slate-800">{d.title}</div>
                <div className="mt-1 text-xs text-slate-500">{d.doc_type.replace("_", " ")} · {d.equipment ?? "—"} · {d.department ?? "—"}{d.page_count ? ` · ${d.page_count} pages` : ""}</div>
                {d.change_note && <div className="mt-1 text-xs text-slate-500">Latest change: {d.change_note}</div>}
              </div>
            </Link>
            {manage && d.status === "effective" && (
              <div className="flex justify-end gap-2 border-t border-slate-100 pt-2">
                <button className="btn-secondary px-3 py-1" onClick={() => { setUploading(false); setParams({ update: d.doc_code }); window.scrollTo({ top: 0, behavior: "smooth" }); }}><RefreshCw size={14} />Update (new version)</button>
                <button className="btn-secondary px-3 py-1 text-red-700" onClick={() => { if (window.confirm(`Permanently delete ${d.doc_code} and ALL its versions? This cannot be undone.`)) del.mutate(d.doc_code); }}><Trash2 size={14} />Delete</button>
              </div>)}
          </div>
        ))}
      </div>
    </div>
  );
}
