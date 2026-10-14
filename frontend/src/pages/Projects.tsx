import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FlaskConical, KeyRound, Plus, Archive } from "lucide-react";
import { toast } from "sonner";
import { api, type Schemas } from "@/api/client";
import { Banner, Empty, Modal, Spinner, StatusBadge, errMsg, fmtDate } from "@/components/ui";

type Project = Schemas["ProjectOut"];
type AccessReq = Schemas["AccessRequestOut"];

export default function Projects() {
  const [creating, setCreating] = useState(false);
  const [joining, setJoining] = useState(false);
  const [archived, setArchived] = useState(false);
  const q = useQuery({ queryKey: ["projects", archived], queryFn: () => api<Project[]>(`/projects?include_archived=${archived}`) });
  const mine = useQuery({ queryKey: ["my-access-requests"], queryFn: () => api<AccessReq[]>("/projects/access-requests/mine") });

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-[26px] font-semibold leading-tight">Research projects</h1>
          <p className="text-sm text-slate-600">Each project is a private workspace: experiments, documents, an evidence-grounded assistant and its own memory.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <label className="flex items-center gap-2 text-sm text-slate-600"><input type="checkbox" checked={archived} onChange={(e) => setArchived(e.target.checked)} />Show archived</label>
          <button className="btn-secondary" onClick={() => setJoining(true)}><KeyRound size={16} />Request access</button>
          <button className="btn-primary" onClick={() => setCreating(true)}><Plus size={16} />New project</button>
        </div>
      </div>

      {q.isLoading && <Spinner label="Loading projects…" />}
      {q.isError && <Banner tone="red">{errMsg(q.error)}</Banner>}
      {q.data?.length === 0 && <Empty title="No projects yet">Create one, or ask a colleague for access with the project ID and password.</Empty>}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3" data-testid="project-list">
        {q.data?.map((p) => (
          <Link key={p.id} to={`/projects/${p.id}`} className="card block p-4 transition hover:border-brand-500">
            <div className="flex items-start justify-between gap-2">
              <div className="flex items-center gap-2 font-semibold"><FlaskConical size={18} className="text-brand-600" />{p.name}</div>
              <StatusBadge status={p.role} />
            </div>
            {p.description && <p className="mt-2 line-clamp-2 text-sm text-slate-600">{p.description}</p>}
            <div className="mt-3 flex flex-wrap gap-1">
              {p.domain && <span className="badge bg-slate-100 text-slate-700">{p.domain}</span>}
              {p.tags.map((t) => <span key={t} className="badge bg-brand-50 text-brand-700">{t}</span>)}
              {p.archived && <span className="badge bg-slate-200 text-slate-700"><Archive size={12} className="mr-1" />archived</span>}
              {p.pending_access_requests > 0 && <span className="badge bg-orange-100 text-orange-800">{p.pending_access_requests} access request(s)</span>}
            </div>
            <div className="mt-3 text-xs text-slate-500">{p.experiments} experiments · {p.documents} documents · {p.members} member(s) · owner {p.owner_name}</div>
          </Link>
        ))}
      </div>

      {!!mine.data?.length && (
        <div className="mt-8">
          <h2 className="mb-2 text-lg font-semibold">My access requests</h2>
          <div className="card divide-y divide-slate-100">
            {mine.data.map((r) => (
              <div key={r.id} className="flex items-center justify-between gap-3 px-4 py-2 text-sm">
                <span>{r.project_name} <span className="text-slate-500">· {fmtDate(r.created_at)}</span></span>
                <span><StatusBadge status={r.status} />{r.role_granted && <span className="ml-2 text-slate-500">as {r.role_granted}</span>}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {creating && <CreateProject onClose={() => setCreating(false)} />}
      {joining && <RequestAccess onClose={() => setJoining(false)} />}
    </div>
  );
}

function CreateProject({ onClose }: { onClose: () => void }) {
  const nav = useNavigate();
  const qc = useQueryClient();
  const [f, setF] = useState({ name: "", description: "", objectives: "", domain: "", tags: "", password: "" });
  const m = useMutation({
    mutationFn: () => api<Project>("/projects", { method: "POST", json: {
      name: f.name, description: f.description || null, objectives: f.objectives || null, domain: f.domain || null,
      tags: f.tags.split(",").map((t) => t.trim()).filter(Boolean), password: f.password || null } }),
    onSuccess: (p) => { toast.success("Project created"); void qc.invalidateQueries({ queryKey: ["projects"] }); nav(`/projects/${p.id}`); },
    onError: (e) => toast.error(errMsg(e)),
  });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const submit = (e: FormEvent) => { e.preventDefault(); m.mutate(); };
  return (
    <Modal title="New project" onClose={onClose}>
      <form onSubmit={submit} className="space-y-3">
        <div><label className="label" htmlFor="p-name">Project name</label><input id="p-name" className="input" required minLength={2} maxLength={160} value={f.name} onChange={set("name")} /></div>
        <div><label className="label" htmlFor="p-desc">Description</label><textarea id="p-desc" className="input" rows={2} value={f.description} onChange={set("description")} /></div>
        <div><label className="label" htmlFor="p-obj">Research objectives</label><textarea id="p-obj" className="input" rows={2} value={f.objectives} onChange={set("objectives")} /></div>
        <div className="grid grid-cols-2 gap-3">
          <div><label className="label" htmlFor="p-dom">Domain</label><input id="p-dom" className="input" placeholder="e.g. analytical chemistry" value={f.domain} onChange={set("domain")} /></div>
          <div><label className="label" htmlFor="p-tags">Tags (comma separated)</label><input id="p-tags" className="input" value={f.tags} onChange={set("tags")} /></div>
        </div>
        <div>
          <label className="label" htmlFor="p-pw">Access password (optional)</label>
          <input id="p-pw" className="input" type="password" autoComplete="new-password" minLength={8} maxLength={128} value={f.password} onChange={set("password")} />
          <p className="mt-1 text-xs text-slate-500">Lets colleagues who know it ask you for access. It never grants access by itself; you approve each person and choose their role.</p>
        </div>
        <div className="flex justify-end gap-2"><button type="button" className="btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn-primary" disabled={m.isPending || f.name.trim().length < 2}>{m.isPending ? "Creating…" : "Create project"}</button></div>
      </form>
    </Modal>
  );
}

function RequestAccess({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const [id, setId] = useState("");
  const [pw, setPw] = useState("");
  const [msg, setMsg] = useState("");
  const [done, setDone] = useState(false);
  const m = useMutation({
    mutationFn: () => api(`/projects/${id.trim()}/access-requests`, { method: "POST", json: { password: pw, message: msg || null } }),
    onSuccess: () => { setDone(true); void qc.invalidateQueries({ queryKey: ["my-access-requests"] }); },
    onError: (e) => toast.error(errMsg(e)),
  });
  return (
    <Modal title="Request access to a project" onClose={onClose}>
      {done ? (
        <div className="space-y-3">
          <Banner tone="green">Request sent. You do not have access yet: the project owner must approve it and choose your role.</Banner>
          <div className="flex justify-end"><button className="btn-primary" onClick={onClose}>Close</button></div>
        </div>
      ) : (
        <form onSubmit={(e) => { e.preventDefault(); m.mutate(); }} className="space-y-3">
          <div><label className="label" htmlFor="j-id">Project ID</label><input id="j-id" className="input font-mono" required value={id} onChange={(e) => setId(e.target.value)} /></div>
          <div><label className="label" htmlFor="j-pw">Project password</label><input id="j-pw" className="input" type="password" autoComplete="off" required value={pw} onChange={(e) => setPw(e.target.value)} /></div>
          <div><label className="label" htmlFor="j-msg">Message to the owner (optional)</label><input id="j-msg" className="input" maxLength={500} value={msg} onChange={(e) => setMsg(e.target.value)} /></div>
          <div className="flex justify-end gap-2"><button type="button" className="btn-secondary" onClick={onClose}>Cancel</button>
            <button className="btn-primary" disabled={m.isPending || !id.trim() || !pw}>{m.isPending ? "Sending…" : "Send request"}</button></div>
        </form>
      )}
    </Modal>
  );
}
