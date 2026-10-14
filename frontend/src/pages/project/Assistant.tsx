import { Fragment, useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, BookmarkPlus, BrainCircuit, ExternalLink, FileText, FlaskConical, MessageSquare, Pencil, Plus, Send, Sigma, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api, streamNdjson, type Schemas } from "@/api/client";
import type { Conflict, ExternalOption, ProjectChatEvent, ProjectCitation, WebSource } from "@/api/types";
import { Banner, Modal, Spinner, StatusBadge, errMsg, fmtDate } from "@/components/ui";
import { CitationMarker } from "@/components/CitationChip";
import type { TabProps } from "@/pages/ProjectDetail";

interface Msg {
  id: number; question: string; text: string; citations: ProjectCitation[]; chatId?: string; verdict?: "sufficient" | "partial" | "insufficient";
  conflicts: Conflict[]; stage?: string; streaming: boolean; error?: string; claims?: { text: string; kind: string }[];
  ask?: { options: ExternalOption[]; message: string; state: "ask" | "loading" | "denied" | "done" };
  external?: { answer: string; sources: WebSource[]; grounded: boolean }; externalError?: string;
}
type Row = Schemas["HistoryOut"];
let counter = 0;

function rowsToMsgs(rows: Row[]): Msg[] {
  const out: Msg[] = [];
  for (const r of rows) {
    const meta = (r.meta ?? {}) as { verdict?: Msg["verdict"]; conflicts?: Conflict[]; awaiting_external?: boolean; external_decision?: string; origin_chat_id?: string; claims?: { text: string; kind: string }[]; error?: boolean };
    if (r.source_type === "external") {
      const prev = out.find((m) => m.chatId === meta.origin_chat_id);
      if (prev) { prev.external = { answer: r.answer ?? "", sources: (r.sources as WebSource[]) ?? [], grounded: false }; if (prev.ask) prev.ask.state = "done"; }
      continue;
    }
    const m: Msg = { id: ++counter, question: r.question, text: r.answer ?? "", citations: (r.sources as ProjectCitation[]) ?? [], chatId: r.id, verdict: meta.verdict,
      conflicts: meta.conflicts ?? [], streaming: false, claims: meta.claims, error: meta.error ? "The AI was unavailable for this question." : undefined };
    if (meta.awaiting_external) m.ask = { state: "ask", message: "Would you like me to search external sources for additional information?", options: [
      { value: "allow_once", label: "Allow external search (this question only)" }, { value: "allow_conversation", label: "Allow external search for this conversation" },
      { value: "deny", label: "Continue using project information only" }] };
    else if (meta.external_decision === "denied") m.ask = { state: "denied", message: "", options: [] };
    out.push(m);
  }
  return out;
}

function inline(s: string, citations: ProjectCitation[], onOpen: (c: ProjectCitation) => void, activeN?: number | null) {
  return s.split(/(\*\*[^*]+\*\*|_[^_]+_|\[\d{1,2}\])/g).map((p, i) => {
    if (/^\*\*[^*]+\*\*$/.test(p)) return <b key={i}>{p.slice(2, -2)}</b>;
    if (/^_[^_]+_$/.test(p)) return <i key={i}>{p.slice(1, -1)}</i>;
    const m = /^\[(\d{1,2})\]$/.exec(p);
    if (m) {
      const c = citations.find((x) => x.n === Number(m[1]));
      return c ? <CitationMarker key={i} n={c.n} active={activeN === c.n} title={c.label} onClick={() => onOpen(c)} preview={<><div className="text-[13px] font-medium text-slate-900">{c.label}</div><div className="mt-0.5 text-slate-600">{c.source_type === "experiment" ? `record v${c.source_version}` : c.page ? `page ${c.page}` : c.source_type}</div><div className="mt-1.5 line-clamp-3 leading-relaxed">{c.snippet}</div></>} /> : <span key={i}>{p}</span>;
    }
    return <Fragment key={i}>{p}</Fragment>;
  });
}

/** Minimal renderer for the server-built answer (bold headings, bullet lists, [n] citation chips). */
export function Answer({ text, citations, onOpen, activeN }: { text: string; citations: ProjectCitation[]; onOpen: (c: ProjectCitation) => void; activeN?: number | null }) {
  return (
    <div className="space-y-3 text-[15px] leading-[1.65] text-slate-900">
      {text.split(/\n{2,}/).map((block, i) => {
        const lines = block.split("\n");
        const bullets = lines.filter((l) => l.startsWith("- "));
        const head = lines.filter((l) => !l.startsWith("- "));
        return (
          <div key={i}>
            {head.map((l, j) => <div key={j} className={l.startsWith("**") ? "font-semibold text-slate-800" : ""}>{inline(l, citations, onOpen, activeN)}</div>)}
            {bullets.length > 0 && <ul className="list-disc space-y-1 pl-5">{bullets.map((l, j) => <li key={j}>{inline(l.slice(2), citations, onOpen, activeN)}</li>)}</ul>}
          </div>);
      })}
    </div>
  );
}

