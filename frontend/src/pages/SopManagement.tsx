import { useEffect, useState, type ChangeEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Upload } from "lucide-react";
import { toast } from "sonner";
import { api, type Schemas } from "@/api/client";
import { Banner, Spinner, StatusBadge, errMsg } from "@/components/ui";

type Job = Schemas["JobOut"];
type Doc = Schemas["DocumentOut"];
interface Step { step_no: number; action: string; parameters: Record<string, unknown>; is_critical: boolean; source_page: number | null; reviewed?: boolean }
const STAGES: Record<string, string> = { queued: "Queued", parsing: "Parsing pages", extracting: "Extracting metadata and steps", embedding: "Embedding passages", ready: "Ready to review" };

export default function SopManagement() {
  const qc = useQueryClient();
  const [params] = useSearchParams();
  const gapId = params.get("gap") ?? undefined;
  const [jobId, setJobId] = useState<string | null>(null);
  const [published, setPublished] = useState<Doc | null>(null);
  const docs = useQuery({ queryKey: ["docs-mgmt"], queryFn: () => api<Doc[]>("/documents") });
  const gap = useQuery({ queryKey: ["gaps"], enabled: !!gapId, queryFn: () => api<Schemas["GapOut"][]>("/gaps") });
  const gapQ = gap.data?.find((g) => g.id === gapId);

  async function onFile(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]; e.target.value = "";
    if (!file) return;
    const fd = new FormData(); fd.append("file", file);
    try { const r = await api<Schemas["JobCreated"]>("/documents/extract", { method: "POST", body: fd }); setJobId(r.job_id); setPublished(null); }
    catch (err) { toast.error(errMsg(err)); }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">SOP management</h1>
        <Link to="/gaps" className="text-sm text-brand-700 underline">Knowledge gaps →</Link>
      </div>
      <Banner tone="blue">This demo uses a free AI tier. Do not upload confidential or proprietary data.</Banner>
      {gapQ && <Banner tone="amber">Publishing from a knowledge gap. Question: <b>&nbsp;{gapQ.question}</b></Banner>}
      {!jobId && !published && (
        <label className="card flex cursor-pointer flex-col items-center gap-2 border-2 border-dashed p-10 text-slate-600 hover:border-brand-500" data-tour="upload-zone">
          <Upload size={32} /><span className="font-semibold">Upload a PDF or DOCX (max 10 MB, 80 pages)</span>
          <span className="text-sm">Metadata and steps are auto-filled for you to review. Nothing is searchable until you publish.</span>
          <input type="file" accept=".pdf,.docx" className="hidden" onChange={onFile} />
        </label>
      )}
      {jobId && !published && <Wizard jobId={jobId} gapId={gapId} onCancel={() => setJobId(null)}
        onPublished={(d) => { setPublished(d); setJobId(null); void qc.invalidateQueries(); }} />}
      {published && (
        <div className="card flex items-center justify-between gap-3 p-5">
          <div className="flex items-center gap-3"><CheckCircle2 className="text-green-600" />
            <div><b>{published.doc_code} v{published.version}</b> is now effective{published.version > 1 ? "; the previous version was superseded." : "."}</div></div>
          <div className="flex gap-2"><Link className="btn-secondary" to={`/sops/${published.id}`}>View</Link>
            <button className="btn-primary" onClick={() => setPublished(null)}>Upload another</button></div>
        </div>
      )}
      <div>
        <h2 className="mb-2 font-semibold">All documents</h2>
        {docs.isLoading && <Spinner />}
        <div className="card overflow-x-auto"><table className="w-full text-left text-sm">
          <thead className="bg-slate-50 text-slate-600"><tr>{["Code", "Title", "Version", "Status", "Change note"].map((h) => <th key={h} className="px-3 py-2 font-semibold">{h}</th>)}</tr></thead>
          <tbody>{docs.data?.map((d) => (
            <tr key={d.id} className="border-t border-slate-100"><td className="px-3 py-2"><Link className="text-brand-700 underline" to={`/sops/${d.id}`}>{d.doc_code}</Link></td>
              <td className="px-3 py-2">{d.title}</td><td className="px-3 py-2">v{d.version}</td><td className="px-3 py-2"><StatusBadge status={d.status} /></td>
              <td className="px-3 py-2 text-slate-500">{d.change_note}</td></tr>))}</tbody></table></div>
      </div>
    </div>
  );
}

