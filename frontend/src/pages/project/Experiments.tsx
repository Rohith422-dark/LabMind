import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { History, Microscope, Plus, Scale, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api, type Schemas } from "@/api/client";
import { Banner, Empty, Modal, Pager, Spinner, StatusBadge, errMsg, fmtDate } from "@/components/ui";
import type { TabProps } from "@/pages/ProjectDetail";

type Exp = Schemas["ExperimentOut"];
type Page = Schemas["ExperimentPage"];
type Param = { name: string; value?: number | null; text_value?: string | null; unit?: string | null; note?: string | null };
type Reagent = { name: string; lot_no?: string | null; quantity?: number | null; unit?: string | null };
type Equip = { name: string; id?: string | null };
type LinkT = { experiment_id: string; relation: "previous" | "next" | "related" };

const PAGE = 15;

export default function Experiments({ project: p, canWrite }: TabProps) {
  const [filters, setFilters] = useState({ q: "", outcome: "", tag: "", parameter: "", date_from: "", date_to: "", sort: "performed_at", order: "desc" });
  const [offset, setOffset] = useState(0);
  const [form, setForm] = useState<{ mode: "create" } | { mode: "edit"; exp: Exp } | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const qs = new URLSearchParams({ limit: String(PAGE), offset: String(offset), sort: filters.sort, order: filters.order });
  (["q", "outcome", "tag", "parameter"] as const).forEach((k) => filters[k] && qs.set(k, filters[k]));
  if (filters.date_from) qs.set("date_from", new Date(filters.date_from).toISOString());
  if (filters.date_to) qs.set("date_to", new Date(`${filters.date_to}T23:59:59`).toISOString());
  const list = useQuery({ queryKey: ["experiments", p.id, qs.toString()], queryFn: () => api<Page>(`/projects/${p.id}/experiments?${qs}`) });
  const setF = (k: keyof typeof filters) => (e: { target: { value: string } }) => { setOffset(0); setFilters({ ...filters, [k]: e.target.value }); };

  return (
    <div>
      <div className="card mb-4 grid gap-3 p-4 md:grid-cols-6">
        <input aria-label="Search experiments" className="input md:col-span-2" placeholder="Search name, notes, results…" value={filters.q} onChange={setF("q")} />
        <select aria-label="Outcome" className="input" value={filters.outcome} onChange={setF("outcome")}>
          <option value="">Any outcome</option><option value="success">success</option><option value="failure">failure</option><option value="inconclusive">inconclusive</option><option value="unknown">unknown</option></select>
        <input aria-label="Tag" className="input" placeholder="Tag" value={filters.tag} onChange={setF("tag")} />
        <input aria-label="Parameter" className="input" placeholder="Parameter (e.g. pH)" value={filters.parameter} onChange={setF("parameter")} />
        <div className="flex gap-2">
          <select aria-label="Sort by" className="input" value={filters.sort} onChange={setF("sort")}><option value="performed_at">Date performed</option><option value="updated_at">Last changed</option><option value="created_at">Created</option><option value="identifier">Identifier</option></select>
          <select aria-label="Order" className="input w-24" value={filters.order} onChange={setF("order")}><option value="desc">↓</option><option value="asc">↑</option></select>
        </div>
        <div className="flex items-center gap-2 md:col-span-3"><label className="text-sm text-slate-600" htmlFor="df">From</label><input id="df" type="date" className="input" value={filters.date_from} onChange={setF("date_from")} />
          <label className="text-sm text-slate-600" htmlFor="dt">to</label><input id="dt" type="date" className="input" value={filters.date_to} onChange={setF("date_to")} /></div>
        <div className="flex justify-end md:col-span-3">{canWrite && <button className="btn-primary" onClick={() => setForm({ mode: "create" })}><Plus size={16} />New experiment</button>}</div>
      </div>

      {list.isLoading && <Spinner label="Loading experiments…" />}
      {list.isError && <Banner tone="red">{errMsg(list.error)}</Banner>}
      {list.data?.total === 0 && <Empty title="No experimental records found">{canWrite ? "Record your first experiment with “New experiment”." : "Nothing matches these filters."}</Empty>}
      {!!list.data?.items.length && (
        <div className="card overflow-x-auto">
          <table className="w-full text-left text-sm" data-testid="experiment-table">
            <thead className="bg-slate-50 text-slate-600"><tr>{["ID", "Title", "Performed", "Outcome", "Key parameters", "Version", "Updated"].map((h) => <th key={h} className="px-3 py-2 font-semibold">{h}</th>)}</tr></thead>
            <tbody>{list.data.items.map((e) => (
              <tr key={e.id} className="cursor-pointer border-t border-slate-100 hover:bg-slate-50" onClick={() => setOpen(e.id)}>
                <td className="px-3 py-2 font-mono text-xs"><button className="text-brand-700 underline" onClick={() => setOpen(e.id)}>{e.identifier}</button></td>
                <td className="px-3 py-2">{e.title}<div className="text-xs text-slate-500">{e.tags.join(", ")}</div></td>
                <td className="px-3 py-2 whitespace-nowrap">{fmtDate(e.performed_at)}</td>
                <td className="px-3 py-2"><StatusBadge status={e.outcome} /></td>
                <td className="px-3 py-2 text-xs">{(e.parameters as Param[]).slice(0, 3).map((x) => `${x.name} ${x.value ?? x.text_value ?? ""}${x.unit ? ` ${x.unit}` : ""}`).join(" · ")}</td>
                <td className="px-3 py-2">v{e.version}</td>
                <td className="px-3 py-2 whitespace-nowrap text-xs text-slate-500">{fmtDate(e.updated_at)}<div>{e.updated_by_name}</div></td>
              </tr>))}</tbody>
          </table>
        </div>
      )}
      {list.data && <Pager total={list.data.total} limit={PAGE} offset={offset} onChange={setOffset} />}

      {form && <ExperimentForm projectId={p.id} initial={form.mode === "edit" ? form.exp : undefined} onClose={() => setForm(null)}
        onSaved={(e) => { setForm(null); setOpen(e.id); }} />}
      {open && <Detail projectId={p.id} id={open} canWrite={canWrite} onClose={() => setOpen(null)} onEdit={(e) => { setOpen(null); setForm({ mode: "edit", exp: e }); }} />}
    </div>
  );
}

