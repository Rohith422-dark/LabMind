import { AlertTriangle, ExternalLink } from "lucide-react";
import type { ExternalResult } from "@/api/types";

/** Visually distinct amber card: external AI output is never mistakable for an approved answer. */
export function ExternalWarningCard({ res, onFeedback, onRequestSop, requested }: {
  res: ExternalResult; onFeedback: (f: "up" | "down") => void; onRequestSop: () => void; requested: boolean;
}) {
  return (
    <div className="rounded-lg border-2 border-amber-400 bg-amber-50" data-testid="external-card">
      <div className="flex items-center gap-2 rounded-t-md bg-amber-400 px-4 py-2 text-sm font-bold uppercase tracking-wide text-amber-950">
        <AlertTriangle size={18} /> External AI result — not from approved lab documents
      </div>
      <div className="space-y-3 p-4">
        <div className="whitespace-pre-wrap text-slate-900">{res.answer}</div>
        {res.sources.length > 0 ? (
          <div>
            <div className="text-xs font-semibold uppercase text-amber-900">Web sources</div>
            <ul className="mt-1 space-y-1 text-sm">
              {res.sources.map((s) => (
                <li key={s.uri}><a className="inline-flex items-center gap-1 text-brand-700 underline" href={s.uri} target="_blank" rel="noreferrer noopener">
                  <ExternalLink size={14} />{s.title} <span className="text-slate-500">({s.domain})</span></a></li>
              ))}
            </ul>
          </div>
        ) : <div className="text-xs text-amber-900">No web sources available for this answer.</div>}
        <p className="border-t border-amber-300 pt-3 text-sm font-medium text-amber-950">
          This information may be inaccurate or outdated. It is not an approved SOP. Verify with a Senior Analyst or an official source before using it in any experiment.
        </p>
        <div className="flex flex-wrap gap-2">
          <button className="btn-secondary" onClick={() => onFeedback("up")}>Helpful</button>
          <button className="btn-secondary" onClick={() => onFeedback("down")}>Wrong</button>
          <button className="btn-primary" disabled={requested} onClick={onRequestSop}>{requested ? "Official SOP requested" : "Request official SOP"}</button>
        </div>
      </div>
    </div>
  );
}
