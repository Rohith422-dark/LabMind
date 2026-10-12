export function StockBar({ qty, capacity, status, unit }: { qty: number; capacity: number; status: string; unit?: string | null }) {
  const pct = capacity > 0 ? Math.max(0, Math.min(100, (qty / capacity) * 100)) : 0;
  const color = status === "red" ? "bg-red-500" : status === "amber" ? "bg-amber-500" : "bg-green-500";
  return (
    <div className="min-w-[8rem]">
      <div className="h-2 overflow-hidden rounded-full bg-slate-200"><div className={`h-full ${color}`} style={{ width: `${pct}%` }} /></div>
      <div className="mt-1 text-xs text-slate-600">{qty} / {capacity} {unit}</div>
    </div>
  );
}
