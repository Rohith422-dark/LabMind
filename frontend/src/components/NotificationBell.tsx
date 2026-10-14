import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell } from "lucide-react";
import { api, type Schemas } from "@/api/client";

export function NotificationBell() {
  const [open, setOpen] = useState(false);
  const qc = useQueryClient();
  const nav = useNavigate();
  const q = useQuery({ queryKey: ["notifications"], queryFn: () => api<Schemas["NotificationOut"][]>("/notifications"), refetchInterval: 15000 });
  const read = useMutation({
    mutationFn: (id: string) => api(`/notifications/${id}/read`, { method: "PATCH" }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["notifications"] }),
  });
  const unread = q.data?.filter((n) => !n.is_read).length ?? 0;
  return (
    <div className="relative">
      <button aria-label="Notifications" className="icon-btn relative" onClick={() => setOpen(!open)}>
        <Bell size={20} />
        {unread > 0 && <span className="absolute right-1 top-1 flex h-4 min-w-[1rem] items-center justify-center rounded-full bg-red-600 px-1 text-[10px] font-semibold text-white" data-testid="unread-count">{unread}</span>}
      </button>
      {open && (
        <div className="absolute right-0 z-30 mt-2 w-96 max-w-[90vw] animate-fade-up rounded-xl border border-slate-200 bg-white shadow-lg shadow-slate-900/5">
          <div className="border-b border-slate-200 px-4 py-3 text-sm font-semibold">Notifications</div>
          <ul className="max-h-80 overflow-y-auto">
            {q.data?.length === 0 && <li className="p-4 text-sm text-slate-500">Nothing yet.</li>}
            {q.data?.map((n) => (
              <li key={n.id}>
                <button className={`w-full px-4 py-3 text-left text-sm hover:bg-slate-50 ${n.is_read ? "text-slate-500" : "font-medium"}`}
                  onClick={() => { read.mutate(n.id); setOpen(false); if (n.link) nav(n.link); }}>
                  {n.message}<div className="text-xs font-normal text-slate-400">{new Date(n.created_at).toLocaleString()}</div></button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