// ------------------------------------------------------------------ form
function Rows<T extends Record<string, unknown>>({ label, rows, set, blank, cols }: {
  label: string; rows: T[]; set: (r: T[]) => void; blank: T; cols: { key: keyof T & string; placeholder: string; type?: string; width?: string }[];
}) {
  return (
    <fieldset className="rounded-md border border-slate-200 p-3">
      <legend className="px-1 text-sm font-medium text-slate-700">{label}</legend>
      {rows.map((r, i) => (
        <div key={i} className="mb-2 flex gap-2">
          {cols.map((c) => (
            <input key={c.key} aria-label={`${label} ${c.placeholder} ${i + 1}`} className={`input ${c.width ?? "flex-1"}`} placeholder={c.placeholder} type={c.type ?? "text"} step="any"
              value={(r[c.key] as string | number | null | undefined) ?? ""} onChange={(e) => set(rows.map((x, j) => (j === i ? { ...x, [c.key]: e.target.value } : x)))} />
          ))}
          <button type="button" className="btn-secondary px-2" aria-label={`Remove ${label} ${i + 1}`} onClick={() => set(rows.filter((_, j) => j !== i))}><Trash2 size={14} /></button>
        </div>
      ))}
      <button type="button" className="btn-secondary px-3 py-1 text-xs" onClick={() => set([...rows, { ...blank }])}><Plus size={12} />Add</button>
    </fieldset>
  );
}

