import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { FileText } from "lucide-react";
import { api, type Schemas } from "@/api/client";
import { useAuth } from "@/context/AuthContext";
import { Empty, Spinner, StatusBadge } from "@/components/ui";

const TYPES = [["", "All types"], ["SOP", "SOP"], ["protocol", "Protocol"], ["troubleshooting_guide", "Troubleshooting guide"], ["manual", "Manual"]];

export default function SopLibrary() {
  const { can } = useAuth();
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

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-2xl font-bold">SOP library</h1>
        {can("sop.manage") && <Link to="/sop-management" className="btn-primary">Upload / manage</Link>}
      </div>
      <div className="card mb-4 grid gap-3 p-4 md:grid-cols-4">
        <input className="input md:col-span-2" placeholder="Search code, title, equipment or content…" value={q} onChange={(e) => setQ(e.target.value)} />
        <select className="input" value={type} onChange={(e) => setType(e.target.value)}>{TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
        <select className="input" value={equipment} onChange={(e) => setEquipment(e.target.value)}>
          <option value="">All equipment</option>{equipments.map((e) => <option key={e}>{e}</option>)}</select>
        <label className="flex items-center gap-2 text-sm text-slate-600"><input type="checkbox" checked={showOld} onChange={(e) => setShowOld(e.target.checked)} />Include superseded / retired</label>
      </div>
      {docs.isLoading && <Spinner label="Loading documents…" />}
      {docs.data?.length === 0 && <Empty title="No documents match">Try a different search, or ask a Senior Analyst to upload the document.</Empty>}
      <div className="grid gap-3 md:grid-cols-2">
        {docs.data?.map((d) => (
          <Link key={d.id} to={`/sops/${d.id}`} className="card flex gap-3 p-4 transition hover:border-brand-500">
            <FileText className="mt-1 shrink-0 text-brand-600" />
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2"><span className="font-semibold">{d.doc_code}</span>
                <span className="text-sm text-slate-500">v{d.version}</span><StatusBadge status={d.status} /></div>
              <div className="truncate text-slate-800">{d.title}</div>
              <div className="mt-1 text-xs text-slate-500">{d.doc_type.replace("_", " ")} · {d.equipment ?? "—"} · {d.department ?? "—"}{d.page_count ? ` · ${d.page_count} pages` : ""}</div>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
