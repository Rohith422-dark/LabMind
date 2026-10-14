export function StockBar({ qty, capacity, status, unit }: { qty: number; capacity: number; status: string; unit?: string | null }) {
  const pct = capacity > 0 ? Math.max(0, Math.min(100, (qty / capacity) * 100)) : 0;
  const color = status === "red" ? "bg-red-600" : status === "amber" ? "bg-amber-400" : "bg-brand-600";
  return (
    <div className="min-w-[8rem]">
      <div className="h-1.5 overflow-hidden rounded-full bg-[#E6ECEF]"><div className={`h-full ${color}`} style={{ width: `${pct}%` }} /></div>
      <div className="mt-1 text-xs text-slate-600">{qty} / {capacity} {unit}</div>
    </div>
  );
}
