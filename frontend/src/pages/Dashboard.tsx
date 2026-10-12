import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip, Legend } from "recharts";
import { api, type Schemas } from "@/api/client";
import { useAuth } from "@/context/AuthContext";
import { Empty, Spinner } from "@/components/ui";

const COLORS: Record<string, string> = { green: "#16a34a", amber: "#d97706", red: "#dc2626", open: "#d97706", sop_requested: "#2563eb", sop_uploaded: "#7c3aed", resolved: "#16a34a" };
const NAMES: Record<string, string> = { green: "In stock", amber: "Low / expiring", red: "Expired / out" };

function Donut({ title, data }: { title: string; data: Schemas["Slice"][] }) {
  return (
    <div className="card p-4"><h2 className="mb-2 font-semibold">{title}</h2>
      <ResponsiveContainer width="100%" height={220}>
        <PieChart><Pie data={data.map((d) => ({ ...d, name: NAMES[d.name] ?? d.name.replace(/_/g, " "), key: d.name }))} dataKey="value" nameKey="name" innerRadius={50} outerRadius={80}>
          {data.map((d) => <Cell key={d.name} fill={COLORS[d.name] ?? "#64748b"} />)}</Pie><Tooltip /><Legend /></PieChart>
      </ResponsiveContainer></div>
  );
}

export default function Dashboard() {
  const { me } = useAuth();
  const q = useQuery({ queryKey: ["dashboard"], queryFn: () => api<Schemas["DashboardOut"]>("/dashboard") });
  return (
    <div className="space-y-5">
      <h1 className="text-2xl font-bold">Welcome, {me?.user.full_name}</h1>
      {q.isLoading && <Spinner />}
      {q.data && (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4" data-testid="dashboard-cards">
            {q.data.cards.map((c) => {
              const body = (<><div className="text-3xl font-bold text-brand-700">{c.value}</div><div className="text-sm text-slate-600">{c.label}</div></>);
              return c.link ? <Link key={c.label} to={c.link} className="card p-5 transition hover:border-brand-500">{body}</Link> : <div key={c.label} className="card p-5">{body}</div>;
            })}
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            {q.data.lots_by_status.length > 0 && <Donut title="Inventory lot status" data={q.data.lots_by_status} />}
            {q.data.gaps_by_status.length > 0 && <Donut title="Knowledge gaps by status" data={q.data.gaps_by_status} />}
          </div>
          {q.data.lots_by_status.length === 0 && q.data.gaps_by_status.length === 0 && q.data.cards.every((c) => c.value === 0) && (
            <Empty title="Nothing to show yet">Activity appears here as soon as there are real records.</Empty>
          )}
        </>
      )}
    </div>
  );
}
