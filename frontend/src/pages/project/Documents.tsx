import { useRef, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Eye, FileUp, History, RefreshCw, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api, apiBlob, type Schemas } from "@/api/client";
import { Banner, Empty, Modal, Pager, Spinner, StatusBadge, errMsg, fmtDate } from "@/components/ui";
import { useAuth } from "@/context/AuthContext";
import type { TabProps } from "@/pages/ProjectDetail";

type Doc = Schemas["ProjectDocumentOut"];
type Page = Schemas["ProjectDocumentPage"];
const PAGE = 15;
const ACCEPT = ".pdf,.docx,.txt,.md,.csv";
const size = (b: number) => (b > 1048576 ? `${(b / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`);

export default function Documents({ project: p, canWrite, isOwner }: TabProps) {
  const qc = useQueryClient();
  const { me } = useAuth();
  const [f, setF] = useState({ q: "", category: "", file_type: "" });
  const [offset, setOffset] = useState(0);
  const [viewing, setViewing] = useState<Doc | null>(null);
  const [versionsOf, setVersionsOf] = useState<Doc | null>(null);
  const [replacing, setReplacing] = useState<Doc | null>(null);
  const qs = new URLSearchParams({ limit: String(PAGE), offset: String(offset) });
  (Object.entries(f) as [string, string][]).forEach(([k, v]) => v && qs.set(k, v));
  const list = useQuery({ queryKey: ["documents", p.id, qs.toString()], queryFn: () => api<Page>(`/projects/${p.id}/documents?${qs}`) });
  const refresh = () => { void qc.invalidateQueries({ queryKey: ["documents", p.id] }); void qc.invalidateQueries({ queryKey: ["project", p.id] }); };

  const del = useMutation({
    mutationFn: (d: Doc) => api(`/projects/${p.id}/documents/${d.id}`, { method: "DELETE" }),
    onSuccess: () => { toast.success("Document removed from the project and from the assistant's index"); refresh(); }, onError: (e) => toast.error(errMsg(e)),
  });
  const download = async (d: Doc) => {
    try {
      const blob = await apiBlob(`/projects/${p.id}/documents/${d.id}/file`);
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob); a.download = d.filename; a.click(); URL.revokeObjectURL(a.href);
    } catch (e) { toast.error(errMsg(e)); }
  };
  const mayChange = (d: Doc) => canWrite && (isOwner || d.uploaded_by === me?.user.id);

  return (
    <div className="space-y-4">
      {canWrite && <Upload projectId={p.id} onDone={refresh} />}
      <div className="card grid gap-3 p-4 md:grid-cols-4">
        <input aria-label="Search documents" className="input md:col-span-2" placeholder="Search titles and document text…" value={f.q} onChange={(e) => { setOffset(0); setF({ ...f, q: e.target.value }); }} />
        <input aria-label="Category" className="input" placeholder="Category" value={f.category} onChange={(e) => { setOffset(0); setF({ ...f, category: e.target.value }); }} />
        <select aria-label="File type" className="input" value={f.file_type} onChange={(e) => { setOffset(0); setF({ ...f, file_type: e.target.value }); }}>
          <option value="">Any type</option>{["pdf", "docx", "txt", "md", "csv"].map((t) => <option key={t} value={t}>{t.toUpperCase()}</option>)}</select>
      </div>
      {list.isLoading && <Spinner label="Loading documents…" />}
      {list.isError && <Banner tone="red">{errMsg(list.error)}</Banner>}
      {list.data?.total === 0 && <Empty title="No documents">{canWrite ? "Upload protocols, reports or data files. The assistant can cite them by page and section." : "Nothing here yet."}</Empty>}
      {!!list.data?.items.length && (
        <div className="card overflow-x-auto">
          <table className="w-full text-left text-sm" data-testid="document-table">
            <thead className="bg-slate-50 text-slate-600"><tr>{["Title", "Type", "Version", "Size", "Indexed", "Uploaded by", ""].map((h) => <th key={h} className="px-3 py-2 font-semibold">{h}</th>)}</tr></thead>
            <tbody>{list.data.items.map((d) => (
              <tr key={d.id} className="border-t border-slate-100 align-top">
                <td className="px-3 py-2"><div className="font-medium">{d.title}</div><div className="text-xs text-slate-500">{d.filename}{d.category ? ` · ${d.category}` : ""}{d.page_count ? ` · ${d.page_count} pages` : ""}</div>
                  {d.warnings.map((w, i) => <div key={i} className="mt-1 text-xs text-amber-700">⚠ {w}</div>)}</td>
                <td className="px-3 py-2 uppercase">{d.file_type}</td><td className="px-3 py-2">v{d.version}</td><td className="px-3 py-2">{size(d.size_bytes)}</td>
                <td className="px-3 py-2"><StatusBadge status={d.chunks > 0 ? "ready" : "unavailable"} /> <span className="text-xs text-slate-500">{d.chunks} passages</span></td>
                <td className="px-3 py-2 text-xs text-slate-500">{d.uploaded_by_name}<div>{fmtDate(d.created_at)}</div></td>
                <td className="px-3 py-2"><div className="flex flex-wrap justify-end gap-1">
                  <button className="btn-secondary px-2 py-1" aria-label={`View text of ${d.title}`} onClick={() => setViewing(d)}><Eye size={14} /></button>
                  <button className="btn-secondary px-2 py-1" aria-label={`Download ${d.title}`} onClick={() => download(d)}><Download size={14} /></button>
                  {d.version > 1 && <button className="btn-secondary px-2 py-1" aria-label={`Versions of ${d.title}`} onClick={() => setVersionsOf(d)}><History size={14} /></button>}
                  {mayChange(d) && <button className="btn-secondary px-2 py-1" aria-label={`Replace ${d.title}`} onClick={() => setReplacing(d)}><RefreshCw size={14} /></button>}
                  {mayChange(d) && <button className="btn-secondary px-2 py-1 text-red-700" aria-label={`Delete ${d.title}`} onClick={() => { if (window.confirm(`Delete “${d.title}” and every version of it? The assistant will no longer be able to use it.`)) del.mutate(d); }}><Trash2 size={14} /></button>}
                </div></td>
              </tr>))}</tbody>
          </table>
        </div>)}
      {list.data && <Pager total={list.data.total} limit={PAGE} offset={offset} onChange={setOffset} />}
      {viewing && <Viewer projectId={p.id} doc={viewing} onClose={() => setViewing(null)} />}
      {versionsOf && <Versions projectId={p.id} doc={versionsOf} onClose={() => setVersionsOf(null)} />}
      {replacing && <Replace projectId={p.id} doc={replacing} onClose={() => setReplacing(null)} onDone={() => { setReplacing(null); refresh(); }} />}
    </div>
  );
}