function toLocalInput(iso?: string | null) {
  if (!iso) return "";
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function ExperimentForm({ projectId, initial, onClose, onSaved }: { projectId: string; initial?: Exp; onClose: () => void; onSaved: (e: Exp) => void }) {
  const qc = useQueryClient();
  const others = useQuery({ queryKey: ["exp-options", projectId], queryFn: () => api<Page>(`/projects/${projectId}/experiments?limit=100&sort=identifier&order=asc`) });
  const docs = useQuery({ queryKey: ["doc-options", projectId], queryFn: () => api<Schemas["ProjectDocumentPage"]>(`/projects/${projectId}/documents?limit=100`) });
  const [f, setF] = useState({
    identifier: initial?.identifier ?? "", title: initial?.title ?? "", performed_at: toLocalInput(initial?.performed_at), outcome: initial?.outcome ?? "unknown",
    objective: initial?.objective ?? "", observations: initial?.observations ?? "", results: initial?.results ?? "", conclusions: initial?.conclusions ?? "",
    tags: (initial?.tags ?? []).join(", "), change_note: "",
  });
  const [reagents, setReagents] = useState<Reagent[]>((initial?.reagents as Reagent[]) ?? []);
  const [equipment, setEquipment] = useState<Equip[]>((initial?.equipment as Equip[]) ?? []);
  const [params, setParams] = useState<Param[]>((initial?.parameters as Param[]) ?? []);
  const [conds, setConds] = useState<{ k: string; v: string }[]>(Object.entries(initial?.conditions ?? {}).map(([k, v]) => ({ k, v: String(v) })));
  const [custom, setCustom] = useState<{ k: string; v: string }[]>(Object.entries(initial?.custom_fields ?? {}).map(([k, v]) => ({ k, v: String(v) })));
  const [links, setLinks] = useState<LinkT[]>((initial?.links as LinkT[]) ?? []);
  const [attachments, setAttachments] = useState<string[]>((initial?.attachments as string[]) ?? []);
  const [error, setError] = useState<string | null>(null);

  const body = () => {
    const num = (v: unknown) => (v === "" || v === null || v === undefined ? null : Number(v));
    return {
      title: f.title, performed_at: f.performed_at ? new Date(f.performed_at).toISOString() : null, outcome: f.outcome,
      objective: f.objective || null, observations: f.observations || null, results: f.results || null, conclusions: f.conclusions || null,
      tags: f.tags.split(",").map((t) => t.trim()).filter(Boolean),
      reagents: reagents.filter((r) => r.name?.trim()).map((r) => ({ name: r.name, lot_no: r.lot_no || null, quantity: num(r.quantity), unit: r.unit || null })),
      equipment: equipment.filter((r) => r.name?.trim()).map((r) => ({ name: r.name, id: r.id || null })),
      parameters: params.filter((r) => r.name?.trim()).map((r) => ({ name: r.name, value: num(r.value), text_value: r.text_value || null, unit: r.unit || null, note: r.note || null })),
      conditions: Object.fromEntries(conds.filter((c) => c.k.trim()).map((c) => [c.k.trim(), c.v])),
      custom_fields: Object.fromEntries(custom.filter((c) => c.k.trim()).map((c) => [c.k.trim(), c.v])),
      links, attachments,
    };
  };
  const m = useMutation({
    mutationFn: () => initial
      ? api<Exp>(`/projects/${projectId}/experiments/${initial.id}`, { method: "PATCH", json: { ...body(), expected_version: initial.version, change_note: f.change_note || null } })
      : api<Exp>(`/projects/${projectId}/experiments`, { method: "POST", json: { identifier: f.identifier, ...body() } }),
    onSuccess: (e) => { toast.success(initial ? `Saved as version ${e.version}` : "Experiment recorded"); void qc.invalidateQueries({ queryKey: ["experiments", projectId] }); void qc.invalidateQueries({ queryKey: ["experiment", projectId, e.id] }); onSaved(e); },
    onError: (e) => { setError(errMsg(e)); toast.error(errMsg(e)); },
  });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const submit = (e: FormEvent) => { e.preventDefault(); setError(null); m.mutate(); };
  // a plain render helper, NOT a component: a component declared here would be re-created every render and remount (blur) on each keystroke
  const area = (k: "objective" | "observations" | "results" | "conclusions", label: string, rows = 3) =>
    <div><label className="label" htmlFor={`x-${k}`}>{label}</label><textarea id={`x-${k}`} className="input" rows={rows} value={f[k]} onChange={set(k)} /></div>;

  return (
    <Modal title={initial ? `Edit ${initial.identifier} (currently v${initial.version})` : "New experiment"} onClose={onClose} wide>
      <form onSubmit={submit} className="space-y-4">
        {error && <Banner tone="red">{error}</Banner>}
        <div className="grid gap-3 md:grid-cols-4">
          <div><label className="label" htmlFor="x-id">Experiment ID</label><input id="x-id" className="input" required disabled={!!initial} maxLength={80} value={f.identifier} onChange={set("identifier")} /></div>
          <div className="md:col-span-2"><label className="label" htmlFor="x-title">Name / title</label><input id="x-title" className="input" required maxLength={200} value={f.title} onChange={set("title")} /></div>
          <div><label className="label" htmlFor="x-out">Outcome</label><select id="x-out" className="input" value={f.outcome} onChange={set("outcome")}><option value="unknown">unknown</option><option value="success">success</option><option value="failure">failure</option><option value="inconclusive">inconclusive</option></select></div>
          <div><label className="label" htmlFor="x-when">Date and time</label><input id="x-when" type="datetime-local" className="input" value={f.performed_at} onChange={set("performed_at")} /></div>
          <div className="md:col-span-3"><label className="label" htmlFor="x-tags">Tags (comma separated)</label><input id="x-tags" className="input" value={f.tags} onChange={set("tags")} /></div>
        </div>
        {area("objective", "Objective", 2)}
        <div className="grid gap-3 md:grid-cols-2">
          <Rows label="Reagents" rows={reagents} set={setReagents} blank={{ name: "" }} cols={[{ key: "name", placeholder: "name" }, { key: "lot_no", placeholder: "lot", width: "w-24" }, { key: "quantity", placeholder: "qty", type: "number", width: "w-20" }, { key: "unit", placeholder: "unit", width: "w-16" }]} />
          <Rows label="Equipment" rows={equipment} set={setEquipment} blank={{ name: "" }} cols={[{ key: "name", placeholder: "name" }, { key: "id", placeholder: "asset ID", width: "w-28" }]} />
        </div>
        <Rows label="Measured parameters" rows={params} set={setParams} blank={{ name: "" }} cols={[{ key: "name", placeholder: "parameter" }, { key: "value", placeholder: "value", type: "number", width: "w-28" }, { key: "unit", placeholder: "unit", width: "w-20" }, { key: "text_value", placeholder: "or text value", width: "w-36" }, { key: "note", placeholder: "note" }]} />
        <div className="grid gap-3 md:grid-cols-2">
          <Rows label="Conditions" rows={conds} set={setConds} blank={{ k: "", v: "" }} cols={[{ key: "k", placeholder: "condition" }, { key: "v", placeholder: "value" }]} />
          <Rows label="Custom fields" rows={custom} set={setCustom} blank={{ k: "", v: "" }} cols={[{ key: "k", placeholder: "field" }, { key: "v", placeholder: "value" }]} />
        </div>
        {area("observations", "Observations")}{area("results", "Results")}{area("conclusions", "Conclusions", 2)}
        <div className="grid gap-3 md:grid-cols-2">
          <fieldset className="rounded-md border border-slate-200 p-3"><legend className="px-1 text-sm font-medium text-slate-700">Linked experiments</legend>
            {links.map((l, i) => (
              <div key={i} className="mb-2 flex gap-2">
                <select aria-label={`Relation ${i + 1}`} className="input w-28" value={l.relation} onChange={(e) => setLinks(links.map((x, j) => (j === i ? { ...x, relation: e.target.value as LinkT["relation"] } : x)))}><option value="previous">previous</option><option value="next">next</option><option value="related">related</option></select>
                <select aria-label={`Linked experiment ${i + 1}`} className="input flex-1" value={l.experiment_id} onChange={(e) => setLinks(links.map((x, j) => (j === i ? { ...x, experiment_id: e.target.value } : x)))}>
                  <option value="">choose…</option>{others.data?.items.filter((o) => o.id !== initial?.id).map((o) => <option key={o.id} value={o.id}>{o.identifier} · {o.title}</option>)}</select>
                <button type="button" className="btn-secondary px-2" aria-label={`Remove link ${i + 1}`} onClick={() => setLinks(links.filter((_, j) => j !== i))}><Trash2 size={14} /></button>
              </div>))}
            <button type="button" className="btn-secondary px-3 py-1 text-xs" onClick={() => setLinks([...links, { experiment_id: "", relation: "related" }])}><Plus size={12} />Add link</button>
          </fieldset>
          <fieldset className="rounded-md border border-slate-200 p-3"><legend className="px-1 text-sm font-medium text-slate-700">Attached documents</legend>
            {docs.data?.items.length === 0 && <div className="text-sm text-slate-500">Upload documents in the Documentation tab first.</div>}
            <div className="max-h-32 space-y-1 overflow-y-auto">{docs.data?.items.map((d) => (
              <label key={d.id} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={attachments.includes(d.id)} onChange={(e) => setAttachments(e.target.checked ? [...attachments, d.id] : attachments.filter((a) => a !== d.id))} />{d.title}</label>))}</div>
          </fieldset>
        </div>
        {initial && <div><label className="label" htmlFor="x-note">What changed and why (kept in the history)</label><input id="x-note" className="input" maxLength={500} value={f.change_note} onChange={set("change_note")} /></div>}
        <div className="flex justify-end gap-2"><button type="button" className="btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn-primary" disabled={m.isPending || !f.title.trim() || (!initial && !f.identifier.trim()) || links.some((l) => !l.experiment_id)}>{m.isPending ? "Saving…" : initial ? "Save new version" : "Record experiment"}</button></div>
      </form>
    </Modal>
  );
}

// ------------------------------------------------------------------ detail
function Detail({ projectId, id, canWrite, onClose, onEdit }: { projectId: string; id: string; canWrite: boolean; onClose: () => void; onEdit: (e: Exp) => void }) {
  const [tab, setTab] = useState<"details" | "history" | "compare" | "analysis">("details");
  const q = useQuery({ queryKey: ["experiment", projectId, id], queryFn: () => api<Exp>(`/projects/${projectId}/experiments/${id}`) });
  const qc = useQueryClient();
  const void_ = useMutation({
    mutationFn: (reason: string) => api(`/projects/${projectId}/experiments/${id}?reason=${encodeURIComponent(reason)}`, { method: "DELETE" }),
    onSuccess: () => { toast.success("Record voided (history kept)"); void qc.invalidateQueries({ queryKey: ["experiments", projectId] }); onClose(); },
    onError: (e) => toast.error(errMsg(e)),
  });
  const e = q.data;
  return (
    <Modal title={e ? `${e.identifier} · ${e.title}` : "Experiment"} onClose={onClose} wide>
      {q.isLoading && <Spinner />}
      {q.isError && <Banner tone="red">{errMsg(q.error)}</Banner>}
      {e && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2"><StatusBadge status={e.outcome} /><span className="text-sm text-slate-500">v{e.version} · created by {e.created_by_name} · last changed by {e.updated_by_name} on {fmtDate(e.updated_at)}</span>
            {e.voided_at && <span className="badge bg-red-100 text-red-800">voided {fmtDate(e.voided_at)}</span>}</div>
          <div className="flex flex-wrap gap-1 border-b border-slate-200">
            {([["details", "Details", null], ["history", "History", History], ["compare", "Compare", Scale], ["analysis", "Troubleshoot", Microscope]] as const).map(([k, l, Icon]) => (
              <button key={k} className={`flex items-center gap-1 border-b-2 px-3 py-2 text-sm ${tab === k ? "border-brand-600 font-medium text-brand-700" : "border-transparent text-slate-600"}`} onClick={() => setTab(k)}>{Icon && <Icon size={14} />}{l}</button>))}
          </div>
          {tab === "details" && <DetailsView e={e} />}
          {tab === "history" && <HistoryView projectId={projectId} e={e} />}
          {tab === "compare" && <CompareView projectId={projectId} e={e} />}
          {tab === "analysis" && <AnalysisView projectId={projectId} e={e} />}
          {canWrite && !e.voided_at && (
            <div className="flex justify-between border-t border-slate-100 pt-3">
              <button className="btn-secondary text-red-700" onClick={() => { const r = window.prompt("Why is this record being voided? (kept in the history)"); if (r && r.trim().length >= 3) void_.mutate(r.trim()); }}><Trash2 size={14} />Void record</button>
              <button className="btn-primary" onClick={() => onEdit(e)}>Edit</button>
            </div>)}
        </div>
      )}
    </Modal>
  );
}

