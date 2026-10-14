import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Activity, AlertTriangle, ArrowRight, CheckCircle2, Clock, Layers, type LucideIcon } from "lucide-react";
import { api, type Schemas } from "@/api/client";
import { useAuth } from "@/context/AuthContext";
import { Banner, Empty, Skeleton, errMsg } from "@/components/ui";

type Overview = Schemas["OverviewOut"];

// one accent (teal); colour only where it carries meaning (status tones)
const TONE: Record<string, { icon: string; chip: string }> = {
  blue: { icon: "bg-brand-100 text-brand-600", chip: "bg-brand-100 text-brand-700" },
  green: { icon: "bg-green-100 text-green-700", chip: "bg-green-100 text-green-700" },
  amber: { icon: "bg-amber-100 text-amber-700", chip: "bg-amber-100 text-amber-700" },
  red: { icon: "bg-red-100 text-red-700", chip: "bg-red-100 text-red-700" },
  purple: { icon: "bg-brand-100 text-brand-600", chip: "bg-brand-100 text-brand-700" },
  slate: { icon: "bg-slate-100 text-slate-600", chip: "bg-slate-100 text-slate-700" },
};
const ICONS: Record<string, LucideIcon> = { blue: Activity, green: CheckCircle2, amber: Clock, red: AlertTriangle, purple: Layers, slate: Layers };
const PALETTE = ["#0F766E", "#2563EB", "#3FA89D", "#93C5FD", "#B45309", "#83919C"];
const NAMED: Record<string, string> = { success: "#15803D", failure: "#B91C1C", inconclusive: "#B45309", unknown: "#83919C", Available: "#0F766E", "Running low": "#B45309", "Out of stock": "#B91C1C", Expired: "#B91C1C", Unavailable: "#83919C", "Awaiting restocking": "#2563EB" };

function ChartCard({ c }: { c: Overview["charts"][number] }) {
  const empty = c.data.length === 0 || c.data.every((d) => d.value === 0);
  return (
    <div className="card p-4">
      <h2 className="mb-3 text-[15px] font-semibold text-slate-900">{c.title}</h2>
      {empty ? <div className="flex h-[220px] items-center justify-center text-sm text-slate-400">No data yet</div> : (
        <ResponsiveContainer width="100%" height={220}>
          {c.kind === "donut" ? (
            <PieChart><Pie data={c.data} dataKey="value" nameKey="name" innerRadius={50} outerRadius={80} paddingAngle={2}>
              {c.data.map((d, i) => <Cell key={d.name} fill={NAMED[d.name] ?? PALETTE[i % PALETTE.length]} />)}</Pie><Tooltip /><Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} /></PieChart>
          ) : (
            <BarChart data={c.data} margin={{ left: -20, right: 8 }}><CartesianGrid stroke="#E6ECEF" vertical={false} /><XAxis dataKey="name" tick={{ fontSize: 11, fill: "#536574" }} interval={0} axisLine={{ stroke: "#DCE5EA" }} tickLine={false} /><YAxis allowDecimals={false} tick={{ fontSize: 11, fill: "#536574" }} axisLine={false} tickLine={false} />
              <Tooltip cursor={{ fill: "#F1F5F7" }} contentStyle={{ borderRadius: 8, border: "1px solid #DCE5EA", fontSize: 12 }} /><Bar dataKey="value" fill="#0F766E" radius={[4, 4, 0, 0]} maxBarSize={36} /></BarChart>
          )}
        </ResponsiveContainer>)}
    </div>
  );
}

export default function Dashboard() {
  const { me } = useAuth();
  const q = useQuery({ queryKey: ["dashboard-overview"], queryFn: () => api<Overview>("/dashboard/overview"), refetchInterval: 60000 });
  const d = q.data;
  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-[26px] leading-tight text-slate-900">{d?.headline ?? `Welcome, ${me?.user.full_name}`}</h1>
        <p className="mt-1 text-sm text-slate-600">{d?.subtitle}<span className="text-slate-400"> · {new Date().toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" })}</span></p>
      </div>
      {q.isLoading && <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-24" />)}</div>}
      {q.isError && <Banner tone="red">{errMsg(q.error)}</Banner>}
      {d && (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4" data-testid="dashboard-cards">
            {d.stats.map((s) => {
              const t = TONE[s.tone] ?? TONE.blue;
              const Icon = ICONS[s.tone] ?? Activity;
              const body = (
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0"><div className="text-xs font-medium text-slate-600">{s.label}</div>
                    <div className="mt-1 text-[28px] font-semibold leading-none tracking-tight text-slate-900">{s.value}</div>
                    {s.hint && <div className="mt-1.5 text-xs text-slate-500">{s.hint}</div>}</div>
                  <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${t.icon}`}><Icon size={18} strokeWidth={1.75} /></span>
                </div>);
              return s.link ? <Link key={s.label} to={s.link} className="card p-4 transition-colors duration-150 hover:border-brand-300">{body}</Link> : <div key={s.label} className="card p-4">{body}</div>;
            })}
          </div>
          <div className="grid gap-4 lg:grid-cols-3">{d.charts.map((c) => <ChartCard key={c.title} c={c} />)}</div>
          <div className="grid gap-4 lg:grid-cols-2">
            {d.blocks.map((b) => (
              <div key={b.title} className="card p-4">
                <div className="mb-2 flex items-center justify-between"><h2 className="text-[15px] font-semibold text-slate-900">{b.title}</h2>
                  {b.link && <Link to={b.link} className="inline-flex items-center gap-1 text-xs font-medium text-brand-600 hover:text-brand-700">View all <ArrowRight size={12} /></Link>}</div>
                {b.items.length === 0 ? <div className="py-4 text-center text-sm text-slate-400">{b.empty}</div> : (
                  <ul className="divide-y divide-slate-100">{b.items.map((it, i) => {
                    const inner = (
                      <div className="flex items-start justify-between gap-3 py-2">
                        <div className="min-w-0"><div className="truncate text-sm font-medium text-slate-800">{it.primary}</div>{it.secondary && <div className="truncate text-xs text-slate-500">{it.secondary}</div>}</div>
                        {it.badge && <span className={`badge shrink-0 ${(TONE[it.tone] ?? TONE.slate).chip}`}>{it.badge}</span>}
                      </div>);
                    return <li key={i}>{it.link ? <Link to={it.link} className="block rounded hover:bg-slate-50">{inner}</Link> : inner}</li>;
                  })}</ul>)}
              </div>))}
          </div>
          {d.stats.every((s) => s.value === 0 || s.value === "0 / 0") && d.blocks.every((b) => b.items.length === 0) && <Empty title="Nothing to show yet">Activity appears here as soon as there are real records.</Empty>}
        </>)}
    </div>
  );
}
