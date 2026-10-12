import { useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import {
  BookOpen, Boxes, ClipboardList, FlaskConical, Gauge, History, LogOut, MessageSquare, PanelLeftClose,
  PanelLeftOpen, ScrollText, ShieldCheck, Users, Wrench, Calculator, Lightbulb, type LucideIcon,
} from "lucide-react";
import { useAuth } from "@/context/AuthContext";

interface NavItem { to: string; label: string; icon: LucideIcon; permission: string }

export const NAV: NavItem[] = [
  { to: "/", label: "Dashboard", icon: Gauge, permission: "self.view" },
  { to: "/chat", label: "Assistant", icon: MessageSquare, permission: "knowledge.use" },
  { to: "/sops", label: "SOP Library", icon: BookOpen, permission: "knowledge.use" },
  { to: "/troubleshoot", label: "Troubleshooting", icon: Wrench, permission: "knowledge.use" },
  { to: "/inventory", label: "Inventory", icon: Boxes, permission: "inventory.view" },
  { to: "/my-requests", label: "My Requests", icon: ClipboardList, permission: "requests.create" },
  { to: "/calculators", label: "Calculators", icon: Calculator, permission: "calculators.use" },
  { to: "/analyst", label: "Analyst Console", icon: FlaskConical, permission: "inventory.manage" },
  { to: "/sop-management", label: "SOP Management", icon: ScrollText, permission: "sop.manage" },
  { to: "/gaps", label: "Knowledge Gaps", icon: Lightbulb, permission: "gaps.view" },
  { to: "/audit", label: "Audit Log", icon: ShieldCheck, permission: "audit.view" },
  { to: "/admin/users", label: "Users", icon: Users, permission: "users.manage" },
];

const ROLE_LABEL: Record<string, string> = {
  scientist: "Scientist", lab_analyst: "Lab Analyst", senior_analyst: "Senior Analyst", admin: "Admin",
};

export function Layout() {
  const { me, can, logout } = useAuth();
  const nav = useNavigate();
  const [collapsed, setCollapsed] = useState(false);
  if (!me) return null;

  return (
    <div className="flex h-screen">
      <aside className={`flex flex-col border-r border-slate-200 bg-white transition-all ${collapsed ? "w-16" : "w-64"}`}>
        <div className="flex h-16 items-center justify-between px-4">
          {!collapsed && <span className="text-lg font-bold text-brand-700">Smart Lab Assistant</span>}
          <button aria-label="Toggle sidebar" className="text-slate-500 hover:text-slate-800" onClick={() => setCollapsed(!collapsed)}>
            {collapsed ? <PanelLeftOpen size={20} /> : <PanelLeftClose size={20} />}
          </button>
        </div>
        <nav className="flex-1 space-y-1 overflow-y-auto px-2">
          {NAV.filter((n) => can(n.permission)).map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} end={to === "/"} title={label}
              className={({ isActive }) => `flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium ${isActive ? "bg-brand-50 text-brand-700" : "text-slate-600 hover:bg-slate-100"}`}>
              <Icon size={20} className="shrink-0" />
              {!collapsed && label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-slate-200 p-3 text-sm">
          {!collapsed && (
            <div className="mb-2">
              <div className="font-semibold">{me.user.full_name}</div>
              <div className="text-slate-500">{ROLE_LABEL[me.user.role]}</div>
            </div>
          )}
          <button className="btn-secondary w-full" onClick={() => nav("/login?switch=1")} title="Switch user">
            <History size={16} />{!collapsed && "Switch user"}
          </button>
          <button className="mt-2 flex w-full items-center justify-center gap-2 text-slate-500 hover:text-slate-800"
            onClick={() => { logout(); nav("/login"); }}>
            <LogOut size={16} />{!collapsed && "Sign out"}
          </button>
        </div>
      </aside>
      <main className="flex min-w-0 flex-1 flex-col overflow-y-auto">
        <div className="flex-1 p-6"><Outlet /></div>
        <footer className="border-t border-slate-200 px-6 py-2 text-xs text-slate-500">Demo build · public documents</footer>
      </main>
    </div>
  );
}