function KV({ label, children }: { label: string; children: React.ReactNode }) {
  return <div><div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div><div className="mt-0.5 whitespace-pre-wrap text-sm">{children || <span className="text-slate-400">—</span>}</div></div>;
}

function Snapshot({ e }: { e: { [k: string]: unknown } }) {
  const params = (e.parameters as Param[]) ?? [];
  const reagents = (e.reagents as Reagent[]) ?? [];
  const equipment = (e.equipment as Equip[]) ?? [];
  const conditions = (e.conditions as Record<string, unknown>) ?? {};
  const custom = (e.custom_fields as Record<string, unknown>) ?? {};
  return (
    <div className="space-y-3">
      <div className="grid gap-3 md:grid-cols-3">
        <KV label="Performed">{fmtDate(e.performed_at as string)}</KV>
        <KV label="Tags">{((e.tags as string[]) ?? []).join(", ")}</KV>
        <KV label="Equipment">{equipment.map((x) => x.name + (x.id ? ` (${x.id})` : "")).join(", ")}</KV>
      </div>
      <KV label="Objective">{e.objective as string}</KV>
      <KV label="Reagents">{reagents.map((r) => `${r.name}${r.lot_no ? ` lot ${r.lot_no}` : ""}${r.quantity != null ? ` ${r.quantity} ${r.unit ?? ""}` : ""}`).join("; ")}</KV>
      {params.length > 0 && (
        <table className="w-full text-left text-sm"><thead className="text-slate-500"><tr>{["Parameter", "Value", "Unit", "Note"].map((h) => <th key={h} className="px-2 py-1 font-semibold">{h}</th>)}</tr></thead>
          <tbody>{params.map((x, i) => <tr key={i} className="border-t border-slate-100"><td className="px-2 py-1">{x.name}</td><td className="px-2 py-1">{x.value ?? x.text_value}</td><td className="px-2 py-1">{x.unit}</td><td className="px-2 py-1 text-slate-500">{x.note}</td></tr>)}</tbody></table>)}
      <KV label="Conditions">{Object.entries(conditions).map(([k, v]) => `${k}: ${String(v)}`).join("\n")}</KV>
      <KV label="Custom fields">{Object.entries(custom).map(([k, v]) => `${k}: ${String(v)}`).join("\n")}</KV>
      <KV label="Observations">{e.observations as string}</KV><KV label="Results">{e.results as string}</KV><KV label="Conclusions">{e.conclusions as string}</KV>
    </div>
  );
}

