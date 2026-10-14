import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, LogOut, Trash2, UserPlus } from "lucide-react";
import { toast } from "sonner";
import { api, type Schemas } from "@/api/client";
import { useAuth } from "@/context/AuthContext";
import { Banner, Spinner, StatusBadge, errMsg, fmtDate } from "@/components/ui";
import type { TabProps } from "@/pages/ProjectDetail";

type Member = Schemas["MemberOut"];
type Req = Schemas["AccessRequestOut"];

export default function Access({ project: p, isOwner }: TabProps) {
  const qc = useQueryClient();
  const nav = useNavigate();
  const { me } = useAuth();
  const members = useQuery({ queryKey: ["members", p.id], queryFn: () => api<Member[]>(`/projects/${p.id}/members`) });
  const reqs = useQuery({ queryKey: ["access-reqs", p.id], queryFn: () => api<Req[]>(`/projects/${p.id}/access-requests`), enabled: isOwner });
  const refresh = () => { void qc.invalidateQueries({ queryKey: ["members", p.id] }); void qc.invalidateQueries({ queryKey: ["access-reqs", p.id] }); void qc.invalidateQueries({ queryKey: ["project", p.id] }); };

  const [username, setUsername] = useState("");
  const [role, setRole] = useState<"viewer" | "editor">("viewer");
  const [pw, setPw] = useState("");
  const [decisionRole, setDecisionRole] = useState<Record<string, "viewer" | "editor">>({});

  const add = useMutation({
    mutationFn: () => api(`/projects/${p.id}/members`, { method: "POST", json: { username: username.trim(), role } }),
    onSuccess: () => { toast.success("Collaborator added"); setUsername(""); refresh(); }, onError: (e) => toast.error(errMsg(e)),
  });
  const setRoleM = useMutation({
    mutationFn: (v: { id: string; role: "viewer" | "editor" }) => api(`/projects/${p.id}/members/${v.id}`, { method: "PATCH", json: { role: v.role } }),
    onSuccess: () => { toast.success("Role updated"); refresh(); }, onError: (e) => toast.error(errMsg(e)),
  });
  const remove = useMutation({
    mutationFn: (id: string) => api(`/projects/${p.id}/members/${id}`, { method: "DELETE" }),
    onSuccess: (_, id) => { toast.success("Access revoked"); if (id === me?.user.id) { void qc.invalidateQueries({ queryKey: ["projects"] }); nav("/projects"); } else refresh(); },
    onError: (e) => toast.error(errMsg(e)),
  });
  const decide = useMutation({
    mutationFn: (v: { id: string; approve: boolean }) => api(`/projects/${p.id}/access-requests/${v.id}/decision`, { method: "POST", json: { approve: v.approve, role: decisionRole[v.id] ?? "viewer" } }),
    onSuccess: (_, v) => { toast.success(v.approve ? "Access granted" : "Request declined"); refresh(); }, onError: (e) => toast.error(errMsg(e)),
  });
  const setPassword = useMutation({
    mutationFn: () => api(`/projects/${p.id}/password`, { method: "PUT", json: { password: pw } }),
    onSuccess: () => { toast.success("Password set"); setPw(""); refresh(); }, onError: (e) => toast.error(errMsg(e)),
  });
  const clearPassword = useMutation({
    mutationFn: () => api(`/projects/${p.id}/password`, { method: "DELETE" }),
    onSuccess: () => { toast.success("Password removed: nobody can request access with a password now"); refresh(); }, onError: (e) => toast.error(errMsg(e)),
  });

  return (
    <div className="space-y-6">
      <div className="card p-5">
        <h2 className="mb-3 text-lg font-semibold">Collaborators</h2>
        {members.isLoading && <Spinner />}
        <div className="overflow-x-auto"><table className="w-full text-left text-sm">
          <thead className="text-slate-500"><tr>{["Name", "Username", "Role", "Since", ""].map((h) => <th key={h} className="px-2 py-1 font-semibold">{h}</th>)}</tr></thead>
          <tbody>{members.data?.map((m) => (
            <tr key={m.user_id} className="border-t border-slate-100">
              <td className="px-2 py-2">{m.full_name}</td><td className="px-2 py-2 text-slate-500">{m.username}</td>
              <td className="px-2 py-2">{isOwner && m.role !== "owner" ? (
                <select aria-label={`Role of ${m.full_name}`} className="input w-28 py-1" value={m.role} onChange={(e) => setRoleM.mutate({ id: m.user_id, role: e.target.value as "viewer" | "editor" })}>
                  <option value="viewer">viewer</option><option value="editor">editor</option></select>) : <StatusBadge status={m.role} />}</td>
              <td className="px-2 py-2 text-slate-500">{fmtDate(m.added_at)}</td>
              <td className="px-2 py-2 text-right">
                {isOwner && m.role !== "owner" && <button className="btn-secondary px-2 py-1 text-red-700" onClick={() => { if (window.confirm(`Revoke ${m.full_name}'s access? They lose the project, its chats and memory immediately.`)) remove.mutate(m.user_id); }}><Trash2 size={14} />Revoke</button>}
                {!isOwner && m.user_id === me?.user.id && <button className="btn-secondary px-2 py-1" onClick={() => { if (window.confirm("Leave this project?")) remove.mutate(m.user_id); }}><LogOut size={14} />Leave</button>}
              </td>
            </tr>))}</tbody></table></div>
        {isOwner && (
          <form className="mt-4 flex flex-wrap items-end gap-2 border-t border-slate-100 pt-4" onSubmit={(e: FormEvent) => { e.preventDefault(); add.mutate(); }}>
            <div className="min-w-[12rem] flex-1"><label className="label" htmlFor="m-user">Add collaborator by username</label><input id="m-user" className="input" value={username} onChange={(e) => setUsername(e.target.value)} /></div>
            <div><label className="label" htmlFor="m-role">Role</label><select id="m-role" className="input" value={role} onChange={(e) => setRole(e.target.value as "viewer" | "editor")}><option value="viewer">viewer (read only)</option><option value="editor">editor (add/change records)</option></select></div>
            <button className="btn-primary" disabled={!username.trim() || add.isPending}><UserPlus size={16} />Add</button>
          </form>
        )}
      </div>

      {isOwner && (
        <>
          <div className="card p-5">
            <h2 className="mb-1 text-lg font-semibold">Access requests</h2>
            <p className="mb-3 text-sm text-slate-600">People who know the project password can ask for access. Nobody gets in until you approve them here.</p>
            {reqs.isLoading && <Spinner />}
            {reqs.data?.length === 0 && <div className="text-sm text-slate-500">No pending requests.</div>}
            <div className="space-y-2">{reqs.data?.map((r) => (
              <div key={r.id} className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-slate-200 p-3 text-sm">
                <div><b>{r.full_name}</b> <span className="text-slate-500">({r.username}) · {fmtDate(r.created_at)}</span>{r.message && <div className="text-slate-600">“{r.message}”</div>}</div>
                <div className="flex items-center gap-2">
                  <select aria-label="Role to grant" className="input w-28 py-1" value={decisionRole[r.id] ?? "viewer"} onChange={(e) => setDecisionRole({ ...decisionRole, [r.id]: e.target.value as "viewer" | "editor" })}><option value="viewer">viewer</option><option value="editor">editor</option></select>
                  <button className="btn-primary px-3 py-1" disabled={decide.isPending} onClick={() => decide.mutate({ id: r.id, approve: true })}>Approve</button>
                  <button className="btn-secondary px-3 py-1" disabled={decide.isPending} onClick={() => decide.mutate({ id: r.id, approve: false })}>Decline</button>
                </div>
              </div>))}</div>
          </div>

          <div className="card p-5">
            <h2 className="mb-1 flex items-center gap-2 text-lg font-semibold"><KeyRound size={18} />Access password</h2>
            <p className="mb-3 text-sm text-slate-600">{p.has_password ? "A password is set." : "No password is set, so nobody can request access by ID."} It is stored only as a salted hash and is never shown again.</p>
            <form className="flex flex-wrap items-end gap-2" onSubmit={(e: FormEvent) => { e.preventDefault(); setPassword.mutate(); }}>
              <div className="min-w-[14rem]"><label className="label" htmlFor="pw-new">{p.has_password ? "Replace password" : "Set password"} (min. 8 characters)</label>
                <input id="pw-new" className="input" type="password" autoComplete="new-password" minLength={8} maxLength={128} value={pw} onChange={(e) => setPw(e.target.value)} /></div>
              <button className="btn-primary" disabled={pw.length < 8 || setPassword.isPending}>Save password</button>
              {p.has_password && <button type="button" className="btn-secondary" onClick={() => clearPassword.mutate()}>Remove password</button>}
            </form>
            <div className="mt-3"><Banner tone="blue">Anyone with the project ID and password can only send you a request. You decide who is let in and with which role.</Banner></div>
          </div>
        </>
      )}
    </div>
  );
}
