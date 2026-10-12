import { AlertTriangle, Loader2 } from "lucide-react";
import type { ReactNode } from "react";

export function Spinner({ label }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-slate-500">
      <Loader2 className="animate-spin" size={18} />{label}
    </span>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="card p-10 text-center">
      <div className="font-semibold text-slate-700">{title}</div>
      {children && <div className="mt-1 text-sm text-slate-500">{children}</div>}
    </div>
  );
}

export function Banner({ tone, children }: { tone: "red" | "amber" | "blue" | "green"; children: ReactNode }) {
  const t = {
    red: "border-red-300 bg-red-50 text-red-900", amber: "border-amber-300 bg-amber-50 text-amber-900",
    blue: "border-blue-300 bg-blue-50 text-blue-900", green: "border-green-300 bg-green-50 text-green-900",
  }[tone];
  return <div className={`flex items-start gap-2 rounded-md border px-3 py-2 text-sm ${t}`}><AlertTriangle size={16} className="mt-0.5 shrink-0" />{children}</div>;
}

const BADGE: Record<string, string> = {
  green: "bg-green-100 text-green-800", amber: "bg-amber-100 text-amber-800", red: "bg-red-100 text-red-800",
  followed: "bg-green-100 text-green-800", missing: "bg-red-100 text-red-800", deviation: "bg-orange-100 text-orange-800",
  out_of_order: "bg-purple-100 text-purple-800", confirm: "bg-blue-100 text-blue-800",
  effective: "bg-green-100 text-green-800", superseded: "bg-red-100 text-red-800", retired: "bg-slate-200 text-slate-700",
  draft: "bg-slate-100 text-slate-700", pending: "bg-amber-100 text-amber-800", issued: "bg-green-100 text-green-800",
  rejected: "bg-red-100 text-red-800", open: "bg-amber-100 text-amber-800", sop_requested: "bg-blue-100 text-blue-800",
  sop_uploaded: "bg-blue-100 text-blue-800", resolved: "bg-green-100 text-green-800",
};
const LABEL: Record<string, string> = {
  green: "In stock", amber: "Low / expiring", red: "Expired / out", out_of_order: "Out of order", sop_requested: "SOP requested",
  followed: "Followed", missing: "Missing", deviation: "Deviation", confirm: "Confirm",
};

export function StatusBadge({ status }: { status: string }) {
  return <span className={`badge ${BADGE[status] ?? "bg-slate-100 text-slate-700"}`}>{LABEL[status] ?? status.replace(/_/g, " ")}</span>;
}

export function HazardBadges({ classes }: { classes: string[] }) {
  if (!classes?.length) return null;
  return <>{classes.slice(0, 4).map((c) => <span key={c} className="badge bg-rose-50 text-rose-700">{c}</span>)}</>;
}

export function errMsg(e: unknown): string {
  return e instanceof Error ? e.message : "Something went wrong";
}