function DetailsView({ e }: { e: Exp }) {
  const links = (e.links as LinkT[]) ?? [];
  return (
    <div className="space-y-3">
      <Snapshot e={e as unknown as { [k: string]: unknown }} />
      {links.length > 0 && <KV label="Linked experiments">{links.map((l) => `${l.relation}: ${l.experiment_id.slice(0, 8)}…`).join(", ")}</KV>}
    </div>
  );
}

function HistoryView({ projectId, e }: { projectId: string; e: Exp }) {
  const [v, setV] = useState<number | null>(null);
  const q = useQuery({ queryKey: ["versions", projectId, e.id, e.version], queryFn: () => api<Schemas["VersionOut"][]>(`/projects/${projectId}/experiments/${e.id}/versions`) });
  const snap = useQuery({ queryKey: ["version", projectId, e.id, v], enabled: v !== null, queryFn: () => api<Schemas["VersionDetail"]>(`/projects/${projectId}/experiments/${e.id}/versions/${v}`) });
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <div>
        <p className="mb-2 text-sm text-slate-600">Every change is kept. Earlier versions are never overwritten, and answers cite the exact version they used.</p>
        {q.isLoading && <Spinner />}
        <ul className="space-y-2">{q.data?.map((x) => (
          <li key={x.version}><button className={`w-full rounded-md border p-2 text-left text-sm ${v === x.version ? "border-brand-500 bg-brand-50" : "border-slate-200 hover:bg-slate-50"}`} onClick={() => setV(x.version)}>
            <b>v{x.version}</b> · {x.changed_by_name} · {fmtDate(x.changed_at)}
            <div className="text-xs text-slate-500">changed: {x.changed_fields.join(", ")}{x.change_note ? ` — ${x.change_note}` : ""}</div></button></li>))}</ul>
      </div>
      <div>{snap.isLoading && <Spinner />}{snap.data && (<><div className="mb-2 text-sm font-semibold">Version {snap.data.version} as it was recorded</div><Snapshot e={snap.data.snapshot as { [k: string]: unknown }} /></>)}
        {v === null && <Empty title="Select a version" />}</div>
    </div>
  );
}

