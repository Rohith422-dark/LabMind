import { useEffect, useState, type FormEvent } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { FlaskConical, ShieldCheck, Beaker, UserCog } from "lucide-react";
import { toast } from "sonner";
import { api, type Schemas } from "@/api/client";
import { useAuth } from "@/context/AuthContext";

const ROLE_INFO: Record<string, { label: string; blurb: string; icon: typeof Beaker }> = {
  scientist: { label: "Scientist", blurb: "Ask questions, troubleshoot, request reagents", icon: Beaker },
  lab_analyst: { label: "Lab Analyst", blurb: "Issue reagents, manage stock and requests", icon: FlaskConical },
  senior_analyst: { label: "Senior Analyst", blurb: "Publish SOPs, close knowledge gaps, audit", icon: ShieldCheck },
  admin: { label: "Admin", blurb: "Manage users and review the audit log", icon: UserCog },
};

export default function Login() {
  const { me, login, demoLogin, logout } = useAuth();
  const nav = useNavigate();
  const [params] = useSearchParams();
  const switching = params.get("switch") === "1";
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const cards = useQuery({ queryKey: ["demo-users"], queryFn: () => api<Schemas["DemoUserCard"][]>("/auth/demo-users") });
  const demoEnabled = useQuery({
    queryKey: ["health"], queryFn: () => api<{ demo_cards: boolean }>("/health"),
  });

  useEffect(() => { if (switching && me) logout(); }, [switching]); // eslint-disable-line react-hooks/exhaustive-deps

  if (me && !switching) return <Navigate to="/" replace />;

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    try { await fn(); nav("/"); } catch (e) { toast.error(e instanceof Error ? e.message : "Login failed"); } finally { setBusy(false); }
  };
  const submit = (e: FormEvent) => { e.preventDefault(); void run(() => login(username, password)); };

  const order = ["scientist", "lab_analyst", "senior_analyst", "admin"];
  const sorted = [...(cards.data ?? [])].sort((a, b) => order.indexOf(a.role) - order.indexOf(b.role));

  return (
    <div className="mx-auto flex min-h-screen max-w-5xl flex-col justify-center px-6 py-10">
      <h1 className="text-4xl font-bold text-brand-900">Smart Lab Assistant</h1>
      <p className="mt-2 text-lg text-slate-600">Approved lab documents are the single source of truth. The scientist makes the final decision.</p>

      {demoEnabled.data?.demo_cards && (
        <section className="mt-8">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">Demo accounts — one click</h2>
          {sorted.length === 0 ? (
            <div className="card p-6 text-slate-500">No accounts yet. Run <code>npm run seed</code>.</div>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {sorted.map((u) => {
                const info = ROLE_INFO[u.role]; const Icon = info.icon;
                return (
                  <button key={u.username} disabled={busy} data-tour={`login-${u.role}`}
                    onClick={() => run(() => demoLogin(u.username))}
                    className="card p-5 text-left transition hover:border-brand-500 hover:shadow-md">
                    <Icon className="mb-3 text-brand-600" size={28} />
                    <div className="font-semibold">{u.full_name}</div>
                    <div className="text-sm font-medium text-brand-700">{info.label}</div>
                    <div className="mt-1 text-sm text-slate-500">{info.blurb}</div>
                  </button>
                );
              })}
            </div>
          )}
        </section>
      )}

      <form onSubmit={submit} className="card mt-8 max-w-md space-y-4 p-6">
        <h2 className="font-semibold">Sign in</h2>
        <div><label className="label" htmlFor="u">Username</label>
          <input id="u" className="input" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" /></div>
        <div><label className="label" htmlFor="p">Password</label>
          <input id="p" type="password" className="input" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" /></div>
        <button className="btn-primary w-full" disabled={busy || !username || !password}>Sign in</button>
      </form>
    </div>
  );
}
