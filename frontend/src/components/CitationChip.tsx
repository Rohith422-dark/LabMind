import type { Citation } from "@/api/types";

export function CitationChip({ c, onOpen }: { c: Citation; onOpen: (c: Citation) => void }) {
  return (
    <span className="group relative inline-block align-baseline">
      <button type="button" data-tour="citation-chip" onClick={() => onOpen(c)}
        className="mx-0.5 inline-flex h-5 min-w-[1.25rem] items-center justify-center rounded bg-brand-100 px-1 text-xs font-bold text-brand-700 hover:bg-brand-600 hover:text-white">
        {c.n}
      </button>
      <span className="pointer-events-none absolute bottom-full left-1/2 z-30 mb-1 hidden w-72 -translate-x-1/2 rounded-md border border-slate-200 bg-white p-2 text-xs font-normal text-slate-700 shadow-lg group-hover:block">
        <b>{c.doc_code} v{c.version}</b>{c.page ? ` · p.${c.page}` : ""}
        <span className="mt-1 block">{c.snippet.slice(0, 200)}…</span>
      </span>
    </span>
  );
}

/** Render answer text turning [n] markers into chips. */
export function AnswerText({ text, citations, onOpen }: { text: string; citations: Citation[]; onOpen: (c: Citation) => void }) {
  const byN = new Map(citations.map((c) => [c.n, c]));
  const parts = text.split(/(\[\d{1,2}\])/g);
  return (
    <div className="whitespace-pre-wrap leading-relaxed">
      {parts.map((p, i) => {
        const m = /^\[(\d{1,2})\]$/.exec(p);
        if (!m) return <span key={i}>{p}</span>;
        const c = byN.get(Number(m[1]));
        return c ? <CitationChip key={i} c={c} onOpen={onOpen} /> : <span key={i} className="text-slate-400">{p}</span>;
      })}
    </div>
  );
}