function CompareView({ projectId, e }: { projectId: string; e: Exp }) {
  const [other, setOther] = useState("");
  const opts = useQuery({ queryKey: ["exp-options", projectId], queryFn: () => api<Page>(`/projects/${projectId}/experiments?limit=100&sort=identifier&order=asc`) });
  const cmp = useQuery({ queryKey: ["compare", projectId, e.id, other], enabled: !!other, queryFn: () => api<{
    b: { identifier: string; version: number; outcome: string }; parameters: { parameter: string; a: unknown; b: unknown; unit_a?: string; unit_b?: string; delta?: number; pct?: number | null; note?: string }[];
    reagents: { only_a: string[]; only_b: string[] }; equipment: { only_a: string[]; only_b: string[] }; conditions: Record<string, { a: unknown; b: unknown }> }>(`/projects/${projectId}/experiments/${e.id}/compare?with=${other}`) });
  return (
    <div className="space-y-3">
      <div><label className="label" htmlFor="cmp">Compare {e.identifier} with</label>
        <select id="cmp" className="input" value={other} onChange={(x) => setOther(x.target.value)}><option value="">choose an earlier or later experiment…</option>
          {opts.data?.items.filter((o) => o.id !== e.id).map((o) => <option key={o.id} value={o.id}>{o.identifier} · {o.title}</option>)}</select></div>
      {cmp.isLoading && <Spinner />}
      {cmp.data && (
        <>
          <table className="w-full text-left text-sm"><thead className="text-slate-500"><tr>{["Parameter", e.identifier, cmp.data.b.identifier, "Difference"].map((h) => <th key={h} className="px-2 py-1 font-semibold">{h}</th>)}</tr></thead>
            <tbody>{cmp.data.parameters.map((r) => (
              <tr key={r.parameter} className="border-t border-slate-100"><td className="px-2 py-1">{r.parameter}</td>
                <td className="px-2 py-1">{String(r.a ?? "—")} {r.unit_a}</td><td className="px-2 py-1">{String(r.b ?? "—")} {r.unit_b}</td>
                <td className="px-2 py-1">{r.note ? <span className="text-amber-700">{r.note}</span> : r.delta !== undefined ? `${r.delta > 0 ? "+" : ""}${Number(r.delta.toPrecision(5))}${r.pct != null ? ` (${r.pct > 0 ? "+" : ""}${r.pct}%)` : ""}` : ""}</td></tr>))}</tbody></table>
          <KV label={`Reagents only in ${e.identifier}`}>{cmp.data.reagents.only_a.join(", ")}</KV><KV label={`Reagents only in ${cmp.data.b.identifier}`}>{cmp.data.reagents.only_b.join(", ")}</KV>
          <KV label="Different conditions">{Object.entries(cmp.data.conditions).map(([k, v]) => `${k}: ${String(v.a ?? "—")} → ${String(v.b ?? "—")}`).join("\n")}</KV>
        </>)}
    </div>
  );
}

