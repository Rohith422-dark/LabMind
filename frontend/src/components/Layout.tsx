import { useState, type FormEvent } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  BookOpen, Boxes, Calculator, ChevronRight, ClipboardList, FlaskConical, FolderKanban, Gauge, Lightbulb, LogOut, MessageSquare,
  PanelLeftClose, PanelLeftOpen, Repeat, Search, ShieldCheck, Users, Wrench, type LucideIcon,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useAuth } from "@/context/AuthContext";
import { NotificationBell } from "@/components/NotificationBell";

interface NavItem { to: string; label: string; icon: LucideIcon; permission: string; group: string; hideFor?: string[] }

export const NAV: NavItem[] = [
  { to: "/", label: "Dashboard", icon: Gauge, permission: "self.view", group: "Workspace" },
  { to: "/projects", label: "Projects", icon: FolderKanban, permission: "projects.use", group: "Workspace", hideFor: ["lab_analyst"] },
  { to: "/chat", label: "AI Assistant", icon: MessageSquare, permission: "knowledge.use", group: "Workspace" },
  { to: "/sops", label: "SOP Library", icon: BookOpen, permission: "knowledge.use", group: "Knowledge", hideFor: ["lab_analyst"] },
  { to: "/troubleshoot", label: "Troubleshooting", icon: Wrench, permission: "knowledge.use", group: "Knowledge", hideFor: ["lab_analyst"] },
  { to: "/gaps", label: "Knowledge Gaps", icon: Lightbulb, permission: "gaps.view", group: "Knowledge" },
  { to: "/inventory", label: "Inventory", icon: Boxes, permission: "inventory.view", group: "Laboratory" },
  { to: "/my-requests", label: "My Requests", icon: ClipboardList, permission: "requests.create", group: "Laboratory", hideFor: ["lab_analyst"] },
  { to: "/analyst", label: "Lab Console", icon: FlaskConical, permission: "inventory.manage", group: "Laboratory" },
  { to: "/calculators", label: "Calculators", icon: Calculator, permission: "calculators.use", group: "Laboratory" },
  { to: "/audit", label: "Audit Log", icon: ShieldCheck, permission: "audit.view", group: "Administration" },
  { to: "/admin/users", label: "Users", icon: Users, permission: "users.manage", group: "Administration" },
];

const ROLE_LABEL: Record<string, string> = {
  scientist: "Scientist", lab_analyst: "Lab Analyst", senior_analyst: "Senior Analyst", admin: "Admin",
};
const initials = (n: string) => n.replace(/^(Dr|Prof|Mr|Ms|Mrs)\.?\s+/i, "").split(/\s+/).map((p) => p[0]).slice(0, 2).join("").toUpperCase();

