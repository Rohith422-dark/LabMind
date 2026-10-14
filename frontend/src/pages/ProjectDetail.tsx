import { Link, NavLink, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { api, ApiError, type Schemas } from "@/api/client";
import { Banner, Spinner, StatusBadge, errMsg } from "@/components/ui";
import Overview from "@/pages/project/Overview";
import Experiments from "@/pages/project/Experiments";
import Documents from "@/pages/project/Documents";
import Assistant from "@/pages/project/Assistant";
import ProjectMemory from "@/pages/project/ProjectMemory";
import Access from "@/pages/project/Access";

export type Project = Schemas["ProjectOut"];
export interface TabProps { project: Project; canWrite: boolean; isOwner: boolean }

const TABS = [
  ["overview", "Overview"], ["experiments", "Experiments"], ["documents", "Documentation"],
  ["assistant", "AI assistant"], ["memory", "Memory"], ["access", "Access"],
] as const;

export default function ProjectDetail() {
  const { id = "", tab = "overview" } = useParams();
  const q = useQuery({ queryKey: ["project", id], queryFn: () => api<Project>(`/projects/${id}`), retry: false });

  if (q.isLoading) return <Spinner label="Loading project…" />;
  if (q.isError) {
    const notFound = q.error instanceof ApiError && q.error.status === 404;
    return (
      <div className="space-y-3">
        <Link to="/projects" className="inline-flex items-center gap-1 text-sm text-brand-700"><ArrowLeft size={14} />All projects</Link>
        <Banner tone="red">{notFound ? "This project does not exist, or you do not have access to it. If a colleague gave you its ID and password, use “Request access” on the Projects page." : errMsg(q.error)}</Banner>
      </div>
    );
  }
  const p = q.data!;
  const isOwner = p.role === "owner";
  const canWrite = (p.role === "owner" || p.role === "editor") && !p.archived;
  const props: TabProps = { project: p, canWrite, isOwner };

  return (
    <div>
      <Link to="/projects" className="mb-2 inline-flex items-center gap-1 text-sm text-brand-700"><ArrowLeft size={14} />All projects</Link>
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <h1 className="text-[26px] font-semibold leading-tight">{p.name}</h1><StatusBadge status={p.role} />
        {p.pending_access_requests > 0 && isOwner && <NavLink to={`/projects/${id}/access`} className="badge bg-orange-100 text-orange-800">{p.pending_access_requests} access request(s) waiting</NavLink>}
      </div>
      {p.archived && <div className="mb-3"><Banner tone="amber">This project is archived and read-only{isOwner ? ". Restore it from the Overview tab to edit again." : "."}</Banner></div>}
      {p.role === "viewer" && <div className="mb-3"><Banner tone="blue">You have view-only access. Ask the owner for the editor role to add or change records.</Banner></div>}
      <nav className="mb-5 flex gap-1 overflow-x-auto border-b border-slate-200" aria-label="Project sections">
        {TABS.map(([key, label]) => (
          <NavLink key={key} to={`/projects/${id}/${key}`} className={() =>
            `whitespace-nowrap border-b-2 px-4 py-2 text-sm font-medium ${tab === key ? "border-brand-600 text-brand-700" : "border-transparent text-slate-600 hover:text-slate-900"}`}>{label}</NavLink>
        ))}
      </nav>
      {tab === "overview" && <Overview {...props} />}
      {tab === "experiments" && <Experiments {...props} />}
      {tab === "documents" && <Documents {...props} />}
      {tab === "assistant" && <Assistant {...props} />}
      {tab === "memory" && <ProjectMemory {...props} />}
      {tab === "access" && <Access {...props} />}
    </div>
  );
}
