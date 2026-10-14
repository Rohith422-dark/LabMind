import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Boxes, FileText, FolderKanban, History, Lightbulb, MessageSquare, PanelRightOpen, Pencil, Plus, Send, ShieldAlert, ThumbsDown, ThumbsUp, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api, streamNdjson, type Schemas } from "@/api/client";
import type { ChatEvent, Citation, ExternalResult, ProjectCitation, ExternalOption, WebSource } from "@/api/types";
import { Answer, SourceModal } from "@/pages/project/Assistant";
import { AnswerText } from "@/components/CitationChip";
import { SourceDrawer } from "@/components/SourceDrawer";
import { ExternalWarningCard } from "@/components/ExternalWarningCard";
import { StatusBadge, Spinner, Banner, Skeleton, errMsg } from "@/components/ui";
import { RetrievedContext, type RetrievedItem } from "@/components/RetrievedContext";
import { StockBar } from "@/components/StockBar";

interface Msg {
  id: number; question: string; text: string; citations: Citation[]; safety?: string; chatId?: string;
  lots?: Schemas["LotOut"][]; gapId?: string; consent?: "ask" | "declined" | "loading" | "done";
  external?: ExternalResult; sopRequested?: boolean; error?: string; streaming: boolean; feedback?: "up" | "down";
  general?: boolean; register?: boolean;                                                                   // answered from the model's own knowledge
  needProject?: { projects: { id: string; name: string; role: string }[]; state: "ask" | "declined" | "done" };
  projectId?: string; pCitations?: ProjectCitation[]; verdict?: string;                // answered from a project the user approved
  pAsk?: { options: ExternalOption[]; state: "ask" | "loading" | "denied" | "done" }; pExternal?: { answer: string; sources: WebSource[] };
}

let counter = 0;
const LAST_KEY = "sla_last_conversation";
const lastGet = () => { try { return localStorage.getItem(LAST_KEY); } catch { return null; } };
const lastSet = (id: string | null) => { try { id ? localStorage.setItem(LAST_KEY, id) : localStorage.removeItem(LAST_KEY); } catch { /* storage unavailable */ } };

type Row = Schemas["HistoryOut"];

/** Rebuild UI messages from saved rows (answers, citations, safety notes, tables, consent/external state). */
function rowsToMsgs(rows: Row[]): Msg[] {
  const out: Msg[] = [];
  for (const r of rows) {
    const meta = (r.meta ?? {}) as { safety?: string; lots?: Schemas["LotOut"][]; gap_id?: string; grounded?: boolean; general?: boolean; register?: boolean; awaiting_project?: boolean;
      projects?: { id: string; name: string; role: string }[]; kind?: string; verdict?: string; awaiting_external?: boolean; origin_chat_id?: string; external_decision?: string };
    if (r.source_type === "external" && meta.origin_chat_id) {
      const prev = out.find((m) => m.chatId === meta.origin_chat_id);
      if (prev) { prev.pExternal = { answer: r.answer ?? "", sources: (r.sources as WebSource[]) ?? [] }; if (prev.pAsk) prev.pAsk.state = "done"; }
      continue;
    }
    if (meta.kind === "project") {
      out.push({ id: ++counter, question: r.question, text: r.answer ?? "", citations: [], pCitations: (r.sources as ProjectCitation[]) ?? [], chatId: r.id, projectId: r.project_id ?? undefined,
        verdict: meta.verdict, streaming: false, pAsk: meta.awaiting_external ? { state: "ask", options: [
          { value: "allow_once", label: "Allow external search (this question only)" }, { value: "allow_conversation", label: "Allow external search for this conversation" },
          { value: "deny", label: "Continue using project information only" }] } : meta.external_decision === "denied" ? { state: "denied", options: [] } : undefined });
      continue;
    }
    if (r.source_type === "external") {
      const prev = [...out].reverse().find((m) => m.gapId === meta.gap_id);
      const sources = (r.sources as { title: string; uri: string; domain: string }[]) ?? [];
      const external: ExternalResult = { chat_id: r.id, answer: r.answer ?? "", sources, grounded: !!meta.grounded, gap_id: meta.gap_id ?? "" };
      if (prev) { prev.external = external; prev.consent = "done"; }
      continue;
    }
    out.push({
      id: ++counter, question: r.question, text: r.answer ?? "", citations: (r.sources as Citation[]) ?? [], chatId: r.id,
      safety: meta.safety, lots: meta.lots, gapId: meta.gap_id, feedback: (r.feedback as "up" | "down" | null) ?? undefined,
      general: meta.general, register: meta.register, needProject: meta.awaiting_project && meta.projects ? { projects: meta.projects, state: "ask" } : undefined,
      consent: !r.answer && meta.gap_id ? "ask" : undefined, error: !r.answer && !meta.gap_id ? "No answer was saved for this question." : undefined,
      streaming: false,
    });
  }
  return out;
}