const ICON = { document: FileText, experiment: FlaskConical, analysis: Sigma } as const;

export default function Assistant({ project: p, canWrite }: TabProps) {
  const qc = useQueryClient();
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [cid, setCid] = useState<string | null>(null);
  const [source, setSource] = useState<ProjectCitation | null>(null);
  const [showMem, setShowMem] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);
  const lastKey = `sla_project_conv_${p.id}`;
  const recent = useQuery({ queryKey: ["conversations", p.id], queryFn: () => api<Schemas["ConversationOut"][]>(`/chat/conversations?project_id=${p.id}`) });

  async function open(id: string) {
    try { const rows = await api<Row[]>(`/chat/conversations/${id}`); setMsgs(rowsToMsgs(rows)); setCid(id); try { localStorage.setItem(lastKey, id); } catch { /* ignore */ } }
    catch { setMsgs([]); setCid(null); try { localStorage.removeItem(lastKey); } catch { /* ignore */ } }
  }
  const fresh = () => { setMsgs([]); setCid(null); try { localStorage.removeItem(lastKey); } catch { /* ignore */ } };
  useEffect(() => { let id: string | null = null; try { id = localStorage.getItem(lastKey); } catch { /* ignore */ } if (id) void open(id); }, [p.id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs]);

  const patch = (id: number, v: Partial<Msg> | ((m: Msg) => Partial<Msg>)) => setMsgs((all) => all.map((m) => (m.id === id ? { ...m, ...(typeof v === "function" ? v(m) : v) } : m)));

  async function ask(question: string) {
    const q = question.trim();
    if (!q || busy) return;
    const id = ++counter;
    setMsgs((all) => [...all, { id, question: q, text: "", citations: [], conflicts: [], streaming: true, stage: "Searching this project…" }]);
    setInput(""); setBusy(true);
    try {
      await streamNdjson<ProjectChatEvent>(`/projects/${p.id}/chat/stream`, { question: q, conversation_id: cid }, (e) => {
        if (e.type === "meta") { patch(id, { chatId: e.chat_id }); setCid(e.conversation_id); try { localStorage.setItem(lastKey, e.conversation_id); } catch { /* ignore */ } }
        else if (e.type === "status") patch(id, { stage: e.stage === "retrieving" ? "Searching this project…" : "Checking the evidence…" });
        else if (e.type === "token") patch(id, (m) => ({ text: m.text + e.text }));
        else if (e.type === "citations") patch(id, { citations: e.citations });
        else if (e.type === "answer") patch(id, { verdict: e.verdict, conflicts: e.conflicts });
        else if (e.type === "need_external") patch(id, { ask: { options: e.options, message: e.message, state: "ask" }, chatId: e.chat_id });
        else if (e.type === "external") patch(id, { external: { answer: e.answer, sources: e.sources, grounded: e.grounded }, ask: { options: [], message: "", state: "done" } });
        else if (e.type === "external_error") patch(id, { externalError: e.message });
        else if (e.type === "error") patch(id, { error: e.message });
      });
    } catch (e) { patch(id, { error: errMsg(e) }); }
    finally { patch(id, { streaming: false, stage: undefined }); setBusy(false); void qc.invalidateQueries({ queryKey: ["conversations", p.id] }); }
  }

  async function decide(m: Msg, decision: ExternalOption["value"]) {
    if (!m.chatId) return;
    patch(m.id, (x) => ({ ask: x.ask && { ...x.ask, state: "loading" } }));
    try {
      const r = await api<{ decision: string; message?: string; external?: { answer: string; sources: WebSource[]; grounded: boolean } }>(`/projects/${p.id}/chat/${m.chatId}/external`, { method: "POST", json: { decision } });
      if (decision === "deny") patch(m.id, (x) => ({ ask: x.ask && { ...x.ask, state: "denied" } }));
      else patch(m.id, (x) => ({ external: r.external, ask: x.ask && { ...x.ask, state: "done" } }));
    } catch (e) { toast.error(errMsg(e)); patch(m.id, (x) => ({ ask: x.ask && { ...x.ask, state: "ask" } })); }
  }

  const rename = useMutation({
    mutationFn: (v: { id: string; title: string }) => api(`/chat/conversations/${v.id}`, { method: "PATCH", json: { title: v.title } }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["conversations", p.id] }), onError: (e) => toast.error(errMsg(e)),
  });
  const del = useMutation({
    mutationFn: (id: string) => api(`/chat/conversations/${id}`, { method: "DELETE" }),
    onSuccess: (_, id) => { toast.success("Conversation deleted"); if (id === cid) fresh(); void qc.invalidateQueries({ queryKey: ["conversations", p.id] }); }, onError: (e) => toast.error(errMsg(e)),
  });
  async function remember(m: Msg) {
    const base = (m.claims ?? []).filter((c) => c.kind === "observed" || c.kind === "interpretation").map((c) => c.text).join(" ") || m.text.replace(/\[\d+\]/g, "").slice(0, 300);
    const content = window.prompt("Save to project memory (shared with project members; marked AI-suggested and unverified):", base.slice(0, 600));
    if (!content || content.trim().length < 2) return;
    const refs = m.citations.filter((c) => c.source_type !== "analysis").map((c) => ({ type: c.source_type, id: c.source_id, version: c.source_version }));
    try { await api(`/projects/${p.id}/memory`, { method: "POST", json: { content, kind: "finding", origin: "ai_suggested", source_refs: refs } }); toast.success("Saved to project memory"); void qc.invalidateQueries({ queryKey: ["pmemory", p.id] }); }
    catch (e) { toast.error(errMsg(e)); }
  }

  const EXAMPLES = ["What does our documentation say about …?", "Is the value in EXP-001 unusual compared with earlier experiments?", "Which earlier experiments used the same reagents?"];
  return (
    <div className="flex h-[calc(100vh-14rem)] min-h-[28rem] gap-5">
      <aside className="hidden w-64 shrink-0 flex-col md:flex" data-testid="project-recent-chats">
        <button className="btn-primary mb-3 w-full" onClick={fresh}><Plus size={16} />New conversation</button>
        <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Recent conversations</div>
        <div className="flex-1 space-y-1 overflow-y-auto pr-1">
          {recent.isLoading && <Spinner />}
          {recent.isError && <Banner tone="red">{errMsg(recent.error)}</Banner>}
          {recent.data?.length === 0 && <div className="rounded-md border border-dashed border-slate-300 p-3 text-sm text-slate-500">Conversations about this project are saved here and restored when you come back.</div>}
          {recent.data?.map((c) => (
            <div key={c.id} className={`group rounded-md px-3 py-2 text-sm ${c.id === cid ? "bg-brand-50 ring-1 ring-brand-500" : "hover:bg-slate-100"}`}>
              <button className="w-full text-left" onClick={() => open(c.id)} title={c.title}>
                <div className="flex items-start gap-2"><MessageSquare size={14} className="mt-1 shrink-0 text-slate-400" /><span className="line-clamp-2">{c.title}</span></div>
                <div className="ml-6 text-xs text-slate-500">{fmtDate(c.last_at)} · {c.turns} turn(s)</div></button>
              <div className="ml-6 mt-1 hidden gap-2 text-xs group-hover:flex group-focus-within:flex">
                <button aria-label={`Rename ${c.title}`} className="inline-flex items-center gap-1 text-slate-600 hover:text-slate-900" onClick={() => { const t = window.prompt("Rename conversation", c.title); if (t && t.trim()) rename.mutate({ id: c.id, title: t.trim() }); }}><Pencil size={12} />Rename</button>
                <button aria-label={`Delete ${c.title}`} className="inline-flex items-center gap-1 text-red-700" onClick={() => { if (window.confirm("Delete this conversation and its saved summary?")) del.mutate(c.id); }}><Trash2 size={12} />Delete</button>
              </div>
            </div>))}
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <p className="text-sm text-slate-600">Answers use <b>only this project&apos;s</b> documents and experiment records, and every claim is checked against the passages it cites.</p>
          {cid && <button className="btn-secondary px-3 py-1 text-xs" onClick={() => setShowMem(true)}><BrainCircuit size={14} />Conversation memory</button>}
        </div>
        <div className="flex-1 space-y-6 overflow-y-auto pr-1" data-testid="project-chat-log">
          {msgs.length === 0 && (
            <div className="card p-6 text-center text-slate-500">
              Ask about this project&apos;s protocols, measurements and history.
              <ul className="mt-3 space-y-1 text-sm">{EXAMPLES.map((e) => <li key={e}><button className="text-brand-700 underline" onClick={() => setInput(e)}>{e}</button></li>)}</ul>
              <div className="mt-3 text-xs">Tip: say “Remember that …” to save a preference or project note.</div>
            </div>)}
          {msgs.map((m) => (
            <div key={m.id} className="space-y-3">
              <div className="ml-auto w-fit max-w-[85%] rounded-lg bg-brand-600 px-4 py-2 text-white" data-testid="user-msg">{m.question}</div>
              <div className="card max-w-[94%] p-4" data-testid="assistant-msg">
                {m.streaming && !m.text && <Spinner label={m.stage ?? "Working…"} />}
                {m.text && <Answer text={m.text} citations={m.citations} onOpen={setSource} />}
                {m.error && <Banner tone="red">{m.error}</Banner>}
                {m.verdict && !m.streaming && (
                  <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                    <StatusBadge status={m.verdict} /> evidence check
                    {m.conflicts.length > 0 && <span className="badge bg-orange-100 text-orange-800">conflicting sources</span>}
                  </div>)}
                {m.citations.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-2 border-t border-slate-100 pt-3 text-xs text-slate-600">
                    {m.citations.map((c) => { const Icon = ICON[c.source_type]; return (
                      <button key={c.n} className="inline-flex items-center gap-1 rounded border border-slate-200 px-2 py-1 hover:border-brand-500" onClick={() => setSource(c)}>
                        <Icon size={12} />[{c.n}] {c.label}{c.source_type === "experiment" ? ` v${c.source_version}` : ""}{c.page ? ` · p.${c.page}` : ""}{c.section && c.source_type === "document" ? ` · ${c.section.slice(0, 30)}` : ""}</button>); })}
                  </div>)}
                {!m.streaming && m.text && m.citations.length > 0 && canWrite && (
                  <button className="mt-2 inline-flex items-center gap-1 text-xs text-slate-500 hover:text-slate-900" onClick={() => remember(m)}><BookmarkPlus size={14} />Save to project memory…</button>)}

                {m.ask?.state === "ask" && (
                  <div className="mt-3 space-y-3 rounded-md border border-amber-300 bg-amber-50 p-3" data-testid="external-consent">
                    <p className="flex items-start gap-2 text-sm font-medium"><AlertTriangle size={16} className="mt-0.5 shrink-0 text-amber-700" />{m.ask.message}</p>
                    <p className="text-xs text-slate-600">Nothing is sent outside until you choose. Only your question text is sent (never project documents or records), and the result is shown separately as unverified.</p>
                    <div className="flex flex-wrap gap-2">{m.ask.options.map((o) => <button key={o.value} className={o.value === "deny" ? "btn-primary" : "btn-secondary"} onClick={() => decide(m, o.value)}>{o.label}</button>)}</div>
                  </div>)}
                {m.ask?.state === "loading" && <div className="mt-3"><Spinner label="Searching external sources…" /></div>}
                {m.ask?.state === "denied" && <div className="mt-3 text-sm text-slate-600">Staying with project information only. No external search was made.</div>}
                {m.externalError && <div className="mt-3"><Banner tone="red">{m.externalError}</Banner></div>}
              </div>
              {m.external && (
                <div className="rounded-xl border border-external-border bg-external-surface" data-testid="external-answer">
                  <div className="flex items-center gap-2 border-b border-external-border/40 px-4 py-2.5 text-sm font-semibold text-amber-800"><AlertTriangle size={18} />External information — not from this project&apos;s records</div>
                  <div className="space-y-3 p-4"><div className="whitespace-pre-wrap text-sm">{m.external.answer}</div>
                    {m.external.sources.length > 0 ? <ul className="space-y-1 text-sm">{m.external.sources.map((s) => <li key={s.uri}><a className="inline-flex items-center gap-1 text-brand-700 underline" href={s.uri} target="_blank" rel="noreferrer noopener"><ExternalLink size={14} />{s.title} <span className="text-slate-500">({s.domain})</span></a></li>)}</ul>
                      : <div className="text-xs text-amber-900">No web sources were available, so this is unverified general knowledge.</div>}
                    <p className="border-t border-amber-300 pt-2 text-xs font-medium text-amber-950">This was not merged into your project findings and was not added to the project&apos;s search index. Verify it before relying on it.</p></div>
                </div>)}
            </div>))}
          <div ref={bottom} />
        </div>
        <form className="mt-3 flex gap-2" onSubmit={(e) => { e.preventDefault(); void ask(input); }}>
          <input aria-label="Ask the project assistant" className="input flex-1 py-3 text-base" maxLength={2000} placeholder="Ask about this project…" value={input} onChange={(e) => setInput(e.target.value)} disabled={busy} />
          <button className="btn-primary px-5" disabled={busy || input.trim().length < 2}><Send size={18} />Ask</button>
        </form>
      </div>
      {source && <SourceModal projectId={p.id} c={source} onClose={() => setSource(null)} />}
      {showMem && cid && <ConvMemory id={cid} onClose={() => setShowMem(false)} />}
    </div>
  );
}

