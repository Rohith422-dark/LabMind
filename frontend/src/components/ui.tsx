import { AlertTriangle, ChevronLeft, ChevronRight, Loader2, X } from "lucide-react";
import { useEffect, type ReactNode } from "react";

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
  return <div className={`flex items-start gap-2 rounded-lg border px-3 py-2 text-sm ${t}`}><AlertTriangle size={16} className="mt-0.5 shrink-0" />{children}</div>;
}

const BADGE: Record<string, string> = {
  green: "bg-green-100 text-green-800", amber: "bg-amber-100 text-amber-800", red: "bg-red-100 text-red-800",
  followed: "bg-green-100 text-green-800", missing: "bg-red-100 text-red-800", deviation: "bg-orange-100 text-orange-800",
  out_of_order: "bg-purple-100 text-purple-800", confirm: "bg-blue-100 text-blue-800",
  effective: "bg-green-100 text-green-800", superseded: "bg-red-100 text-red-800", retired: "bg-slate-200 text-slate-700",
  draft: "bg-slate-100 text-slate-700", pending: "bg-amber-100 text-amber-800", issued: "bg-green-100 text-green-800",
  rejected: "bg-red-100 text-red-800", open: "bg-amber-100 text-amber-800", sop_requested: "bg-blue-100 text-blue-800",
  sop_uploaded: "bg-blue-100 text-blue-800", resolved: "bg-green-100 text-green-800",
  submitted: "bg-slate-100 text-slate-800", under_review: "bg-blue-100 text-blue-800", needs_clarification: "bg-orange-100 text-orange-800",
  approved: "bg-indigo-100 text-indigo-800", fulfilled: "bg-green-100 text-green-800",
  available: "bg-green-100 text-green-800", low: "bg-amber-100 text-amber-800", out_of_stock: "bg-red-100 text-red-800",
  expired: "bg-red-100 text-red-800", unavailable: "bg-slate-200 text-slate-700", awaiting_restock: "bg-purple-100 text-purple-800",
  owner: "bg-purple-100 text-purple-800", editor: "bg-blue-100 text-blue-800", viewer: "bg-slate-100 text-slate-700",
  success: "bg-green-100 text-green-800", failure: "bg-red-100 text-red-800", inconclusive: "bg-amber-100 text-amber-800",
  unknown: "bg-slate-100 text-slate-700", urgent: "bg-red-100 text-red-800", high: "bg-orange-100 text-orange-800",
  normal: "bg-slate-100 text-slate-700", ready: "bg-green-100 text-green-800", sufficient: "bg-green-100 text-green-800",
  partial: "bg-amber-100 text-amber-800", insufficient: "bg-red-100 text-red-800",
};
const LABEL: Record<string, string> = {
  green: "In stock", amber: "Low / expiring", red: "Expired / out", out_of_order: "Out of order", sop_requested: "SOP requested",
  followed: "Followed", missing: "Missing", deviation: "Deviation", confirm: "Confirm",
  low: "Running low", out_of_stock: "Out of stock", awaiting_restock: "Awaiting restocking",
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

export function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4" role="dialog" aria-modal="true" aria-label={title}>
      <div className={`card my-8 w-full ${wide ? "max-w-4xl" : "max-w-lg"} p-6`}>
        <div className="mb-4 flex items-start justify-between gap-4">
          <h2 className="text-lg font-bold">{title}</h2>
          <button aria-label="Close" className="text-slate-500 hover:text-slate-900" onClick={onClose}><X size={20} /></button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function Pager({ total, limit, offset, onChange }: { total: number; limit: number; offset: number; onChange: (offset: number) => void }) {
  if (total <= limit) return null;
  const page = Math.floor(offset / limit) + 1;
  const pages = Math.ceil(total / limit);
  return (
    <div className="mt-3 flex items-center justify-end gap-3 text-sm text-slate-600">
      <span>{offset + 1}-{Math.min(offset + limit, total)} of {total}</span>
      <button className="btn-secondary px-2 py-1" aria-label="Previous page" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - limit))}><ChevronLeft size={16} /></button>
      <span>Page {page} / {pages}</span>
      <button className="btn-secondary px-2 py-1" aria-label="Next page" disabled={offset + limit >= total} onClick={() => onChange(offset + limit)}><ChevronRight size={16} /></button>
    </div>
  );
}

export function fmtDate(iso?: string | null): string {
  return iso ? new Date(iso).toLocaleString() : "";
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`skeleton ${className}`} aria-hidden="true" />;
}
