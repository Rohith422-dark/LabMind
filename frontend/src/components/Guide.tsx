import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { driver, type DriveStep } from "driver.js";
import "driver.js/dist/driver.css";
import { Check, Compass, Play, X } from "lucide-react";
import { api } from "@/api/client";
import type { DemoQuestion } from "@/api/types";
import { useAuth } from "@/context/AuthContext";

interface Task { id: string; label: string; hint?: string; to: string }

const TOURS: Record<string, DriveStep[]> = {
  "/chat": [
    { element: "[data-tour=chat-input]", popover: { title: "Ask in plain language", description: "Answers come only from approved, effective documents." } },
    { element: "[data-tour=citation-chip]", popover: { title: "Citations", description: "Click a numbered chip to open the real source PDF at the cited page with the passage highlighted." } },
  ],
  "/troubleshoot": [
    { element: "[data-tour=ts-sop]", popover: { title: "Pick the SOP", description: "Or let the assistant auto-detect it from the symptom." } },
    { element: "[data-tour=ts-diagnose]", popover: { title: "Diagnosis", description: "Ranked probable causes, each tied to a deviation or a guide citation." } },
  ],
  "/sop-management": [
    { element: "[data-tour=upload-zone]", popover: { title: "Upload a real document", description: "Metadata and steps are auto-filled for you to review." } },
  ],
};

function tasksFor(role: string, qs: DemoQuestion[]): Task[] {
  const ans = qs.filter((q) => q.kind === "answerable");
  const unc = qs.filter((q) => q.kind === "not_covered");
  const ts = qs.find((q) => q.kind === "troubleshoot_narration");
  const enc = encodeURIComponent;
  if (role === "scientist") return [
    { id: "s1", label: "Ask a question a real SOP answers", hint: ans[0]?.question, to: ans[0] ? `/chat?q=${enc(ans[0].question)}` : "/chat" },
    { id: "s2", label: "Click the [1] chip: the source PDF opens at the cited page with the passage highlighted", to: "/chat" },
    { id: "s3", label: "Ask something no document covers, say Yes to the online check, then Request official SOP", hint: unc[0]?.question, to: unc[0] ? `/chat?q=${enc(unc[0].question)}` : "/chat" },
    { id: "s4", label: "Troubleshoot: compare what you did with the SOP", hint: ts?.symptom, to: ts ? `/troubleshoot?symptom=${enc(ts.symptom ?? "")}&narration=${enc(ts.question)}` : "/troubleshoot" },
    { id: "s5", label: "Open Inventory and raise a reagent request", to: "/inventory" },
    { id: "s6", label: "RBAC check: try opening SOP Management (you will be turned away)", to: "/sop-management" },
    { id: "s7", label: "After the Senior Analyst publishes: re-ask the same uncovered question", hint: unc[0]?.question, to: unc[0] ? `/chat?q=${enc(unc[0].question)}` : "/chat" },
  ];
  if (role === "lab_analyst") return [
    { id: "a1", label: "Issue the scientist's request from the earliest-expiry lot", to: "/analyst" },
    { id: "a2", label: "Try issuing an expired lot: it is blocked", to: "/analyst" },
    { id: "a3", label: "Review stock: return, adjust (reason required) or dispose", to: "/analyst" },
  ];
  if (role === "senior_analyst") return [
    { id: "r1", label: "Open Knowledge Gaps and find the scientist's question", to: "/gaps" },
    { id: "r2", label: "Upload a real document: metadata auto-fills, then publish with a change note", to: "/sop-management" },
    { id: "r3", label: "Open the audit log and press Verify integrity", to: "/audit" },
  ];
  return [
    { id: "d1", label: "Review the audit trail (incl. external AI use and denied access) and verify integrity", to: "/audit" },
    { id: "d2", label: "Create a user and change a role", to: "/admin/users" },
  ];
}

export function Guide() {
  const { me } = useAuth();
  const nav = useNavigate();
  const loc = useLocation();
  const [open, setOpen] = useState(false);
  const key = `sla_guide_${me?.user.username}`;
  const [done, setDone] = useState<string[]>([]);
  const qs = useQuery({ queryKey: ["demo-q"], queryFn: () => api<DemoQuestion[]>("/demo/questions"), enabled: !!me });

  useEffect(() => { try { setDone(JSON.parse(localStorage.getItem(key) ?? "[]")); } catch { setDone([]); } }, [key]);
  if (!me) return null;
  const tasks = tasksFor(me.user.role, qs.data ?? []);
  const toggle = (id: string) => {
    const next = done.includes(id) ? done.filter((d) => d !== id) : [...done, id];
    setDone(next); try { localStorage.setItem(key, JSON.stringify(next)); } catch { /* storage unavailable */ }
  };
  const tour = () => {
    const steps = TOURS[loc.pathname];
    if (!steps) return;
    driver({ showProgress: true, steps: steps.filter((s) => !s.element || document.querySelector(s.element as string)) }).drive();
  };

  return (
    <>
      <button onClick={() => setOpen(!open)} data-tour="guide-btn" aria-label="Open guide"
        className="fixed bottom-14 right-5 z-30 flex items-center gap-2 rounded-full bg-brand-700 px-4 py-3 font-semibold text-white shadow-lg hover:bg-brand-900">
        <Compass size={20} />Guide {done.length}/{tasks.length}
      </button>
      {open && (
        <div className="fixed bottom-28 right-5 z-30 w-[22rem] max-w-[calc(100vw-2.5rem)] rounded-lg border border-slate-200 bg-white shadow-2xl">
          <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
            <div className="font-bold">Demo guide · {me.user.role.replace("_", " ")}</div>
            <button onClick={() => setOpen(false)} aria-label="Close guide"><X size={18} /></button>
          </div>
          <ul className="max-h-[55vh] space-y-1 overflow-y-auto p-3">
            {tasks.map((t) => (
              <li key={t.id} className="rounded-md p-2 hover:bg-slate-50">
                <div className="flex items-start gap-2">
                  <button onClick={() => toggle(t.id)} aria-label="Mark done"
                    className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded border ${done.includes(t.id) ? "border-green-600 bg-green-600 text-white" : "border-slate-300"}`}>
                    {done.includes(t.id) && <Check size={14} />}</button>
                  <div className="min-w-0 flex-1 text-sm">
                    <div className={done.includes(t.id) ? "text-slate-400 line-through" : ""}>{t.label}</div>
                    {t.hint && <div className="mt-1 rounded bg-slate-100 px-2 py-1 text-xs text-slate-600">{t.hint}</div>}
                    <button className="mt-1 text-xs font-semibold text-brand-700 underline" onClick={() => { nav(t.to); setOpen(false); }}>Go there</button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
          <div className="border-t border-slate-200 p-3"><button className="btn-secondary w-full" onClick={tour} disabled={!TOURS[loc.pathname]}>
            <Play size={16} />{TOURS[loc.pathname] ? "Tour this page" : "No tour for this page"}</button></div>
        </div>
      )}
    </>
  );
}
