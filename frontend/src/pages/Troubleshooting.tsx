import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { FileDown, FolderDown, Send } from "lucide-react";
import { toast } from "sonner";
import { api, streamNdjson, type Schemas } from "@/api/client";
import type { Citation, CompareRow, DiagnoseResult, ExternalResult, SopRef, TsEvent, TsQuestion } from "@/api/types";
import { ComparisonTable } from "@/components/ComparisonTable";
import { ExternalWarningCard } from "@/components/ExternalWarningCard";
import { SourceDrawer } from "@/components/SourceDrawer";
import { Banner, Spinner, errMsg } from "@/components/ui";
import { useAuth } from "@/context/AuthContext";

interface Turn { role: "user" | "system"; text: string }
type Exp = Schemas["ExperimentOut"];

/** Turn a recorded experiment into the free-text "what I did" the troubleshooter compares with the SOP. */
function experimentToNarration(e: Exp): string {
  const names = (xs: unknown[], f: (x: Record<string, unknown>) => string) => xs.map((x) => f(x as Record<string, unknown>)).filter(Boolean).join("; ");
  const lines = [`Experiment ${e.identifier} - ${e.title}${e.performed_at ? ` (${new Date(e.performed_at).toLocaleDateString()})` : ""}.`];
  if (e.objective) lines.push(`Objective: ${e.objective}`);
  const reagents = names(e.reagents, (r) => [r.name, r.lot_no && `lot ${r.lot_no}`, r.quantity != null && `${r.quantity} ${r.unit ?? ""}`.trim()].filter(Boolean).join(" "));
  if (reagents) lines.push(`Reagents used: ${reagents}.`);
  const equipment = names(e.equipment, (x) => String(x.name ?? ""));
  if (equipment) lines.push(`Equipment: ${equipment}.`);
  const conditions = Object.entries(e.conditions ?? {}).map(([k, v]) => `${k} ${String(v)}`).join("; ");
  if (conditions) lines.push(`Conditions: ${conditions}.`);
  const params = names(e.parameters, (x) => `${x.name} ${x.value ?? x.text_value ?? ""}${x.unit ? ` ${x.unit}` : ""}`);
  if (params) lines.push(`Measured values: ${params}.`);
  if (e.observations) lines.push(`Observations: ${e.observations}`);
  if (e.results) lines.push(`Results: ${e.results}`);
  return lines.join("\n");
}