export function Layout() {
  const { me, can, logout } = useAuth();
  const nav = useNavigate();
  const loc = useLocation();
  const [collapsed, setCollapsed] = useState(() => typeof window !== "undefined" && window.innerWidth < 1024);
  const [search, setSearch] = useState("");
  const health = useQuery({ queryKey: ["health"], queryFn: () => api<{ llm_mock: boolean; ai_configured: boolean }>("/health") });
  if (!me) return null;

  const items = NAV.filter((n) => can(n.permission) && !n.hideFor?.includes(me.user.role));
  const groups = [...new Set(items.map((i) => i.group))];
  const current = items.filter((i) => (i.to === "/" ? loc.pathname === "/" : loc.pathname.startsWith(i.to))).sort((a, b) => b.to.length - a.to.length)[0];
  const submit = (e: FormEvent) => { e.preventDefault(); const q = search.trim(); if (q) { nav(`/chat?q=${encodeURIComponent(q)}`); setSearch(""); } };

  return (
    <div className="flex h-screen bg-slate-50">
      <aside className={`flex shrink-0 flex-col border-r border-slate-200 bg-white transition-[width] duration-200 ease-out ${collapsed ? "w-[72px]" : "w-[248px]"}`} aria-label="Primary">
        <div className={`flex h-16 items-center border-b border-slate-200 ${collapsed ? "justify-center" : "justify-between px-4"}`}>
          {!collapsed && <div className="flex items-center gap-2"><span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-600 text-white"><FlaskConical size={18} /></span>
            <span className="text-[15px] font-semibold tracking-tight text-slate-900">LabMind</span></div>}
          <button aria-label="Toggle sidebar" title={collapsed ? "Expand sidebar" : "Collapse sidebar"} className="icon-btn" onClick={() => setCollapsed(!collapsed)}>
            {collapsed ? <PanelLeftOpen size={19} /> : <PanelLeftClose size={19} />}
          </button>
        </div>
        <nav className="flex-1 space-y-4 overflow-y-auto px-3 py-4">
          {groups.map((g) => (
            <div key={g}>
              {!collapsed ? <div className="mb-1 px-3 text-[11px] font-medium uppercase tracking-wide text-slate-500">{g}</div> : <div className="mx-3 mb-2 border-t border-slate-200 first:hidden" />}
              <div className="space-y-0.5">
                {items.filter((i) => i.group === g).map(({ to, label, icon: Icon }) => (
                  <NavLink key={to} to={to} end={to === "/"} title={collapsed ? label : undefined} aria-label={label}
                    className={({ isActive }) => `flex h-10 items-center gap-3 rounded-lg px-3 text-sm font-medium transition-colors duration-150 ${collapsed ? "justify-center px-0" : ""} ${isActive ? "bg-brand-100 text-brand-600" : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"}`}>
                    <Icon size={19} className="shrink-0" strokeWidth={1.75} />
                    {!collapsed && <span className="truncate">{label}</span>}
                  </NavLink>
                ))}
              </div>
            </div>
          ))}
        </nav>
        <div className="border-t border-slate-200 p-3">
          <div className={`flex items-center gap-3 ${collapsed ? "justify-center" : "px-1"}`}>
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-brand-100 text-xs font-semibold text-brand-600" title={collapsed ? me.user.full_name : undefined}>{initials(me.user.full_name)}</span>
            {!collapsed && <div className="min-w-0"><div className="truncate text-sm font-medium text-slate-900">{me.user.full_name}</div><div className="truncate text-xs text-slate-600">{ROLE_LABEL[me.user.role]}</div></div>}
          </div>
          <div className={`mt-3 flex ${collapsed ? "flex-col items-center gap-1" : "gap-2"}`}>
            <button className={collapsed ? "icon-btn" : "btn-secondary flex-1 px-2"} onClick={() => nav("/login?switch=1")} title="Switch user" aria-label="Switch user"><Repeat size={16} />{!collapsed && "Switch"}</button>
            <button className={collapsed ? "icon-btn" : "btn-secondary flex-1 px-2"} onClick={() => { logout(); nav("/login"); }} title="Sign out" aria-label="Sign out"><LogOut size={16} />{!collapsed && "Sign out"}</button>
          </div>
        </div>
      </aside>
      <main className="flex min-w-0 flex-1 flex-col overflow-y-auto">
        {health.data?.llm_mock && <div className="bg-red-600 px-4 py-1 text-center text-xs font-semibold tracking-widest text-white">MOCK AI — DEVELOPMENT ONLY · answers are not from a real model</div>}
        {health.data && !health.data.ai_configured && <div className="bg-amber-100 px-4 py-1 text-center text-sm text-amber-800">AI not configured — add GEMINI_API_KEY to backend/.env. Non-AI pages still work.</div>}
        <header className="sticky top-0 z-20 flex h-16 shrink-0 items-center gap-4 border-b border-slate-200 bg-white px-4 md:px-6">
          <div className="hidden min-w-0 items-center gap-1.5 text-sm text-slate-600 md:flex">
            <span className="whitespace-nowrap">LabMind</span><ChevronRight size={14} className="text-slate-400" /><span className="whitespace-nowrap font-medium text-slate-900">{current?.label ?? "Page"}</span>
          </div>
          <form onSubmit={submit} className="relative mx-auto w-full max-w-md" role="search">
            <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input aria-label="Ask the assistant" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Ask the AI assistant…"
              className="h-10 w-full rounded-lg border border-transparent bg-slate-100 pl-9 pr-3 text-sm placeholder:text-slate-500 transition-colors focus:border-brand-600 focus:bg-white focus:outline-none focus:ring-2 focus:ring-brand-600/20" />
          </form>
          <div className="flex items-center gap-1"><NotificationBell />
            <span className="ml-1 flex h-9 w-9 items-center justify-center rounded-full border border-slate-200 bg-slate-100 text-xs font-semibold text-slate-800" aria-hidden="true">{initials(me.user.full_name)}</span></div>
        </header>
        <div className="flex-1 p-4 md:p-6"><Outlet /></div>
        <footer className="border-t border-slate-200 px-6 py-2 text-xs text-slate-500">Demo build · public documents</footer>
      </main>
    </div>
  );
}
