import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { Schemas } from "@/api/client";
import { Empty, Spinner, StatusBadge } from "@/components/ui";

export default function MyRequests() {
  const q = useQuery({ queryKey: ["myreq"], queryFn: () => api<Schemas["RequestOut"][]>("/requests/mine") });
  return (
    <div>
      <h1 className="mb-4 text-2xl font-bold">My requests</h1>
      {q.isLoading && <Spinner />}
      {q.data?.length === 0 && <Empty title="No requests yet">Raise one from the Inventory page.</Empty>}
      {!!q.data?.length && (
        <div className="card overflow-x-auto">
          <table className="w-full text-left text-sm" data-testid="my-requests">
            <thead className="bg-slate-50 text-slate-600"><tr>{["Raised", "Reagent", "Quantity", "Purpose", "Status"].map((h) => <th key={h} className="px-3 py-2 font-semibold">{h}</th>)}</tr></thead>
            <tbody>{q.data.map((r) => (
              <tr key={r.id} className="border-t border-slate-100">
                <td className="px-3 py-2">{new Date(r.created_at).toLocaleString()}</td><td className="px-3 py-2">{r.reagent_name}</td>
                <td className="px-3 py-2">{r.quantity} {r.unit}</td><td className="px-3 py-2">{r.purpose}{r.experiment_ref ? ` (${r.experiment_ref})` : ""}</td>
                <td className="px-3 py-2"><StatusBadge status={r.status} />{r.reject_reason && <div className="text-xs text-red-700">{r.reject_reason}</div>}</td>
              </tr>))}</tbody>
          </table>
        </div>
      )}
    </div>
  );
}