/** Pick one of the user's own projects and one of its experiments; the record becomes the narration (appended, never silently replacing). */
function ImportFromProject({ onImport }: { onImport: (text: string, e: Exp) => void }) {
  const [projectId, setProjectId] = useState("");
  const [expId, setExpId] = useState("");
  const projects = useQuery({ queryKey: ["ts-projects"], queryFn: () => api<Schemas["ProjectOut"][]>("/projects") });
  const exps = useQuery({ queryKey: ["ts-exps", projectId], enabled: !!projectId,
    queryFn: () => api<Schemas["ExperimentPage"]>(`/projects/${projectId}/experiments?limit=100&sort=performed_at&order=desc`) });
  const chosen = exps.data?.items.find((x) => x.id === expId);
  if (projects.data?.length === 0) return null;
  return (
    <div className="space-y-2 rounded-lg border border-slate-200 bg-slate-50 p-3" data-testid="ts-import">
      <div className="flex items-center gap-2 text-sm font-medium text-slate-800"><FolderDown size={16} className="text-brand-600" />Import what you did from a project experiment</div>
      <div className="grid gap-2 sm:grid-cols-2">
        <select aria-label="Project" className="input" value={projectId} onChange={(e) => { setProjectId(e.target.value); setExpId(""); }}>
          <option value="">Choose a project…</option>{projects.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select>
        <select aria-label="Experiment" className="input" value={expId} disabled={!projectId || exps.isLoading} onChange={(e) => setExpId(e.target.value)}>
          <option value="">{exps.isLoading ? "Loading…" : exps.data?.items.length === 0 ? "No experiments in this project" : "Choose an experiment…"}</option>
          {exps.data?.items.map((x) => <option key={x.id} value={x.id}>{x.identifier} · {x.title}{x.outcome !== "unknown" ? ` (${x.outcome})` : ""}</option>)}</select>
      </div>
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs text-slate-600">The record&apos;s text is added to the box below so you can edit it. It is handled like anything you type here.</p>
        <button type="button" className="btn-secondary shrink-0" disabled={!chosen} onClick={() => chosen && onImport(experimentToNarration(chosen), chosen)}>Import</button>
      </div>
    </div>
  );
}

export default function Troubleshooting() {
  const [params] = useSearchParams();
  const { can } = useAuth();
  const sops = useQuery({ queryKey: ["sops-ts"], queryFn: () => api<Schemas["DocumentOut"][]>("/documents?status=effective&type=SOP") });
  const [docId, setDocId] = useState("");
  const [symptom, setSymptom] = useState(params.get("symptom") ?? "");
  const [narration, setNarration] = useState(params.get("narration") ?? "");
  const [reply, setReply] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sop, setSop] = useState<SopRef | null>(null);
  const [rows, setRows] = useState<CompareRow[]>([]);
  const [questions, setQuestions] = useState<TsQuestion[]>([]);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [stage, setStage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [diag, setDiag] = useState<DiagnoseResult | null>(null);
  const [gapId, setGapId] = useState<string | null>(null);
  const [consent, setConsent] = useState<"ask" | "declined" | "loading" | "done" | null>(null);
  const [external, setExternal] = useState<ExternalResult | null>(null);
  const [sopRequested, setSopRequested] = useState(false);
  const [source, setSource] = useState<Citation | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { const n = params.get("narration"); if (n) setNarration(n); const s = params.get("symptom"); if (s) setSymptom(s); }, [params]);

  const onEvent = (e: TsEvent) => {
    if (e.type === "stage") setStage(e.stage);
    else if (e.type === "session") { setSessionId(e.session_id); setSop(e.document); }
    else if (e.type === "comparison") setRows(e.rows);
    else if (e.type === "questions") setQuestions((prev) => [...prev.filter((q) => !e.questions.some((n) => n.key === q.key)), ...e.questions]);
    else if (e.type === "no_sop") { setGapId(e.gap_id); setConsent("ask"); }
    else if (e.type === "error") setError(e.message);
  };

  async function run(path: string, body: unknown) {
    setBusy(true); setError(null); setStage("Working…");
    try { await streamNdjson<TsEvent>(path, body, onEvent); } catch (e) { setError(errMsg(e)); } finally { setBusy(false); setStage(null); }
  }

  async function start() {
    setTurns([{ role: "user", text: narration }]); setDiag(null); setQuestions([]); setRows([]); setConsent(null); setExternal(null);
    await run("/troubleshoot/start", { document_id: docId || null, symptom, narration });
  }
  async function send() {
    const t = reply.trim(); if (!t || !sessionId) return;
    setTurns((p) => [...p, { role: "user", text: t }]); setReply(""); setQuestions([]);
    await run(`/troubleshoot/${sessionId}/message`, { text: t });
  }
  async function diagnose() {
    if (!sessionId) return;
    setBusy(true); setError(null); setStage("Ranking causes");
    try { setDiag(await api<DiagnoseResult>(`/troubleshoot/${sessionId}/diagnose`, { method: "POST" })); }
    catch (e) { setError(errMsg(e)); } finally { setBusy(false); setStage(null); }
  }
  async function goExternal() {
    setConsent("loading");
    try { setExternal(await api<ExternalResult>("/chat/external", { method: "POST", json: { gap_id: gapId } })); setConsent("done"); }
    catch (e) { toast.error(errMsg(e)); setConsent("ask"); }
  }
  async function requestSop() {
    try { await api(`/gaps/${gapId}/request-sop`, { method: "PATCH" }); setSopRequested(true); toast.success("Official SOP requested"); } catch (e) { toast.error(errMsg(e)); }
  }
  async function openStep(stepNo: number) {
    if (!sop) return;
    try {
      const d = await api<Schemas["DocumentDetail"]>(`/documents/${sop.id}`);
      const s = d.steps.find((x) => x.step_no === stepNo);
      setSource({ n: stepNo, document_id: sop.id, chunk_id: "", doc_code: sop.doc_code, title: sop.title, version: sop.version, page: s?.source_page ?? 1, section: null, snippet: s?.action ?? "", score: 0 });
    } catch (e) { toast.error(errMsg(e)); }
  }

  function exportReport() {
    const esc = (s: string) => s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c] as string));
    const w = window.open("", "_blank"); if (!w) { toast.error("Allow pop-ups to export the report"); return; }
    const body = rows.map((r) => `<tr><td>${r.step_no ?? "—"}${r.is_critical ? " (critical)" : ""}</td><td>${esc(r.narrated ?? "not described")}</td><td>${esc(r.sop_action)}<br><small>${esc(r.sop_requirement)}</small></td><td>${r.status}</td></tr>`).join("");
    const causes = (diag?.diagnosis.causes ?? []).map((c) => `<li><b>${esc(c.cause)}</b> — ${esc(c.evidence)}</li>`).join("");
    w.document.write(`<html><head><title>Deviation report</title><style>body{font:14px sans-serif;padding:24px}table{border-collapse:collapse;width:100%}td,th{border:1px solid #999;padding:6px;text-align:left}</style></head><body>
      <h1>Deviation report</h1><p>SOP: ${esc(sop?.doc_code ?? "")} v${sop?.version} — ${esc(sop?.title ?? "")}<br>Symptom: ${esc(symptom)}<br>Generated: ${new Date().toLocaleString()}</p>
      <table><tr><th>Step</th><th>Your procedure</th><th>SOP requirement</th><th>Status</th></tr>${body}</table>
      <h2>Probable causes</h2><ol>${causes}</ol><p><i>Assistant suggestions only. The scientist makes the final decision.</i></p></body></html>`);
    w.document.close(); w.focus(); w.print();
  }

  const started = !!sessionId;
  const open = questions.filter((q) => !q.answered);
  return (
    <div>
      <h1 className="mb-1 text-2xl font-bold">Troubleshooting</h1>
      <p className="mb-4 text-sm text-slate-600">Describe what you did. Your steps are compared with the approved SOP by rules (not by the AI), so differences are exact.</p>
      {error && <div className="mb-3"><Banner tone="red">{error}</Banner></div>}
      <div className="grid gap-6 lg:grid-cols-2">
        <section className="space-y-3">
          {!started && consent === null && (
            <div className="card space-y-3 p-4">
              <div><label className="label">SOP</label>
                <select className="input" value={docId} onChange={(e) => setDocId(e.target.value)} data-tour="ts-sop">
                  <option value="">Auto-detect from the symptom</option>
                  {sops.data?.map((d) => <option key={d.id} value={d.id}>{d.doc_code} v{d.version} — {d.title}</option>)}</select></div>
              <div><label className="label">Symptom</label><input className="input" value={symptom} onChange={(e) => setSymptom(e.target.value)} placeholder="What went wrong?" /></div>
              {can("projects.use") && <ImportFromProject onImport={(text, e) => {
                setNarration((cur) => (cur.trim() ? `${cur.trim()}

${text}` : text));
                setSymptom((cur) => cur.trim() || (e.outcome === "failure" ? `${e.identifier} did not give the expected result` : cur));
                toast.success(`Imported ${e.identifier}. Review and edit it before comparing.`);
              }} />}
              <div><label className="label">What did you do? (free text, in order)</label>
                <textarea className="input" rows={7} value={narration} onChange={(e) => setNarration(e.target.value)} placeholder="Describe each step you carried out, in order, with the values you used." /></div>
              <button className="btn-primary" disabled={busy || symptom.trim().length < 3 || narration.trim().length < 3} onClick={start}>Compare with the SOP</button>
            </div>
          )}
          {(started || turns.length > 0) && (
            <div className="card space-y-3 p-4">
              <div className="space-y-2" data-testid="ts-conversation">
                {turns.map((t, i) => <div key={i} className="ml-auto w-fit max-w-[90%] whitespace-pre-wrap rounded-lg bg-brand-600 px-3 py-2 text-sm text-white">{t.text}</div>)}
                {open.map((q) => <div key={q.key} className="w-fit max-w-[90%] rounded-lg bg-slate-100 px-3 py-2 text-sm" data-testid="ts-question">{q.question}</div>)}
                {busy && stage && <Spinner label={stage + "…"} />}
              </div>
              {started && (
                <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); void send(); }}>
                  <input className="input flex-1" placeholder="Answer the questions above or add details…" value={reply} onChange={(e) => setReply(e.target.value)} disabled={busy} />
                  <button className="btn-primary" disabled={busy || !reply.trim()}><Send size={16} /></button>
                </form>
              )}
              {started && <button className="btn-secondary" data-tour="ts-diagnose" disabled={busy} onClick={diagnose}>Generate diagnosis{open.length ? ` (skip ${open.length} open question${open.length > 1 ? "s" : ""})` : ""}</button>}
            </div>
          )}
          {consent === "ask" && (
            <div className="card space-y-3 p-4" data-testid="consent-card">
              <p className="font-medium">I couldn&apos;t find a matching approved SOP for this. Would you like me to check online using AI?</p>
              <div className="flex gap-2"><button className="btn-primary" onClick={goExternal}>Yes, search online</button>
                <button className="btn-secondary" onClick={() => setConsent("declined")}>No, thanks</button></div>
            </div>
          )}
          {consent === "declined" && (
            <div className="card space-y-2 p-4 text-sm"><p>Please contact a Senior Analyst, or request an official SOP.</p>
              <button className="btn-secondary" disabled={sopRequested} onClick={requestSop}>{sopRequested ? "Official SOP requested" : "Request official SOP"}</button></div>
          )}
          {consent === "loading" && <Spinner label="Checking online (unverified)…" />}
          {external && <ExternalWarningCard res={external} requested={sopRequested} onFeedback={() => toast.success("Thanks")} onRequestSop={requestSop} />}
        </section>

        <section className="space-y-4">
          {sop && <Banner tone="blue">Compared against <b>{sop.doc_code} v{sop.version}</b> — {sop.title}</Banner>}
          {rows.length > 0 && <ComparisonTable rows={rows} onOpenStep={openStep} />}
          {diag && (
            <div className="card space-y-3 p-4" data-testid="diagnosis">
              <div className="flex items-center justify-between"><h2 className="font-semibold">Probable causes</h2>
                <button className="btn-secondary px-3 py-1" onClick={exportReport}><FileDown size={16} />Export deviation report</button></div>
              {diag.warnings.map((w) => <Banner key={w} tone="red">{w}</Banner>)}
              {diag.diagnosis.deviation_advice && <Banner tone="amber">{diag.diagnosis.deviation_advice}</Banner>}
              {diag.diagnosis.causes.length === 0 && <p className="text-sm text-slate-500">No deviations from the SOP were found. Check consumables, reagent lots and instrument condition.</p>}
              <ol className="space-y-2 text-sm">{diag.diagnosis.causes.map((c) => (
                <li key={c.rank} className="rounded-md border border-slate-200 p-3"><b>{c.rank}. {c.cause}</b>
                  <div className="text-slate-600">{c.evidence}</div>
                  <div className="mt-1 flex gap-2 text-xs">
                    {c.linked_step_no && <button className="text-brand-700 underline" onClick={() => openStep(c.linked_step_no!)}>SOP step {c.linked_step_no}</button>}
                    {c.guide_citation && diag.citations[c.guide_citation - 1] && <button className="text-brand-700 underline" onClick={() => setSource(diag.citations[c.guide_citation! - 1])}>Guide [{c.guide_citation}]</button>}</div></li>))}</ol>
              {diag.diagnosis.next_actions.length > 0 && (<div><h3 className="font-semibold">Recommended next actions</h3>
                <ul className="list-disc pl-5 text-sm">{diag.diagnosis.next_actions.map((a, i) => <li key={i}>{a}</li>)}</ul></div>)}
              {diag.citations.length > 0 && <div className="flex flex-wrap gap-2 text-xs">{diag.citations.map((c) => (
                <button key={c.n} className="rounded border border-slate-200 px-2 py-1 hover:border-brand-500" onClick={() => setSource(c)}>[{c.n}] {c.doc_code} v{c.version}{c.page ? ` · p.${c.page}` : ""}</button>))}</div>}
              <p className="text-xs text-slate-500">Suggestions only — the scientist makes the final decision.</p>
            </div>
          )}
        </section>
      </div>
      <SourceDrawer citation={source} onClose={() => setSource(null)} />
    </div>
  );
}
