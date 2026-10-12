import type { CompareRow } from "@/api/types";
import { StatusBadge } from "@/components/ui";

export function ComparisonTable({ rows, onOpenStep }: { rows: CompareRow[]; onOpenStep?: (stepNo: number) => void }) {
  return (
    <div className="card overflow-x-auto">
      <table className="w-full text-left text-sm" data-testid="comparison-table">
        <thead className="bg-slate-50 text-slate-600">
          <tr>{["Step", "Your procedure", "SOP requirement", "Status"].map((h) => <th key={h} className="px-3 py-2 font-semibold">{h}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r, i) => {
            const loud = r.is_critical && r.status !== "followed";
            return (
              <tr key={i} className={`border-t border-slate-100 align-top ${loud ? "bg-red-50/60" : ""}`}>
                <td className="px-3 py-2 font-semibold">
                  {r.step_no !== null ? (
                    <button className="text-brand-700 underline" onClick={() => onOpenStep?.(r.step_no!)}>{r.step_no}</button>
                  ) : "—"}
                  {r.is_critical && <span className="ml-1 text-xs font-bold text-red-600" title="Critical step">!</span>}
                </td>
                <td className="px-3 py-2">{r.narrated ?? <span className="italic text-slate-400">not described</span>}</td>
                <td className="px-3 py-2">
                  <div>{r.sop_action}</div>
                  {r.sop_requirement && <div className="text-xs text-slate-500">{r.sop_requirement}</div>}
                  {r.findings.filter((f) => f.result !== "ok").map((f, k) => (
                    <div key={k} className={`mt-1 text-xs ${f.result === "deviation" ? "font-semibold text-orange-700" : "text-blue-700"}`}>
                      {f.param}: SOP {f.expected_text} ({f.tolerance}) — {f.result === "deviation" ? `you: ${f.actual_text}` : "not stated"}
                    </div>
                  ))}
                  {r.note && <div className="mt-1 text-xs text-orange-700">{r.note}</div>}
                </td>
                <td className="px-3 py-2">
                  <div className="flex flex-wrap gap-1">
                    <StatusBadge status={r.status} />
                    {r.flags.filter((f) => f !== r.status).map((f) => <StatusBadge key={f} status={f} />)}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
