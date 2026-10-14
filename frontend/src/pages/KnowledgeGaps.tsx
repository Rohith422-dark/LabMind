import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, type Schemas } from "@/api/client";
import { Empty, Spinner, StatusBadge } from "@/components/ui";

export default function KnowledgeGaps() {
  const q = useQuery({ queryKey: ["gaps"], queryFn: () => api<Schemas["GapOut"][]>("/gaps") });
  const top = (q.data ?? []).slice(0, 8).map((g) => ({ name: g.question.length > 38 ? g.question.slice(0, 36) + "…" : g.question, asked: g.similar_count }));
  return (
    <div className="space-y-4">
      <h1 className="text-[26px] font-semibold leading-tight">Knowledge gaps</h1>
      <p className="text-slate-600">Questions the approved documents could not answer. Upload the missing document to close the loop — the requester is notified automatically.</p>
      {q.isLoading && <Spinner />}
      {q.data?.length === 0 && <Empty title="No knowledge gaps">When a scientist asks something the approved documents do not cover, it appears here.</Empty>}
      {top.length > 0 && (
        <div className="card p-4"><h2 className="mb-2 font-semibold">Most asked uncovered questions</h2>
          <ResponsiveContainer width="100%" height={Math.max(160, top.length * 38)}>
            <BarChart data={top} layout="vertical" margin={{ left: 20, right: 20 }}>
              <CartesianGrid strokeDasharray="3 3" /><XAxis type="number" allowDecimals={false} /><YAxis type="category" dataKey="name" width={260} tick={{ fontSize: 12 }} />
              <Tooltip /><Bar dataKey="asked" fill="#2563eb" radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer></div>
      )}
      {!!q.data?.length && (
        <div className="card overflow-x-auto"><table className="w-full text-left text-sm" data-testid="gaps-table">
          <thead className="bg-slate-50 text-slate-600"><tr>{["Question", "Asked", "First asked by", "Status", ""].map((h) => <th key={h} className="px-3 py-2 font-semibold">{h}</th>)}</tr></thead>
          <tbody>{q.data.map((g) => (
            <tr key={g.id} className="border-t border-slate-100 align-top">
              <td className="px-3 py-2">{g.question}</td><td className="px-3 py-2">{g.similar_count}×</td>
              <td className="px-3 py-2">{g.requester_name}<div className="text-xs text-slate-500">{new Date(g.created_at).toLocaleString()}</div></td>
              <td className="px-3 py-2"><StatusBadge status={g.status} /></td>
              <td className="px-3 py-2">{g.status !== "resolved" && <Link className="btn-primary px-3 py-1" to={`/sops?gap=${g.id}`}>Upload SOP</Link>}
                {g.linked_document_id && <Link className="text-brand-700 underline" to={`/sops/${g.linked_document_id}`}>View document</Link>}</td>
            </tr>))}</tbody></table></div>
      )}
    </div>
  );
}
