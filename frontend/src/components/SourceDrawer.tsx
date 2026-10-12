import { useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { Download, X } from "lucide-react";
import { api, apiBlob, type Schemas } from "@/api/client";
import type { Citation } from "@/api/types";
import { Banner, Spinner } from "@/components/ui";
import { PdfView } from "@/components/PdfView";

export async function downloadDoc(id: string, name: string) {
  const url = URL.createObjectURL(await apiBlob(`/documents/${id}/file?download=true`));
  const a = document.createElement("a"); a.href = url; a.download = name; a.click(); URL.revokeObjectURL(url);
}

/** Right-side drawer: the real source file at the cited page with the cited passage highlighted. */
export function SourceDrawer({ citation, onClose }: { citation: Citation | null; onClose: () => void }) {
  const open = !!citation;
  const doc = useQuery({
    queryKey: ["doc", citation?.document_id], enabled: open,
    queryFn: () => api<Schemas["DocumentDetail"]>(`/documents/${citation!.document_id}`),
  });
  const hl = useQuery({
    queryKey: ["hl", citation?.document_id, citation?.chunk_id], enabled: open && !!citation?.chunk_id,
    queryFn: () => api<Schemas["HighlightOut"]>(`/documents/${citation!.document_id}/highlights?chunk_id=${citation!.chunk_id}`),
  });
  const marked = useRef<HTMLDivElement>(null);
  useEffect(() => { marked.current?.scrollIntoView({ block: "center" }); }, [hl.data, doc.data]);
  if (!citation) return null;
  const d = doc.data;
  const isPdf = d?.file_type === "pdf";

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/30" onClick={onClose} />
      <aside className="fixed right-0 top-0 z-50 flex h-full w-full max-w-[720px] flex-col bg-white shadow-2xl" role="dialog" aria-label="Source document">
        <header className="flex items-start justify-between gap-3 border-b border-slate-200 p-4">
          <div>
            <div className="text-lg font-bold">{citation.doc_code} <span className="text-slate-500">· {citation.title}</span></div>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-sm">
              {d && <span className={`badge ${d.status === "effective" ? "bg-green-100 text-green-800" : "bg-red-100 text-red-800"}`}>
                {d.status === "effective" ? `Effective v${d.version}` : `${d.status.toUpperCase()} v${d.version}`}
              </span>}
              {citation.page && <span className="text-slate-600">Page {citation.page}</span>}
              {citation.section && <span className="text-slate-500">· {citation.section}</span>}
            </div>
          </div>
          <div className="flex items-center gap-2">
            {d && <button className="btn-secondary" onClick={() => downloadDoc(d.id, `${d.doc_code}-v${d.version}.${d.file_type}`)}><Download size={16} />Download</button>}
            <button aria-label="Close" onClick={onClose} className="rounded p-1 hover:bg-slate-100"><X /></button>
          </div>
        </header>
        <div className="flex-1 overflow-y-auto p-4">
          {d && d.status !== "effective" && <div className="mb-3"><Banner tone="red"><b>SUPERSEDED — DO NOT USE.</b> This version is shown for reference only.</Banner></div>}
          {(doc.isLoading || (hl.isLoading && !!citation.chunk_id)) && <Spinner label="Loading…" />}
          {d && isPdf && (hl.data || !citation.chunk_id) && (
            <PdfView documentId={d.id} page={hl.data?.page ?? citation.page ?? 1} rects={hl.data?.rects} pageWidth={hl.data?.page_width} pageHeight={hl.data?.page_height} />
          )}
          {d && isPdf && hl.data && hl.data.rects.length === 0 && (
            <p className="mt-3 rounded-md bg-slate-50 p-3 text-sm text-slate-700"><b>Cited passage:</b> {hl.data.text}</p>
          )}
          {d && !isPdf && (
            <div className="space-y-3 text-sm">
              {d.text_sections.map((s, i) => {
                const hit = s.chunk_id === citation.chunk_id;
                return (
                  <div key={i} ref={hit ? marked : undefined} className={hit ? "rounded-md bg-yellow-100 p-3 ring-2 ring-yellow-400" : "p-3"}>
                    {s.section && <div className="font-semibold">{s.section}</div>}
                    <div className="whitespace-pre-wrap">{s.text}</div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </aside>
    </>
  );
}