function Wizard({ jobId, gapId, onCancel, onPublished }: { jobId: string; gapId?: string; onCancel: () => void; onPublished: (d: Doc) => void }) {
  const [job, setJob] = useState<Job | null>(null);
  const [meta, setMeta] = useState({ doc_code: "", title: "", doc_type: "SOP", department: "", equipment: "", change_note: "" });
  const [steps, setSteps] = useState<Step[]>([]);
  const [filled, setFilled] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let stop = false;
    const tick = async () => {
      try {
        const j = await api<Job>(`/documents/jobs/${jobId}`);
        if (stop) return; setJob(j);
        if (j.status !== "ready" && j.status !== "failed") setTimeout(tick, 1000);
      } catch (e) { if (!stop) toast.error(errMsg(e)); }
    };
    void tick(); return () => { stop = true; };
  }, [jobId]);

  useEffect(() => {
    if (job?.status === "ready" && job.preview && !filled) {
      const m = job.preview.metadata as Record<string, string>;
      setMeta({ doc_code: m.doc_code ?? "", title: m.title ?? "", doc_type: m.doc_type ?? "SOP", department: m.department ?? "", equipment: m.equipment ?? "", change_note: "" });
      setSteps((job.preview.steps as Step[]) ?? []); setFilled(true);
    }
  }, [job, filled]);

  const existing = useQuery({
    queryKey: ["exists", meta.doc_code], enabled: meta.doc_code.length > 2,
    queryFn: () => api<Doc[]>(`/documents?q=${encodeURIComponent(meta.doc_code)}`).then((r) => r.filter((d) => d.doc_code === meta.doc_code)),
  });
  const isNewVersion = !!existing.data?.length;
  const setM = (k: keyof typeof meta) => (e: { target: { value: string } }) => setMeta({ ...meta, [k]: e.target.value });

  async function publish() {
    setBusy(true);
    try {
      const doc = await api<Doc>("/documents/publish", { method: "POST", json: { job_id: jobId, ...meta, department: meta.department || null, equipment: meta.equipment || null,
        change_note: meta.change_note || null, gap_id: gapId ?? null, steps: steps.map((s, i) => ({ ...s, step_no: i + 1 })) } });
      toast.success(`Published ${doc.doc_code} v${doc.version}`); onPublished(doc);
    } catch (e) { toast.error(errMsg(e)); } finally { setBusy(false); }
  }

  if (!job || (job.status !== "ready" && job.status !== "failed")) {
    return <div className="card space-y-3 p-6" data-testid="job-progress"><div className="font-semibold">{STAGES[job?.status ?? "queued"]}…</div>
      <div className="h-2 overflow-hidden rounded-full bg-slate-200"><div className="h-full bg-brand-600 transition-all" style={{ width: `${job?.progress ?? 5}%` }} /></div></div>;
  }
  if (job.status === "failed") {
    return <div className="space-y-3"><Banner tone="red">{job.error}</Banner><button className="btn-secondary" onClick={onCancel}>Try another file</button></div>;
  }
  const warnings = (job.preview?.warnings as string[]) ?? [];
  const ocr = (job.preview?.ocr_pages as number[]) ?? [];
  return (
    <div className="space-y-4" data-testid="publish-form">
      {warnings.map((w) => <Banner key={w} tone="amber">{w}</Banner>)}
      {ocr.length > 0 && <Banner tone="blue">Pages transcribed by AI (OCR): {ocr.join(", ")}. Please proofread.</Banner>}
      <div className="card grid gap-3 p-4 md:grid-cols-2">
        <div><label className="label">Document code</label><input className="input" value={meta.doc_code} onChange={setM("doc_code")} /></div>
        <div><label className="label">Title</label><input className="input" value={meta.title} onChange={setM("title")} /></div>
        <div><label className="label">Type</label><select className="input" value={meta.doc_type} onChange={setM("doc_type")}>
          {["SOP", "protocol", "troubleshooting_guide", "manual"].map((t) => <option key={t}>{t}</option>)}</select></div>
        <div><label className="label">Department</label><input className="input" value={meta.department} onChange={setM("department")} /></div>
        <div><label className="label">Equipment / assay</label><input className="input" value={meta.equipment} onChange={setM("equipment")} /></div>
        <div><label className="label">Change note {isNewVersion ? "(required — new version)" : "(optional)"}</label>
          <input className="input" value={meta.change_note} onChange={setM("change_note")} /></div>
      </div>
      {isNewVersion && <Banner tone="amber">{meta.doc_code} already exists (v{Math.max(...existing.data!.map((d) => d.version))}). Publishing creates a new version and supersedes the current one.</Banner>}
      {meta.doc_type !== "troubleshooting_guide" && meta.doc_type !== "manual" && (
        <div className="card p-4">
          <div className="mb-2 flex items-center justify-between"><h2 className="font-semibold">Extracted steps ({steps.length})</h2>
            <button className="btn-secondary px-3 py-1" onClick={() => setSteps([...steps, { step_no: steps.length + 1, action: "", parameters: {}, is_critical: false, source_page: null }])}>Add step</button></div>
          {steps.length === 0 && <p className="text-sm text-slate-500">No discrete steps detected — the document will still be searchable.</p>}
          <div className="space-y-2">{steps.map((s, i) => (
            <div key={i} className="flex items-start gap-2"><span className="w-6 pt-2 text-right text-sm font-semibold">{i + 1}</span>
              <textarea className="input flex-1" rows={2} value={s.action} onChange={(e) => setSteps(steps.map((x, k) => (k === i ? { ...x, action: e.target.value } : x)))} />
              <label className="flex items-center gap-1 pt-2 text-xs"><input type="checkbox" checked={s.is_critical} onChange={(e) => setSteps(steps.map((x, k) => (k === i ? { ...x, is_critical: e.target.checked } : x)))} />critical</label>
              <button className="px-2 pt-2 text-red-600" onClick={() => setSteps(steps.filter((_, k) => k !== i))} aria-label="Remove step">✕</button></div>))}</div>
        </div>
      )}
      <div className="text-sm text-slate-500">{String(job.preview?.chunk_count)} passages · {String(job.preview?.page_count ?? "—")} pages</div>
      <div className="flex gap-2">
        <button className="btn-primary" data-tour="publish-btn" disabled={busy || !meta.doc_code || !meta.title || (isNewVersion && !meta.change_note.trim())} onClick={publish}>Publish</button>
        <button className="btn-secondary" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}
