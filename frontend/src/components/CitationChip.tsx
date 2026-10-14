import type { Citation } from "@/api/types";

/** Numbered inline marker. `active` mirrors the selected card in the Retrieved context panel (same selected token). */
export function CitationMarker({ n, active, title, onClick, preview }: { n: number; active?: boolean; title: string; onClick: () => void; preview?: React.ReactNode }) {
  return (
    <span className="group relative inline-block align-baseline">
      <button type="button" data-tour="citation-chip" onClick={onClick} aria-pressed={!!active} aria-label={`Source ${n}: ${title}`}
        className={`mx-0.5 inline-flex h-[18px] min-w-[18px] items-center justify-center rounded border px-1 text-[11px] font-semibold leading-none transition-colors duration-200 ${active ? "border-brand-600 bg-brand-100 text-brand-700" : "border-transparent bg-transparent text-brand-600 hover:bg-brand-100"}`}>
        {n}
      </button>
      {preview && (
        <span className="pointer-events-none absolute bottom-full left-1/2 z-30 mb-1.5 hidden w-72 -translate-x-1/2 animate-fade-up rounded-[10px] border border-slate-200 bg-white p-3 text-xs font-normal text-slate-700 shadow-lg shadow-slate-900/10 group-hover:block">
          {preview}
        </span>
      )}
    </span>
  );
}

export function CitationChip({ c, onOpen, active }: { c: Citation; onOpen: (c: Citation) => void; active?: boolean }) {
  return (
    <CitationMarker n={c.n} active={active} title={`${c.doc_code} v${c.version}`} onClick={() => onOpen(c)}
      preview={<><div className="text-[13px] font-medium text-slate-900">{c.title}</div>
        <div className="mt-0.5 text-slate-600"><span className="code">{c.doc_code}</span> · v{c.version}{c.page ? ` · p.${c.page}` : ""}</div>
        <div className="mt-1.5 line-clamp-3 leading-relaxed">{c.snippet}</div></>} />
  );
}

/** Render answer text turning [n] markers into citation markers and **bold** into emphasis. */
export function AnswerText({ text, citations, onOpen, activeN }: { text: string; citations: Citation[]; onOpen: (c: Citation) => void; activeN?: number | null }) {
  const byN = new Map(citations.map((c) => [c.n, c]));
  const parts = text.split(/(\[\d{1,2}\]|\*\*[^*]+\*\*)/g);
  return (
    <div className="whitespace-pre-wrap text-[15px] leading-[1.65] text-slate-900">
      {parts.map((p, i) => {
        if (/^\*\*[^*]+\*\*$/.test(p)) return <b key={i} className="font-semibold">{p.slice(2, -2)}</b>;
        const m = /^\[(\d{1,2})\]$/.exec(p);
        if (!m) return <span key={i}>{p}</span>;
        const c = byN.get(Number(m[1]));
        return c ? <CitationChip key={i} c={c} onOpen={onOpen} active={activeN === c.n} /> : <span key={i} className="text-slate-400">{p}</span>;
      })}
    </div>
  );
}
