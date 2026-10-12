import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, type Schemas } from "@/api/client";
import { useAuth } from "@/context/AuthContext";

type Role = Schemas["UserOut"]["role"];
const ROLES: Role[] = ["scientist", "lab_analyst", "senior_analyst", "admin"];
const blank = { username: "", password: "", full_name: "", role: "scientist" as Role, department: "" };

export default function AdminUsers() {
  const qc = useQueryClient();
  const { me } = useAuth();
  const [form, setForm] = useState(blank);
  const users = useQuery({ queryKey: ["users"], queryFn: () => api<Schemas["UserOut"][]>("/users") });
  const onErr = (e: Error) => toast.error(e.message);

  const create = useMutation({
    mutationFn: () => api("/users", { method: "POST", json: { ...form, department: form.department || null } }),
    onSuccess: () => { toast.success("User created"); setForm(blank); void qc.invalidateQueries({ queryKey: ["users"] }); },
    onError: onErr,
  });
  const setRole = useMutation({
    mutationFn: (v: { id: string; role: Role }) => api(`/users/${v.id}/role`, { method: "PATCH", json: { role: v.role } }),
    onSuccess: () => { toast.success("Role updated"); void qc.invalidateQueries({ queryKey: ["users"] }); },
    onError: onErr,
  });
  const submit = (e: FormEvent) => { e.preventDefault(); create.mutate(); };
  const set = (k: keyof typeof blank) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });

  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <div className="lg:col-span-2">
        <h1 className="mb-4 text-2xl font-bold">Users</h1>
        <div className="card overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-50 text-slate-600"><tr>
              {["Name", "Username", "Department", "Role"].map((h) => <th key={h} className="px-3 py-2 font-semibold">{h}</th>)}
            </tr></thead>
            <tbody>
              {users.data?.map((u) => (
                <tr key={u.id} className="border-t border-slate-100">
                  <td className="px-3 py-2 font-medium">{u.full_name}</td>
                  <td className="px-3 py-2">{u.username}</td>
                  <td className="px-3 py-2">{u.department}</td>
                  <td className="px-3 py-2">
                    <select className="input py-1" value={u.role} disabled={u.id === me?.user.id}
                      onChange={(e) => setRole.mutate({ id: u.id, role: e.target.value as Role })}>
                      {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <form onSubmit={submit} className="card space-y-3 self-start p-5">
        <h2 className="font-semibold">Create user</h2>
        <div><label className="label">Full name</label><input className="input" value={form.full_name} onChange={set("full_name")} required /></div>
        <div><label className="label">Username</label><input className="input" value={form.username} onChange={set("username")} required /></div>
        <div><label className="label">Password (min 8)</label><input type="password" minLength={8} className="input" value={form.password} onChange={set("password")} required /></div>
        <div><label className="label">Department</label><input className="input" value={form.department} onChange={set("department")} /></div>
        <div><label className="label">Role</label>
          <select className="input" value={form.role} onChange={set("role")}>{ROLES.map((r) => <option key={r}>{r}</option>)}</select></div>
        <button className="btn-primary w-full" disabled={create.isPending}>Create</button>
      </form>
    </div>
  );
}