export function SourceModal({ projectId, c, onClose }: { projectId: string; c: ProjectCitation; onClose: () => void }) {
  const ver = useQuery({ enabled: c.source_type === "experiment", queryKey: ["cited-version", c.source_id, c.source_version],
    queryFn: () => api<Schemas["VersionDetail"]>(`/projects/${projectId}/experiments/${c.source_id}/versions/${c.source_version}`) });
  const snap = ver.data?.snapshot as { [k: string]: unknown } | undefined;
  return (
    <Modal title={`[${c.n}] ${c.label}`} onClose={onClose} wide>
      <div className="space-y-3 text-sm">
        <div className="flex flex-wrap gap-2 text-slate-600">
          <span className="badge bg-slate-100 text-slate-700">{c.source_type === "analysis" ? "computed from experiment records" : c.source_type === "experiment" ? `experiment record, version ${c.source_version}` : `document${c.source_version > 1 ? ` v${c.source_version}` : ""}`}</span>
          {c.page && <span>page {c.page}</span>}{c.section && <span>section: {c.section}</span>}</div>
        <div><div className="mb-1 text-xs font-semibold uppercase text-slate-500">Passage the answer relied on</div><blockquote className="whitespace-pre-wrap rounded-md border-l-4 border-brand-500 bg-slate-50 p-3">{c.snippet}</blockquote></div>
        {c.source_type === "experiment" && (ver.isLoading ? <Spinner /> : snap && (
          <div><div className="mb-1 text-xs font-semibold uppercase text-slate-500">Record exactly as it was at version {c.source_version}</div>
            <dl className="grid gap-x-4 gap-y-1 rounded-md bg-slate-50 p-3 md:grid-cols-2">{["title", "outcome", "objective", "observations", "results", "conclusions"].map((k) => snap[k] ? <div key={k}><dt className="text-xs uppercase text-slate-500">{k}</dt><dd className="whitespace-pre-wrap">{String(snap[k])}</dd></div> : null)}
              {((snap.parameters as { name: string; value?: number; text_value?: string; unit?: string }[]) ?? []).length > 0 && <div className="md:col-span-2"><dt className="text-xs uppercase text-slate-500">parameters</dt><dd>{(snap.parameters as { name: string; value?: number; text_value?: string; unit?: string }[]).map((x) => `${x.name} = ${x.value ?? x.text_value}${x.unit ? ` ${x.unit}` : ""}`).join("; ")}</dd></div>}
            </dl></div>))}
        {c.source_type === "analysis" && <p className="text-slate-600">This passage was calculated from the recorded values of the experiment and its predecessors; open the experiment&apos;s “Troubleshoot” tab to see every number and which records they came from.</p>}
      </div>
    </Modal>
  );
}

