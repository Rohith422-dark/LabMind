import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Pencil, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api, type Schemas } from "@/api/client";
import { useAuth } from "@/context/AuthContext";
import { Banner, Empty, Spinner, errMsg, fmtDate } from "@/components/ui";
import type { TabProps } from "@/pages/ProjectDetail";

type Mem = Schemas["MemoryOut"];

export default function ProjectMemory({ project: p, canWrite, isOwner }: TabProps) {
  const qc = useQueryClient();
  const { me } = useAuth();
  const q = useQuery({ queryKey: ["pmemory", p.id], queryFn: () => api<Mem[]>(`/projects/${p.id}/memory`) });
  const [text, setText] = useState("");
  const [kind, setKind] = useState<"note" | "terminology" | "finding">("note");
  const [editing, setEditing] = useState<{ id: string; content: string } | null>(null);
  const refresh = () => void qc.invalidateQueries({ queryKey: ["pmemory", p.id] });

  const add = useMutation({
    mutationFn: () => api(`/projects/${p.id}/memory`, { method: "POST", json: { content: text, kind } }),
    onSuccess: () => { toast.success("Saved to project memory"); setText(""); refresh(); }, onError: (e) => toast.error(errMsg(e)),
  });
  const save = useMutation({
    mutationFn: (v: { id: string; content: string }) => api(`/projects/${p.id}/memory/${v.id}`, { method: "PATCH", json: { content: v.content } }),
    onSuccess: () => { setEditing(null); refresh(); }, onError: (e) => toast.error(errMsg(e)),
  });
  const confirm = useMutation({
    mutationFn: (id: string) => api(`/projects/${p.id}/memory/${id}/confirm`, { method: "POST" }),
    onSuccess: () => { toast.success("Marked as still valid"); refresh(); }, onError: (e) => toast.error(errMsg(e)),
  });
  const del = useMutation({
    mutationFn: (id: string) => api(`/projects/${p.id}/memory/${id}`, { method: "DELETE" }),
    onSuccess: () => { toast.success("Deleted"); refresh(); }, onError: (e) => toast.error(errMsg(e)),
  });
  const canChange = (m: Mem) => canWrite && (isOwner || m.author_id === me?.user.id);

  return (
    <div className="space-y-4">
      <Banner tone="blue">Project memory is shared by this project&apos;s members and is context for the assistant only. It is <b>not</b> a verified experimental record and is never used as a citation. Entries become <b>stale</b> when the experiment or document they came from changes, and stale entries are not used until someone confirms them.</Banner>
      {canWrite && (
        <form className="card flex flex-wrap items-end gap-2 p-4" onSubmit={(e: FormEvent) => { e.preventDefault(); add.mutate(); }}>
          <div className="min-w-[16rem] flex-1"><label className="label" htmlFor="pm-text">Add a note, term or established finding</label>
            <input id="pm-text" className="input" maxLength={1000} value={text} onChange={(e) => setText(e.target.value)} placeholder="e.g. “S1” is the untreated control strain" /></div>
          <div><label className="label" htmlFor="pm-kind">Type</label><select id="pm-kind" className="input" value={kind} onChange={(e) => setKind(e.target.value as typeof kind)}>
            <option value="note">note</option><option value="terminology">terminology</option><option value="finding">finding</option></select></div>
          <button className="btn-primary" disabled={text.trim().length < 2 || add.isPending}>Save</button>
        </form>
      )}
      {q.isLoading && <Spinner />}
      {q.data?.length === 0 && <Empty title="No project memory yet">Add terminology and findings here, or tell the assistant “Remember that …”.</Empty>}
      <div className="space-y-2" data-testid="project-memory">
        {q.data?.map((m) => (
          <div key={m.id} className={`card flex flex-wrap items-start justify-between gap-3 p-3 ${m.stale ? "border-amber-400 bg-amber-50" : ""}`}>
            <div className="min-w-0 flex-1">
              {editing?.id === m.id ? (
                <div className="flex gap-2"><input className="input" value={editing.content} onChange={(e) => setEditing({ id: m.id, content: e.target.value })} />
                  <button className="btn-primary px-3" onClick={() => save.mutate(editing)}>Save</button><button className="btn-secondary px-3" onClick={() => setEditing(null)}>Cancel</button></div>
              ) : <div className="text-sm">{m.content}</div>}
              <div className="mt-1 flex flex-wrap gap-1 text-xs">
                <span className="badge bg-slate-100 text-slate-700">{m.kind}</span>
                {m.origin === "ai_suggested" && <span className="badge bg-purple-100 text-purple-800">AI-suggested · unverified</span>}
                {m.stale && <span className="badge bg-amber-200 text-amber-900">stale: its source changed</span>}
                <span className="text-slate-500">{m.author_name} · {fmtDate(m.created_at)}</span>
              </div>
            </div>
            {canChange(m) && (
              <div className="flex gap-1">
                {m.stale && <button className="btn-secondary px-2 py-1" onClick={() => confirm.mutate(m.id)}><Check size={14} />Still valid</button>}
                <button className="btn-secondary px-2 py-1" aria-label="Edit" onClick={() => setEditing({ id: m.id, content: m.content })}><Pencil size={14} /></button>
                <button className="btn-secondary px-2 py-1 text-red-700" aria-label="Delete" onClick={() => del.mutate(m.id)}><Trash2 size={14} /></button>
              </div>
            )}
          </div>))}
      </div>
    </div>
  );
}