export default function ChatAssistant() {
  const [params, setParams] = useSearchParams();
  const qc = useQueryClient();
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState(params.get("q") ?? "");
  const [busy, setBusy] = useState(false);
  const [source, setSource] = useState<Citation | null>(null);
  const [pSource, setPSource] = useState<{ c: ProjectCitation; projectId: string } | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [selected, setSelected] = useState<{ msgId: number; n: number } | null>(null);
  const [panelOpen, setPanelOpen] = useState(true);
  const [drawer, setDrawer] = useState(false);
  const [panelW, setPanelW] = useState(() => { try { return Number(localStorage.getItem("sla_panel_w")) || 380; } catch { return 380; } });
  const bottom = useRef<HTMLDivElement>(null);
  const recent = useQuery({ queryKey: ["conversations"], queryFn: () => api<Schemas["ConversationOut"][]>("/chat/conversations?scope=global") });

  async function openConversation(id: string) {
    try {
      const rows = await api<Row[]>(`/chat/conversations/${id}`);
      setMsgs(rowsToMsgs(rows)); setConversationId(id); lastSet(id);
    } catch { lastSet(null); setMsgs([]); setConversationId(null); }
  }
  async function renameChat(c: Schemas["ConversationOut"]) {
    const t = window.prompt("Rename conversation", c.title);
    if (!t || !t.trim()) return;
    try { await api(`/chat/conversations/${c.id}`, { method: "PATCH", json: { title: t.trim() } }); void qc.invalidateQueries({ queryKey: ["conversations"] }); } catch (e) { toast.error(errMsg(e)); }
  }
  async function deleteChat(c: Schemas["ConversationOut"]) {
    if (!window.confirm("Delete this conversation permanently?")) return;
    try { await api(`/chat/conversations/${c.id}`, { method: "DELETE" }); if (c.id === conversationId) newChat(); void qc.invalidateQueries({ queryKey: ["conversations"] }); toast.success("Conversation deleted"); } catch (e) { toast.error(errMsg(e)); }
  }
  function newChat() { setMsgs([]); setConversationId(null); lastSet(null); setInput(""); }

  useEffect(() => { const q = params.get("q"); if (q) { setInput(q); setParams({}, { replace: true }); } }, [params, setParams]);
  // persistent memory: come back to where you left off (unless a guide prompt is prefilling a new question)
  useEffect(() => { const id = lastGet(); if (id && !params.get("q")) void openConversation(id); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs]);

  const patch = (id: number, p: Partial<Msg> | ((m: Msg) => Partial<Msg>)) =>
    setMsgs((all) => all.map((m) => (m.id === id ? { ...m, ...(typeof p === "function" ? p(m) : p) } : m)));

  async function ask(question: string, projectCheck = true) {
    const q = question.trim();
    if (!q || busy) return;
    const id = ++counter;
    const history = msgs.filter((m) => m.text && !m.error).slice(-3).flatMap((m) => [
      { role: "user" as const, content: m.question }, { role: "assistant" as const, content: m.text.slice(0, 800) }]);
    setMsgs((all) => [...all, { id, question: q, text: "", citations: [], streaming: true }]);
    setInput(""); setBusy(true);
    try {
      await streamNdjson<ChatEvent>("/chat/stream", { question: q, history, conversation_id: conversationId, mode: "assistant", project_check: projectCheck }, (e) => {
        if (e.type === "meta") { patch(id, { chatId: e.chat_id }); setConversationId(e.conversation_id); lastSet(e.conversation_id); }
        else if (e.type === "token") patch(id, (m) => ({ text: m.text + e.text }));
        else if (e.type === "citations") patch(id, { citations: e.citations });
        else if (e.type === "safety") patch(id, { safety: e.note });
        else if (e.type === "inventory") patch(id, { lots: e.lots });
        else if (e.type === "no_match") patch(id, { gapId: e.gap_id, consent: "ask" });
        else if ((e as { type: string }).type === "general") patch(id, { general: true });
        else if ((e as { type: string }).type === "register") patch(id, { register: true });
        else if ((e as { type: string }).type === "need_project") patch(id, { needProject: { projects: (e as unknown as { projects: { id: string; name: string; role: string }[] }).projects, state: "ask" } });
        else if (e.type === "error") patch(id, { error: e.message });
      });
    } catch (e) {
      patch(id, { error: errMsg(e) });
    } finally {
      patch(id, { streaming: false }); setBusy(false);
      void qc.invalidateQueries({ queryKey: ["conversations"] });
    }
  }

  async function answerFromProject(m: Msg, projectId: string) {
    if (busy) return;
    patch(m.id, (x) => ({ needProject: x.needProject && { ...x.needProject, state: "done" } }));
    const id = ++counter;
    setMsgs((all) => [...all, { id, question: m.question, text: "", citations: [], streaming: true, projectId, pCitations: [] }]);
    setBusy(true);
    try {
      await streamNdjson<{ type: string; [k: string]: unknown }>("/chat/assistant/project-answer", { question: m.question, project_id: projectId, conversation_id: conversationId }, (e) => {
        if (e.type === "meta") { patch(id, { chatId: e.chat_id as string }); setConversationId(e.conversation_id as string); lastSet(e.conversation_id as string); }
        else if (e.type === "token") patch(id, (x) => ({ text: x.text + (e.text as string) }));
        else if (e.type === "citations") patch(id, { pCitations: e.citations as ProjectCitation[] });
        else if (e.type === "answer") patch(id, { verdict: e.verdict as string });
        else if (e.type === "need_external") patch(id, { chatId: e.chat_id as string, pAsk: { options: e.options as ExternalOption[], state: "ask" } });
        else if (e.type === "external") patch(id, { pExternal: { answer: e.answer as string, sources: e.sources as WebSource[] }, pAsk: { options: [], state: "done" } });
        else if (e.type === "error") patch(id, { error: e.message as string });
      });
    } catch (e) { patch(id, { error: errMsg(e) }); }
    finally { patch(id, { streaming: false }); setBusy(false); void qc.invalidateQueries({ queryKey: ["conversations"] }); }
  }

  async function declineProject(m: Msg) {
    patch(m.id, (x) => ({ needProject: x.needProject && { ...x.needProject, state: "declined" } }));
    await ask(m.question, false);
  }

  async function projectConsent(m: Msg, decision: ExternalOption["value"]) {
    if (!m.chatId || !m.projectId) return;
    patch(m.id, (x) => ({ pAsk: x.pAsk && { ...x.pAsk, state: "loading" } }));
    try {
      const r = await api<{ external?: { answer: string; sources: WebSource[] } }>(`/projects/${m.projectId}/chat/${m.chatId}/external`, { method: "POST", json: { decision } });
      if (decision === "deny") patch(m.id, (x) => ({ pAsk: x.pAsk && { ...x.pAsk, state: "denied" } }));
      else patch(m.id, (x) => ({ pExternal: r.external, pAsk: x.pAsk && { ...x.pAsk, state: "done" } }));
    } catch (e) { toast.error(errMsg(e)); patch(m.id, (x) => ({ pAsk: x.pAsk && { ...x.pAsk, state: "ask" } })); }
  }

  async function goExternal(m: Msg) {
    patch(m.id, { consent: "loading" });
    try {
      const res = await api<ExternalResult>("/chat/external", { method: "POST", json: { gap_id: m.gapId, conversation_id: conversationId } });
      patch(m.id, { external: res, consent: "done" });
    } catch (e) { toast.error(errMsg(e)); patch(m.id, { consent: "ask" }); }
  }

  async function requestSop(m: Msg) {
    try { await api(`/gaps/${m.gapId}/request-sop`, { method: "PATCH" }); patch(m.id, { sopRequested: true }); toast.success("Official SOP requested. A Senior Analyst has been notified."); }
    catch (e) { toast.error(errMsg(e)); }
  }

  async function feedback(m: Msg, f: "up" | "down") {
    const id = m.external?.chat_id ?? m.chatId; if (!id) return;
    try { await api(`/chat/${id}/feedback`, { method: "PATCH", json: { feedback: f } }); patch(m.id, { feedback: f }); toast.success("Thanks for the feedback"); }
    catch (e) { toast.error(errMsg(e)); }
  }

  const ago = (iso: string) => {
    const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
    return mins < 1 ? "just now" : mins < 60 ? `${mins} min ago` : mins < 1440 ? `${Math.round(mins / 60)} h ago` : new Date(iso).toLocaleDateString();
  };

  // ---- retrieved-context panel: one selection shared by the inline markers and the cards
  const itemsOf = (m: Msg): RetrievedItem[] => m.projectId
    ? (m.pCitations ?? []).map((c) => ({ key: `${m.id}:${c.n}`, msgId: m.id, n: c.n, kind: c.source_type, title: c.label, version: c.source_type === "analysis" ? null : c.source_version,
      page: c.page, section: c.section, snippet: c.snippet, score: c.score, raw: c }))
    : m.citations.map((c) => ({ key: `${m.id}:${c.n}`, msgId: m.id, n: c.n, kind: "document" as const, title: c.title, code: c.doc_code, version: c.version, page: c.page, section: c.section,
      snippet: c.snippet, score: c.score, raw: c }));
  const withItems = msgs.filter((m) => itemsOf(m).length > 0);
  const panelMsg = msgs.find((m) => m.id === selected?.msgId) ?? withItems[withItems.length - 1];
  const answerItems = panelMsg ? itemsOf(panelMsg) : [];
  const conversationItems = withItems.flatMap(itemsOf);
  const selectedKey = selected ? `${selected.msgId}:${selected.n}` : null;
  const select = (msgId: number, n: number) => { setSelected({ msgId, n }); };
  const openItem = (it: RetrievedItem) => {
    const m = msgs.find((x) => x.id === it.msgId);
    if (it.kind === "document" && !m?.projectId) setSource(it.raw as Citation);
    else if (m?.projectId) setPSource({ c: it.raw as ProjectCitation, projectId: m.projectId });
  };
  const startResize = (e: React.PointerEvent) => {
    e.preventDefault();
    const startX = e.clientX, startW = panelW;
    const move = (ev: PointerEvent) => setPanelW(Math.max(300, Math.min(560, startW + (startX - ev.clientX))));
    const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
    window.addEventListener("pointermove", move); window.addEventListener("pointerup", up);
  };
  useEffect(() => { try { localStorage.setItem("sla_panel_w", String(panelW)); } catch { /* ignore */ } }, [panelW]);

  const panel = (onCollapse: () => void) => (
    <RetrievedContext answer={answerItems} conversation={conversationItems} selectedKey={selectedKey} busy={busy}
      onSelect={(it) => select(it.msgId, it.n)} onOpen={openItem} onCollapse={onCollapse} />
  );

  return (
    <div className="flex h-[calc(100vh-10.5rem)] min-h-[30rem] gap-4">
      <aside className="hidden w-60 shrink-0 flex-col xl:flex" data-testid="recent-chats">
        <button className="btn-primary mb-3 w-full" onClick={newChat}><Plus size={16} />New chat</button>
        <div className="mb-2 flex items-center gap-1.5 px-1 text-[11px] font-medium uppercase tracking-wide text-slate-500"><History size={13} />Recent chats</div>
        <div className="flex-1 space-y-0.5 overflow-y-auto pr-1">
          {recent.isLoading && <div className="space-y-2">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-12" />)}</div>}
          {recent.data?.length === 0 && <div className="rounded-lg border border-dashed border-slate-300 p-3 text-sm text-slate-500">Your conversations are saved here, and the assistant remembers them.</div>}
          {recent.data?.map((c) => (
            <div key={c.id} className={`group rounded-lg px-3 py-2 text-sm transition-colors duration-150 ${c.id === conversationId ? "bg-brand-100" : "hover:bg-slate-100"}`}>
              <button className="w-full text-left" onClick={() => openConversation(c.id)} title={c.title}>
                <div className={`line-clamp-2 font-medium ${c.id === conversationId ? "text-brand-700" : "text-slate-800"}`}>{c.title}</div>
                <div className="mt-0.5 text-xs text-slate-500">{ago(c.last_at)} · {c.turns} {c.turns === 1 ? "question" : "questions"}</div>
              </button>
              <div className="mt-1 hidden gap-3 text-xs group-hover:flex group-focus-within:flex">
                <button aria-label={`Rename ${c.title}`} className="inline-flex items-center gap-1 text-slate-600 hover:text-slate-900" onClick={() => renameChat(c)}><Pencil size={12} />Rename</button>
                <button aria-label={`Delete ${c.title}`} className="inline-flex items-center gap-1 text-red-700" onClick={() => deleteChat(c)}><Trash2 size={12} />Delete</button>
              </div>
            </div>
          ))}
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="mb-3 flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-[26px] leading-tight text-slate-900">AI assistant</h1>
            <p className="mt-1 max-w-2xl text-sm text-slate-600">Answers from approved lab documents carry citations; general questions use the AI&apos;s own knowledge; your projects are only used after you give permission.</p>
          </div>
          <div className="flex items-center gap-2">
            <select className="input hidden h-10 w-44 py-1 text-sm lg:block xl:hidden" value={conversationId ?? ""} onChange={(e) => (e.target.value ? void openConversation(e.target.value) : newChat())} aria-label="Recent chats">
              <option value="">New chat</option>{recent.data?.map((c) => <option key={c.id} value={c.id}>{c.title.slice(0, 40)}</option>)}</select>
            <button className="btn-secondary px-3 lg:hidden" onClick={newChat} aria-label="New chat"><Plus size={16} /></button>
            {(!panelOpen || true) && <button className={`btn-secondary px-3 ${panelOpen ? "hidden" : "hidden lg:inline-flex"}`} onClick={() => setPanelOpen(true)}><PanelRightOpen size={16} />Sources ({answerItems.length})</button>}
            <button className="btn-secondary px-3 lg:hidden" onClick={() => setDrawer(true)}><PanelRightOpen size={16} />Sources ({answerItems.length})</button>
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto rounded-xl" data-testid="chat-log">
          <div className="mx-auto max-w-[760px] space-y-7 px-1 pb-4">
            {msgs.length === 0 && (
              <div className="card mt-6 p-8 text-center">
                <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-lg bg-brand-100 text-brand-600"><MessageSquare size={20} /></div>
                <div className="font-medium text-slate-900">How can I help?</div>
                <p className="mt-1 text-sm text-slate-600">Ask about an SOP or troubleshooting guide, check reagent stock, or ask anything general.</p>
              </div>
            )}
            {msgs.map((m) => (
              <div key={m.id} className="space-y-3">
                <div className="ml-auto w-fit max-w-[85%] rounded-xl bg-slate-100 px-4 py-2.5 text-[15px] text-slate-900" data-testid="user-msg">{m.question}</div>
                <div className="max-w-full" data-testid="assistant-msg">
                  {m.streaming && !m.text && <div className="space-y-2" aria-label="Searching"><Skeleton className="h-4 w-3/4" /><Skeleton className="h-4 w-1/2" /><span className="sr-only">Searching approved documents…</span></div>}
                  {m.register && !m.streaming && <div className="mb-2 flex items-start gap-2 rounded-lg border border-brand-200 bg-brand-50 px-3 py-2 text-xs text-slate-700"><Boxes size={14} className="mt-0.5 shrink-0 text-brand-600" />From the lab&apos;s inventory register (live data). Lines starting “General knowledge:” come from the AI, not the register.</div>}
                  {m.general && !m.streaming && <div className="mb-2 flex items-start gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600"><Lightbulb size={14} className="mt-0.5 shrink-0 text-amber-700" />General answer from the AI&apos;s own knowledge, not from approved lab documents or your project data. Verify anything safety-critical.</div>}
                  {m.text && m.projectId && <Answer text={m.text} citations={m.pCitations ?? []} onOpen={(c) => select(m.id, c.n)} activeN={selected?.msgId === m.id ? selected.n : null} />}
                  {m.text && !m.projectId && <AnswerText text={m.text} citations={m.citations} onOpen={(c) => select(m.id, c.n)} activeN={selected?.msgId === m.id ? selected.n : null} />}
                  {m.projectId && !m.streaming && m.verdict && <div className="mt-2 flex items-center gap-2 text-xs text-slate-600"><StatusBadge status={m.verdict} /> evidence check · answered from your project only</div>}
                  {itemsOf(m).length > 0 && !m.streaming && (
                    <button className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-brand-600 hover:text-brand-700" onClick={() => { setSelected({ msgId: m.id, n: itemsOf(m)[0].n }); setDrawer(true); setPanelOpen(true); }}>
                      <FileText size={13} />{itemsOf(m).length} source{itemsOf(m).length === 1 ? "" : "s"} used</button>)}
                  {m.needProject?.state === "ask" && (
                    <div className="mt-3 space-y-2 rounded-xl border border-blue-200 bg-blue-50 p-3.5" data-testid="project-permission">
                      <p className="flex items-center gap-2 text-sm font-medium text-slate-900"><FolderKanban size={16} className="text-blue-600" />May I look at your project data to answer this?</p>
                      <p className="text-xs text-slate-600">Nothing from your projects is read until you choose one. Only that project&apos;s documents and records are used.</p>
                      <div className="flex flex-wrap gap-2">{m.needProject.projects.map((p) => <button key={p.id} className="btn-primary" disabled={busy} onClick={() => answerFromProject(m, p.id)}>Use “{p.name}”</button>)}
                        <button className="btn-secondary" disabled={busy} onClick={() => declineProject(m)}>No - answer in general terms</button></div>
                    </div>)}
                  {m.needProject?.state === "declined" && <div className="mt-2 text-sm text-slate-600">OK - your project data was not used.</div>}
                  {m.pAsk?.state === "ask" && (
                    <div className="mt-3 space-y-2 rounded-xl border border-external-border bg-external-surface p-3.5">
                      <p className="text-sm font-medium text-slate-900">Your project does not contain enough information. Would you like me to search external sources?</p>
                      <div className="flex flex-wrap gap-2">{m.pAsk.options.map((o) => <button key={o.value} className={o.value === "deny" ? "btn-primary" : "btn-secondary"} onClick={() => projectConsent(m, o.value)}>{o.label}</button>)}</div></div>)}
                  {m.pAsk?.state === "loading" && <Spinner label="Searching external sources…" />}
                  {m.pAsk?.state === "denied" && <div className="mt-2 text-sm text-slate-600">Staying with project information only. No external search was made.</div>}
                  {m.pExternal && <div className="mt-3 rounded-xl border border-external-border bg-external-surface"><div className="flex items-center gap-2 border-b border-external-border/40 px-4 py-2.5 text-sm font-semibold text-amber-800"><AlertTriangle size={16} />External information — not from your project</div><div className="whitespace-pre-wrap p-4 text-sm text-slate-900">{m.pExternal.answer}</div></div>}
                  {m.error && <Banner tone="red">{m.error}</Banner>}
                  {m.lots && m.lots.length > 0 && (
                    <div className="mt-3 overflow-x-auto rounded-xl border border-slate-200">
                      <table className="w-full text-left"><thead><tr>
                        {["Reagent", "Lot", "Quantity", "Expiry", "Location", "Status"].map((h) => <th key={h} className="px-3 py-2">{h}</th>)}</tr></thead>
                        <tbody>{m.lots.map((l) => (
                          <tr key={l.lot_id} className="border-t border-slate-200">
                            <td className="px-3 py-2">{l.name}</td><td className="px-3 py-2"><span className="code">{l.lot_no}</span></td>
                            <td className="px-3 py-2"><StockBar qty={l.quantity_available} capacity={l.capacity} status={l.status} unit={l.unit} /></td>
                            <td className="px-3 py-2">{l.expiry_date}{l.days_remaining !== null && l.days_remaining !== undefined ? ` (${l.days_remaining} d)` : ""}</td>
                            <td className="px-3 py-2">{l.location}</td><td className="px-3 py-2"><StatusBadge status={l.status} /></td>
                          </tr>))}</tbody></table>
                    </div>
                  )}
                  {m.safety && <div className="mt-3"><Banner tone="amber"><ShieldAlert size={16} className="shrink-0" />{m.safety}</Banner></div>}
                  {!m.streaming && m.text && !m.error && (
                    <div className="mt-3 flex gap-1 border-t border-slate-100 pt-2 text-slate-400">
                      <button aria-label="Helpful" title="Helpful" className={`icon-btn h-8 w-8 ${m.feedback === "up" ? "text-green-700" : ""}`} onClick={() => feedback(m, "up")}><ThumbsUp size={15} /></button>
                      <button aria-label="Not helpful" title="Not helpful" className={`icon-btn h-8 w-8 ${m.feedback === "down" ? "text-red-700" : ""}`} onClick={() => feedback(m, "down")}><ThumbsDown size={15} /></button>
                    </div>
                  )}
                  {m.consent === "ask" && (
                    <div className="mt-3 space-y-3 rounded-xl border border-external-border bg-external-surface p-3.5" data-testid="consent-card">
                      <p className="text-sm font-medium text-slate-900">I couldn&apos;t find this in the approved lab documents. Would you like me to check online using AI?</p>
                      <div className="flex gap-2">
                        <button className="btn-primary" onClick={() => goExternal(m)}>Yes, search online</button>
                        <button className="btn-secondary" onClick={() => patch(m.id, { consent: "declined" })}>No, thanks</button>
                      </div>
                    </div>
                  )}
                  {m.consent === "loading" && <Spinner label="Checking online (unverified)…" />}
                  {m.consent === "declined" && (
                    <div className="mt-3 space-y-2 text-sm">
                      <p>No problem. Please contact a Senior Analyst, or ask for an official SOP to be written.</p>
                      <button className="btn-secondary" disabled={m.sopRequested} onClick={() => requestSop(m)}>{m.sopRequested ? "Official SOP requested" : "Request official SOP"}</button>
                    </div>
                  )}
                </div>
                {m.external && (
                  <ExternalWarningCard res={m.external} requested={!!m.sopRequested} onFeedback={(f) => feedback(m, f)} onRequestSop={() => requestSop(m)} />
                )}
              </div>
            ))}
            <div ref={bottom} />
          </div>
        </div>

        <form className="mx-auto mt-2 w-full max-w-[760px]" onSubmit={(e) => { e.preventDefault(); void ask(input); }}>
          <div className="flex items-end gap-2 rounded-xl border border-slate-200 bg-white p-2 transition-colors focus-within:border-brand-600 focus-within:ring-2 focus-within:ring-brand-600/20">
            <textarea data-tour="chat-input" aria-label="Message the assistant" rows={1} value={input} disabled={busy}
              className="max-h-40 min-h-[44px] flex-1 resize-none bg-transparent px-2 py-2.5 text-[15px] text-slate-900 placeholder:text-slate-400 focus:outline-none"
              placeholder="Ask anything - or say “Remember that I prefer …”"
              onChange={(e) => { setInput(e.target.value); e.target.style.height = "auto"; e.target.style.height = `${Math.min(e.target.scrollHeight, 160)}px`; }}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void ask(input); } }} />
            <button className="btn-primary h-11 w-11 shrink-0 px-0" disabled={busy || !input.trim()} aria-label="Send"><Send size={18} /></button>
          </div>
          <p className="mt-1.5 text-center text-[11px] text-slate-500">Enter to send · Shift+Enter for a new line · AI can be wrong, you make the final decision</p>
        </form>
      </div>

      {panelOpen && (
        <>
          <div className="hidden w-1.5 shrink-0 cursor-col-resize rounded-full transition-colors hover:bg-brand-200 active:bg-brand-300 lg:block" onPointerDown={startResize} role="separator" aria-orientation="vertical" aria-label="Resize retrieved context" />
          <div className="hidden shrink-0 lg:block" style={{ width: panelW }}>{panel(() => setPanelOpen(false))}</div>
        </>
      )}
      {drawer && (
        <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-label="Retrieved context">
          <div className="absolute inset-0 bg-slate-900/25" onClick={() => setDrawer(false)} />
          <div className="absolute inset-y-0 right-0 w-[min(92vw,420px)] animate-fade-up bg-slate-50 p-3 shadow-xl">{panel(() => setDrawer(false))}</div>
        </div>
      )}
      <SourceDrawer citation={source} onClose={() => setSource(null)} />
      {pSource && <SourceModal projectId={pSource.projectId} c={pSource.c} onClose={() => setPSource(null)} />}
    </div>
  );
}
