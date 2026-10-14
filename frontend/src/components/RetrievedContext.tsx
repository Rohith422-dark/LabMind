import { useEffect, useRef, useState } from "react";
import { ChevronDown, ExternalLink, FileText, FlaskConical, PanelRightClose, Sigma } from "lucide-react";

export interface RetrievedItem {
  key: string; msgId: number; n: number; kind: "document" | "experiment" | "analysis";
  title: string; code?: string; version?: number | null; page?: number | null; section?: string | null;
  snippet: string; score: number; raw: unknown;
}

const KIND = {
  document: { icon: FileText, label: "Document" },
  experiment: { icon: FlaskConical, label: "Experiment record" },
  analysis: { icon: Sigma, label: "Computed" },
} as const;

function Card({ it, selected, onSelect, onOpen }: { it: RetrievedItem; selected: boolean; onSelect: () => void; onOpen: () => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => { if (selected) ref.current?.scrollIntoView({ block: "nearest", behavior: "smooth" }); }, [selected]);
  const K = KIND[it.kind];
  const pct = Math.round(Math.max(0, Math.min(1, it.score)) * 100);
  return (
    <div ref={ref} data-selected={selected} data-testid="retrieval-card"
      className={`rounded-[10px] border p-3.5 transition-colors duration-200 ${selected ? "border-brand-300 bg-brand-50 shadow-sm" : "border-slate-200 bg-white hover:border-slate-300"}`}>
      <div className="flex items-start gap-2.5">
        <button type="button" onClick={onSelect} aria-pressed={selected} aria-label={`Select source ${it.n}`}
          className={`mt-0.5 flex h-5 min-w-[20px] items-center justify-center rounded px-1 text-[11px] font-semibold transition-colors duration-200 ${selected ? "bg-brand-600 text-white" : "bg-slate-100 text-brand-600 hover:bg-brand-100"}`}>{it.n}</button>
        <div className="min-w-0 flex-1 cursor-pointer" onClick={onSelect}>
          <div className="flex items-start justify-between gap-2">
            <div className="truncate text-[13.5px] font-medium text-slate-900" title={it.title}>{it.title}</div>
            <span className={`badge shrink-0 ${it.kind === "document" && it.version ? "bg-green-100 text-green-700" : "bg-slate-100 text-slate-700"}`}>
              {it.kind === "document" && it.version ? "Effective" : K.label}</span>
          </div>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-slate-600">
            {it.code && <span className="code text-slate-700">{it.code}</span>}
            {it.version ? <span>v{it.version}</span> : null}
            {it.page ? <span>Page {it.page}</span> : null}
            {it.section ? <span className="truncate">§ {it.section.slice(0, 40)}</span> : null}
          </div>
          <p className={`mt-2 text-[13px] leading-relaxed text-slate-800 ${open ? "" : "line-clamp-3"}`}>{it.snippet}</p>
          <div className="mt-2.5 flex items-center gap-2" title={it.kind === "analysis" ? "Calculated from the recorded values" : `Retrieval score ${it.score.toFixed(2)}`}>
            <span className="text-[11px] font-medium text-slate-500">{it.kind === "analysis" ? "Computed from records" : "Retrieval score"}</span>
            {it.kind !== "analysis" && <>
              <span className="h-1 w-16 overflow-hidden rounded-full bg-[#E6ECEF]"><span className="block h-full rounded-full bg-brand-600 transition-[width] duration-300" style={{ width: `${pct}%` }} /></span>
              <span className="text-[11px] tabular-nums text-slate-600">{it.score.toFixed(2)}</span></>}
          </div>
        </div>
      </div>
      <div className={`grid transition-[grid-template-rows] duration-200 ease-out ${open ? "grid-rows-[1fr]" : "grid-rows-[0fr]"}`}>
        <div className="overflow-hidden"><div className="mt-3 border-t border-slate-200 pt-2.5 text-xs text-slate-600">
          {it.kind === "document" ? "Open the document to see this passage in context." : "Open the record to see it exactly as it was cited."}</div></div>
      </div>
      <div className="mt-2 flex items-center justify-between border-t border-slate-100 pt-2">
        <button type="button" className="inline-flex items-center gap-1 text-xs font-medium text-slate-600 hover:text-slate-900" aria-expanded={open} onClick={() => setOpen(!open)}>
          <ChevronDown size={14} className={`transition-transform duration-200 ${open ? "rotate-180" : ""}`} />{open ? "Show less" : "Show full passage"}</button>
        {it.kind !== "analysis" && <button type="button" className="inline-flex items-center gap-1 text-xs font-medium text-brand-600 hover:text-brand-700" onClick={onOpen}><ExternalLink size={13} />Open {it.kind === "document" ? "document" : "record"}</button>}
      </div>
    </div>
  );
}

export function RetrievedContext({ answer, conversation, selectedKey, onSelect, onOpen, onCollapse, busy }: {
  answer: RetrievedItem[]; conversation: RetrievedItem[]; selectedKey: string | null; busy: boolean;
  onSelect: (it: RetrievedItem) => void; onOpen: (it: RetrievedItem) => void; onCollapse?: () => void;
}) {
  const [tab, setTab] = useState<"answer" | "conversation">("answer");
  const items = tab === "answer" ? answer : conversation;
  return (
    <section className="flex h-full min-h-0 flex-col rounded-xl border border-slate-200 bg-white" aria-label="Retrieved context">
      <header className="flex items-center justify-between gap-2 border-b border-slate-200 bg-slate-50 px-4 py-3 rounded-t-xl">
        <div className="flex items-center gap-2"><h2 className="text-sm font-semibold text-slate-900">Retrieved context</h2>
          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-600 tabular-nums">{answer.length}</span>
          {busy && <span className="flex items-center gap-1 text-[11px] text-slate-500"><span className="h-1.5 w-1.5 rounded-full bg-brand-600" />searching</span>}</div>
        {onCollapse && <button className="icon-btn h-8 w-8" onClick={onCollapse} aria-label="Collapse retrieved context" title="Collapse"><PanelRightClose size={16} /></button>}
      </header>
      <div className="flex gap-4 border-b border-slate-200 px-4" role="tablist">
        {([["answer", "This answer"], ["conversation", "Conversation"]] as const).map(([k, l]) => (
          <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
            className={`-mb-px border-b-2 py-2.5 text-[13px] font-medium transition-colors duration-150 ${tab === k ? "border-brand-600 text-brand-600" : "border-transparent text-slate-600 hover:text-slate-900"}`}>{l}
            <span className="ml-1.5 text-[11px] text-slate-500 tabular-nums">{k === "answer" ? answer.length : conversation.length}</span></button>))}
      </div>
      <div className="min-h-0 flex-1 space-y-2.5 overflow-y-auto p-3.5">
        {items.length === 0 ? (
          <div className="flex h-full min-h-[10rem] flex-col items-center justify-center px-6 text-center">
            <FileText size={22} className="mb-2 text-slate-400" strokeWidth={1.5} />
            <p className="text-sm font-medium text-slate-700">No sources for this answer</p>
            <p className="mt-1 text-xs leading-relaxed text-slate-500">When the assistant answers from approved documents or your project records, the exact passages it relied on appear here.</p>
          </div>
        ) : items.map((it) => <Card key={it.key} it={it} selected={it.key === selectedKey} onSelect={() => onSelect(it)} onOpen={() => onOpen(it)} />)}
      </div>
    </section>
  );
}