function ConvMemory({ id, onClose }: { id: string; onClose: () => void }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["conv-memory", id], queryFn: () => api<Schemas["ConversationMemoryOut"]>(`/chat/conversations/${id}/memory`) });
  const clear = useMutation({ mutationFn: () => api(`/chat/conversations/${id}/memory`, { method: "DELETE" }), onSuccess: () => { toast.success("Summary and permissions cleared"); void qc.invalidateQueries({ queryKey: ["conv-memory", id] }); }, onError: (e) => toast.error(errMsg(e)) });
  return (
    <Modal title="Conversation memory" onClose={onClose}>
      {q.isLoading && <Spinner />}
      {q.data && (
        <div className="space-y-3 text-sm">
          <Banner tone="blue">{q.data.note}</Banner>
          <div><div className="label">Summary of earlier turns{q.data.summary_stale ? " (stale - rebuilt on your next question)" : ""}</div>
            <div className="whitespace-pre-wrap rounded-md bg-slate-50 p-3">{q.data.summary ?? "Nothing summarised yet. Recent turns are used directly; older turns are summarised once the conversation gets long."}</div></div>
          <div>External search for this conversation: <b>{q.data.external_allowed ? "allowed" : "ask each time"}</b></div>
          <div className="flex justify-end gap-2"><button className="btn-secondary" onClick={onClose}>Close</button><button className="btn-secondary text-red-700" onClick={() => clear.mutate()}>Clear summary & permission</button></div>
        </div>)}
    </Modal>
  );
}