function Upload({ projectId, onDone }: { projectId: string; onDone: () => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [title, setTitle] = useState("");
  const [category, setCategory] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const m = useMutation({
    mutationFn: () => { const fd = new FormData(); fd.append("file", file!); if (title) fd.append("title", title); if (category) fd.append("category", category); return api<Doc>(`/projects/${projectId}/documents`, { method: "POST", body: fd }); },
    onSuccess: (d) => { toast.success(`“${d.title}” uploaded and indexed (${d.chunks} passages)`); setFile(null); setTitle(""); setCategory(""); if (input.current) input.current.value = ""; onDone(); },
    onError: (e) => toast.error(errMsg(e)),
  });
  return (
    <form className="card flex flex-wrap items-end gap-3 p-4" onSubmit={(e: FormEvent) => { e.preventDefault(); if (file) m.mutate(); }}>
      <div><label className="label" htmlFor="up-file">File (PDF, DOCX, TXT, MD, CSV — max 10 MB)</label>
        <input ref={input} id="up-file" type="file" accept={ACCEPT} className="block text-sm" onChange={(e) => { const f = e.target.files?.[0] ?? null; setFile(f); if (f && !title) setTitle(f.name.replace(/\.[^.]+$/, "")); }} /></div>
      <div className="min-w-[12rem] flex-1"><label className="label" htmlFor="up-title">Title</label><input id="up-title" className="input" maxLength={240} value={title} onChange={(e) => setTitle(e.target.value)} /></div>
      <div><label className="label" htmlFor="up-cat">Category</label><input id="up-cat" className="input" maxLength={80} placeholder="e.g. protocol" value={category} onChange={(e) => setCategory(e.target.value)} /></div>
      <button className="btn-primary" disabled={!file || m.isPending}><FileUp size={16} />{m.isPending ? "Reading & indexing…" : "Upload"}</button>
    </form>
  );
}

function Replace({ projectId, doc, onClose, onDone }: { projectId: string; doc: Doc; onClose: () => void; onDone: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const m = useMutation({
    mutationFn: () => { const fd = new FormData(); fd.append("file", file!); return api<Doc>(`/projects/${projectId}/documents/${doc.id}/replace`, { method: "POST", body: fd }); },
    onSuccess: (d) => { toast.success(`Now at version ${d.version}. The previous version is no longer used by the assistant.`); onDone(); }, onError: (e) => toast.error(errMsg(e)),
  });
  return (
    <Modal title={`Replace “${doc.title}”`} onClose={onClose}>
      <div className="space-y-3">
        <Banner tone="amber">The new file becomes version {doc.version + 1}. The old version stays downloadable as history but is removed from search and from the assistant immediately.</Banner>
        <input type="file" accept={ACCEPT} aria-label="New version" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        <div className="flex justify-end gap-2"><button className="btn-secondary" onClick={onClose}>Cancel</button><button className="btn-primary" disabled={!file || m.isPending} onClick={() => m.mutate()}>{m.isPending ? "Uploading…" : "Replace"}</button></div>
      </div>
    </Modal>
  );
}

function Versions({ projectId, doc, onClose }: { projectId: string; doc: Doc; onClose: () => void }) {
  const q = useQuery({ queryKey: ["doc-versions", projectId, doc.id], queryFn: () => api<Doc[]>(`/projects/${projectId}/documents/${doc.id}/versions`) });
  return (
    <Modal title={`Versions of “${doc.title}”`} onClose={onClose}>
      {q.isLoading && <Spinner />}
      <ul className="space-y-2 text-sm">{q.data?.map((d) => <li key={d.id} className="flex justify-between rounded-md border border-slate-200 p-2"><span><b>v{d.version}</b> · {d.filename} · {fmtDate(d.created_at)} · {d.uploaded_by_name}</span><StatusBadge status={d.status === "ready" ? "ready" : "superseded"} /></li>)}</ul>
    </Modal>
  );
}

function Viewer({ projectId, doc, onClose }: { projectId: string; doc: Doc; onClose: () => void }) {
  const q = useQuery({ queryKey: ["doc-content", projectId, doc.id], queryFn: () => api<{ pages: { page: number | null; text: string }[]; warnings: string[] }>(`/projects/${projectId}/documents/${doc.id}/content`) });
  return (
    <Modal title={doc.title} onClose={onClose} wide>
      {q.isLoading && <Spinner />}
      {q.isError && <Banner tone="red">{errMsg(q.error)}</Banner>}
      <p className="mb-3 text-sm text-slate-600">Extracted text, as the assistant sees it. Page numbers are kept where the format has them.</p>
      <div className="max-h-[60vh] space-y-4 overflow-y-auto">{q.data?.pages.map((pg, i) => (
        <section key={i}><div className="mb-1 text-xs font-semibold uppercase text-slate-500">{pg.page ? `Page ${pg.page}` : "Text"}</div><div className="whitespace-pre-wrap rounded-md bg-slate-50 p-3 text-sm">{pg.text}</div></section>))}</div>
    </Modal>
  );
}