type Analysis = {
  compared_with: number; observed: string[]; hypotheses: string[]; unknown: string[]; caution: string;
  parameters: { parameter: string; value: number; unit: string; flags: string[]; history_count: number }[];
  similar_experiments: { id: string; identifier: string; outcome: string; similarity: number; shared: string[] }[];
};

function AnalysisView({ projectId, e }: { projectId: string; e: Exp }) {
  const q = useQuery({ queryKey: ["analysis", projectId, e.id, e.version], queryFn: () => api<Analysis>(`/projects/${projectId}/experiments/${e.id}/analysis`) });
  if (q.isLoading) return <Spinner label="Comparing with the project's other experiments…" />;
  if (q.isError || !q.data) return <Banner tone="red">{errMsg(q.error)}</Banner>;
  const a = q.data;
  const Sec = ({ title, tone, items }: { title: string; tone: string; items: string[] }) => items.length === 0 ? null : (
    <div className={`rounded-md border p-3 ${tone}`}><div className="mb-1 text-sm font-semibold">{title}</div><ul className="list-disc space-y-1 pl-5 text-sm">{items.map((x, i) => <li key={i}>{x}</li>)}</ul></div>);
  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-600">Computed from the recorded values of {a.compared_with} other experiment(s) in this project. No AI is involved in these numbers.</p>
      <Sec title="Observed (from the records)" tone="border-green-200 bg-green-50" items={a.observed} />
      <Sec title="Flags" tone="border-amber-300 bg-amber-50" items={a.parameters.flatMap((p) => p.flags.map((f) => `${p.parameter}: ${f}`))} />
      <Sec title="Hypotheses (unverified — patterns to check, not causes)" tone="border-purple-200 bg-purple-50" items={a.hypotheses} />
      <Sec title="Unknown / please record" tone="border-slate-300 bg-slate-50" items={a.unknown} />
      {a.similar_experiments.length > 0 && <div><div className="mb-1 text-sm font-semibold">Most similar earlier experiments</div>
        <ul className="space-y-1 text-sm">{a.similar_experiments.map((s) => <li key={s.id}><b>{s.identifier}</b> <StatusBadge status={s.outcome} /> similarity {s.similarity} · shared: {s.shared.join(", ")}</li>)}</ul></div>}
      <Banner tone="amber">{a.caution}</Banner>
    </div>
  );
}
