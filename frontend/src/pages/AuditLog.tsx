import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { CheckCircle2, XCircle } from "lucide-react";
import { api, apiBlob, type Schemas } from "@/api/client";

export default function AuditLog() {
  const [action, setAction] = useState("");
  const rows = useQuery({
    queryKey: ["audit", action],
    queryFn: () => api<Schemas["AuditOut"][]>(`/audit?limit=300${action ? `&action=${encodeURIComponent(action)}` : ""}`),
  });
  const verify = useMutation({ mutationFn: () => api<Schemas["VerifyOut"]>("/audit/verify") });

  const exportCsv = async () => {
    const url = URL.createObjectURL(await apiBlob("/audit/export"));
    const a = document.createElement("a");
    a.href = url; a.download = "audit_log.csv"; a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold">Audit log</h1>
        <div className="flex items-center gap-2">
          <input className="input w-56" placeholder="Filter by action" value={action} onChange={(e) => setAction(e.target.value)} />
          <button className="btn-secondary" onClick={exportCsv}>Export CSV</button>
          <button className="btn-primary" onClick={() => verify.mutate()} disabled={verify.isPending}>Verify integrity</button>
        </div>
      </div>
      {verify.data && (
        <div className={`mt-4 flex items-center gap-2 rounded-md p-3 text-sm font-medium ${verify.data.ok ? "bg-green-50 text-green-800" : "bg-red-50 text-red-800"}`}>
          {verify.data.ok ? <CheckCircle2 size={18} /> : <XCircle size={18} />}
          {verify.data.ok ? `Chain intact — ${verify.data.checked} entries verified` : `Chain broken at entry #${verify.data.first_broken_id}`}
        </div>
      )}
      <div className="card mt-4 overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-50 text-slate-600"><tr>
            {["#", "Time", "User", "Action", "Target", "Details"].map((h) => <th key={h} className="px-3 py-2 font-semibold">{h}</th>)}
          </tr></thead>
          <tbody>
            {rows.data?.map((r) => (
              <tr key={r.id} className="border-t border-slate-100 align-top">
                <td className="px-3 py-2 text-slate-400">{r.id}</td>
                <td className="whitespace-nowrap px-3 py-2">{new Date(r.timestamp).toLocaleString()}</td>
                <td className="px-3 py-2">{r.username ?? "—"}<div className="text-xs text-slate-500">{r.role}</div></td>
                <td className="px-3 py-2 font-medium">{r.action}</td>
                <td className="px-3 py-2">{r.target}</td>
                <td className="px-3 py-2 font-mono text-xs text-slate-500">{Object.keys(r.details).length ? JSON.stringify(r.details) : ""}</td>
              </tr>
            ))}
            {rows.data?.length === 0 && <tr><td colSpan={6} className="p-8 text-center text-slate-500">No audit entries yet.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}
