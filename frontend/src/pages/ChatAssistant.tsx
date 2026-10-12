import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Send, ShieldAlert, ThumbsDown, ThumbsUp } from "lucide-react";
import { toast } from "sonner";
import { api, streamNdjson, type Schemas } from "@/api/client";
import type { ChatEvent, Citation, ExternalResult } from "@/api/types";
import { AnswerText } from "@/components/CitationChip";
import { SourceDrawer } from "@/components/SourceDrawer";
import { ExternalWarningCard } from "@/components/ExternalWarningCard";
import { StatusBadge, Spinner, Banner, errMsg } from "@/components/ui";
import { StockBar } from "@/components/StockBar";

interface Msg {
  id: number; question: string; text: string; citations: Citation[]; safety?: string; chatId?: string;
  lots?: Schemas["LotOut"][]; gapId?: string; consent?: "ask" | "declined" | "loading" | "done";
  external?: ExternalResult; sopRequested?: boolean; error?: string; streaming: boolean; feedback?: "up" | "down";
}

let counter = 0;

export default function ChatAssistant() {
  const [params, setParams] = useSearchParams();
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState(params.get("q") ?? "");
  const [busy, setBusy] = useState(false);
  const [source, setSource] = useState<Citation | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => { const q = params.get("q"); if (q) { setInput(q); setParams({}, { replace: true }); } }, [params, setParams]);
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs]);

  const patch = (id: number, p: Partial<Msg> | ((m: Msg) => Partial<Msg>)) =>
    setMsgs((all) => all.map((m) => (m.id === id ? { ...m, ...(typeof p === "function" ? p(m) : p) } : m)));

  async function ask(question: string) {
    const q = question.trim();
    if (!q || busy) return;
    const id = ++counter;
    const history = msgs.filter((m) => m.text && !m.error).slice(-3).flatMap((m) => [
      { role: "user" as const, content: m.question }, { role: "assistant" as const, content: m.text.slice(0, 800) }]);
    setMsgs((all) => [...all, { id, question: q, text: "", citations: [], streaming: true }]);
    setInput(""); setBusy(true);
    try {
      await streamNdjson<ChatEvent>("/chat/stream", { question: q, history }, (e) => {
        if (e.type === "meta") patch(id, { chatId: e.chat_id });
        else if (e.type === "token") patch(id, (m) => ({ text: m.text + e.text }));
        else if (e.type === "citations") patch(id, { citations: e.citations });
        else if (e.type === "safety") patch(id, { safety: e.note });
        else if (e.type === "inventory") patch(id, { lots: e.lots });
        else if (e.type === "no_match") patch(id, { gapId: e.gap_id, consent: "ask" });
        else if (e.type === "error") patch(id, { error: e.message });
      });
    } catch (e) {
      patch(id, { error: errMsg(e) });
    } finally {
      patch(id, { streaming: false }); setBusy(false);
    }
  }

  async function goExternal(m: Msg) {
    patch(m.id, { consent: "loading" });
    try {
      const res = await api<ExternalResult>("/chat/external", { method: "POST", json: { gap_id: m.gapId } });
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

  return (
    <div className="mx-auto flex h-[calc(100vh-7rem)] max-w-4xl flex-col">
      <div className="mb-3">
        <h1 className="text-2xl font-bold">Ask the lab assistant</h1>
        <p className="text-sm text-slate-600">Answers come only from approved, effective lab documents. You make the final decision.</p>
      </div>
      <div className="flex-1 space-y-6 overflow-y-auto pr-1" data-testid="chat-log">
        {msgs.length === 0 && (
          <div className="card p-8 text-center text-slate-500">
            Ask about an SOP, a procedure, a troubleshooting guide, or reagent stock.
            <div className="mt-1 text-sm">Open the <b>Guide</b> (bottom right) for suggested questions.</div>
          </div>
        )}
        {msgs.map((m) => (
          <div key={m.id} className="space-y-3">
            <div className="ml-auto w-fit max-w-[85%] rounded-lg bg-brand-600 px-4 py-2 text-white" data-testid="user-msg">{m.question}</div>
            <div className="card max-w-[92%] p-4" data-testid="assistant-msg">
              {m.streaming && !m.text && <Spinner label="Searching approved documents…" />}
              {m.text && <AnswerText text={m.text} citations={m.citations} onOpen={setSource} />}
              {m.error && <Banner tone="red">{m.error}</Banner>}
              {m.lots && m.lots.length > 0 && (
                <div className="mt-3 overflow-x-auto">
                  <table className="w-full text-left text-sm"><thead className="text-slate-500"><tr>
                    {["Reagent", "Lot", "Quantity", "Expiry", "Location", "Status"].map((h) => <th key={h} className="px-2 py-1 font-semibold">{h}</th>)}</tr></thead>
                    <tbody>{m.lots.map((l) => (
                      <tr key={l.lot_id} className="border-t border-slate-100">
                        <td className="px-2 py-1">{l.name}</td><td className="px-2 py-1">{l.lot_no}</td>
                        <td className="px-2 py-1"><StockBar qty={l.quantity_available} capacity={l.capacity} status={l.status} unit={l.unit} /></td>
                        <td className="px-2 py-1">{l.expiry_date}{l.days_remaining !== null && l.days_remaining !== undefined ? ` (${l.days_remaining} d)` : ""}</td>
                        <td className="px-2 py-1">{l.location}</td><td className="px-2 py-1"><StatusBadge status={l.status} /></td>
                      </tr>))}</tbody></table>
                </div>
              )}
              {m.safety && <div className="mt-3"><Banner tone="amber"><ShieldAlert size={16} className="shrink-0" />{m.safety}</Banner></div>}
              {m.citations.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-2 border-t border-slate-100 pt-3 text-xs text-slate-600">
                  {m.citations.map((c) => (
                    <button key={c.n} className="rounded border border-slate-200 px-2 py-1 hover:border-brand-500" onClick={() => setSource(c)}>
                      [{c.n}] {c.doc_code} v{c.version}{c.page ? ` · p.${c.page}` : ""}
                    </button>
                  ))}
                </div>
              )}
              {!m.streaming && m.text && !m.error && (
                <div className="mt-2 flex gap-1 text-slate-400">
                  <button aria-label="Helpful" className={m.feedback === "up" ? "text-green-600" : "hover:text-slate-700"} onClick={() => feedback(m, "up")}><ThumbsUp size={16} /></button>
                  <button aria-label="Not helpful" className={m.feedback === "down" ? "text-red-600" : "hover:text-slate-700"} onClick={() => feedback(m, "down")}><ThumbsDown size={16} /></button>
                </div>
              )}
              {m.consent === "ask" && (
                <div className="space-y-3" data-testid="consent-card">
                  <p className="font-medium">I couldn&apos;t find this in the approved lab documents. Would you like me to check online using AI?</p>
                  <div className="flex gap-2">
                    <button className="btn-primary" onClick={() => goExternal(m)}>Yes, search online</button>
                    <button className="btn-secondary" onClick={() => patch(m.id, { consent: "declined" })}>No, thanks</button>
                  </div>
                </div>
              )}
              {m.consent === "loading" && <Spinner label="Checking online (unverified)…" />}
              {m.consent === "declined" && (
                <div className="space-y-2 text-sm">
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
      <form className="mt-3 flex gap-2" onSubmit={(e) => { e.preventDefault(); void ask(input); }}>
        <input data-tour="chat-input" className="input flex-1 py-3 text-base" placeholder="e.g. How do I recalibrate the pH meter?" value={input}
          onChange={(e) => setInput(e.target.value)} disabled={busy} />
        <button className="btn-primary px-5" disabled={busy || !input.trim()}><Send size={18} />Ask</button>
      </form>
      <SourceDrawer citation={source} onClose={() => setSource(null)} />
    </div>
  );
}
