import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Archive, Copy, Pencil, RotateCcw, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api/client";
import { Banner, Modal, errMsg, fmtDate } from "@/components/ui";
import type { Project, TabProps } from "@/pages/ProjectDetail";

export default function Overview({ project: p, isOwner }: TabProps) {
  const qc = useQueryClient();
  const nav = useNavigate();
  const [editing, setEditing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const refresh = () => { void qc.invalidateQueries({ queryKey: ["project", p.id] }); void qc.invalidateQueries({ queryKey: ["projects"] }); };
  const archive = useMutation({
    mutationFn: () => api<Project>(`/projects/${p.id}/${p.archived ? "restore" : "archive"}`, { method: "POST" }),
    onSuccess: () => { toast.success(p.archived ? "Project restored" : "Project archived (read-only)"); refresh(); },
    onError: (e) => toast.error(errMsg(e)),
  });
  const copy = async () => {
    try { await navigator.clipboard.writeText(p.id); toast.success("Project ID copied"); } catch { toast.error("Could not copy; select the ID manually"); }
  };

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <div className="card space-y-3 p-5 lg:col-span-2">
        <div className="flex items-center justify-between"><h2 className="text-lg font-semibold">About this project</h2>
          {isOwner && <button className="btn-secondary" onClick={() => setEditing(true)}><Pencil size={14} />Edit</button>}</div>
        <Field label="Description" value={p.description} />
        <Field label="Research objectives" value={p.objectives} />
        <Field label="Domain" value={p.domain} />
        <div><div className="label">Tags</div><div className="flex flex-wrap gap-1">{p.tags.length ? p.tags.map((t) => <span key={t} className="badge bg-brand-50 text-brand-700">{t}</span>) : <span className="text-sm text-slate-500">none</span>}</div></div>
      </div>
      <div className="space-y-4">
        <div className="card space-y-2 p-5 text-sm">
          <h2 className="text-lg font-semibold">Details</h2>
          <div><span className="text-slate-500">Owner:</span> {p.owner_name}</div>
          <div><span className="text-slate-500">Created:</span> {fmtDate(p.created_at)}</div>
          <div><span className="text-slate-500">Experiments:</span> {p.experiments} · <span className="text-slate-500">Documents:</span> {p.documents} · <span className="text-slate-500">Members:</span> {p.members}</div>
          <div><span className="text-slate-500">Access password:</span> {p.has_password ? "set" : "not set"}</div>
          {isOwner && <div className="pt-1"><div className="text-slate-500">Project ID (share with the password to let someone request access)</div>
            <div className="mt-1 flex items-center gap-2"><code className="break-all rounded bg-slate-100 px-2 py-1 text-xs">{p.id}</code>
              <button className="btn-secondary px-2 py-1" aria-label="Copy project ID" onClick={copy}><Copy size={14} /></button></div></div>}
        </div>
        {isOwner && (
          <div className="card space-y-2 p-5">
            <h2 className="text-lg font-semibold">Retention</h2>
            <button className="btn-secondary w-full" onClick={() => archive.mutate()} disabled={archive.isPending}>
              {p.archived ? <><RotateCcw size={14} />Restore project</> : <><Archive size={14} />Archive (read-only)</>}</button>
            <button className="btn-danger w-full" onClick={() => setDeleting(true)}><Trash2 size={14} />Delete permanently…</button>
            <p className="text-xs text-slate-500">Deleting removes experiments and their history, documents, search index, conversations and project memory for everyone. The audit log keeps a record that it happened.</p>
          </div>
        )}
      </div>
      {editing && <Edit p={p} onClose={() => setEditing(false)} onDone={() => { setEditing(false); refresh(); }} />}
      {deleting && <Delete p={p} onClose={() => setDeleting(false)} onDone={() => { void qc.invalidateQueries({ queryKey: ["projects"] }); nav("/projects"); }} />}
    </div>
  );
}

function Field({ label, value }: { label: string; value?: string | null }) {
  return <div><div className="label">{label}</div><div className="whitespace-pre-wrap text-sm text-slate-800">{value || <span className="text-slate-500">not provided</span>}</div></div>;
}

function Edit({ p, onClose, onDone }: { p: Project; onClose: () => void; onDone: () => void }) {
  const [f, setF] = useState({ name: p.name, description: p.description ?? "", objectives: p.objectives ?? "", domain: p.domain ?? "", tags: p.tags.join(", ") });
  const m = useMutation({
    mutationFn: () => api(`/projects/${p.id}`, { method: "PATCH", json: { name: f.name, description: f.description || null, objectives: f.objectives || null,
      domain: f.domain || null, tags: f.tags.split(",").map((t) => t.trim()).filter(Boolean) } }),
    onSuccess: () => { toast.success("Saved"); onDone(); }, onError: (e) => toast.error(errMsg(e)),
  });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  return (
    <Modal title="Edit project" onClose={onClose}>
      <form className="space-y-3" onSubmit={(e: FormEvent) => { e.preventDefault(); m.mutate(); }}>
        <div><label className="label" htmlFor="e-name">Name</label><input id="e-name" className="input" required minLength={2} value={f.name} onChange={set("name")} /></div>
        <div><label className="label" htmlFor="e-desc">Description</label><textarea id="e-desc" className="input" rows={3} value={f.description} onChange={set("description")} /></div>
        <div><label className="label" htmlFor="e-obj">Objectives</label><textarea id="e-obj" className="input" rows={3} value={f.objectives} onChange={set("objectives")} /></div>
        <div className="grid grid-cols-2 gap-3">
          <div><label className="label" htmlFor="e-dom">Domain</label><input id="e-dom" className="input" value={f.domain} onChange={set("domain")} /></div>
          <div><label className="label" htmlFor="e-tags">Tags</label><input id="e-tags" className="input" value={f.tags} onChange={set("tags")} /></div>
        </div>
        <div className="flex justify-end gap-2"><button type="button" className="btn-secondary" onClick={onClose}>Cancel</button><button className="btn-primary" disabled={m.isPending}>Save</button></div>
      </form>
    </Modal>
  );
}

function Delete({ p, onClose, onDone }: { p: Project; onClose: () => void; onDone: () => void }) {
  const [typed, setTyped] = useState("");
  const m = useMutation({
    mutationFn: () => api(`/projects/${p.id}?confirm_name=${encodeURIComponent(typed)}`, { method: "DELETE" }),
    onSuccess: () => { toast.success("Project deleted"); onDone(); }, onError: (e) => toast.error(errMsg(e)),
  });
  return (
    <Modal title="Delete project permanently" onClose={onClose}>
      <div className="space-y-3">
        <Banner tone="red">This cannot be undone. Everything in “{p.name}” is removed for all members.</Banner>
        <div><label className="label" htmlFor="d-name">Type the project name to confirm</label><input id="d-name" className="input" value={typed} onChange={(e) => setTyped(e.target.value)} /></div>
        <div className="flex justify-end gap-2"><button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn-danger" disabled={typed !== p.name || m.isPending} onClick={() => m.mutate()}>Delete forever</button></div>
      </div>
    </Modal>
  );
}
