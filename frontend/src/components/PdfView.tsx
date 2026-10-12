import { useEffect, useRef, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import workerSrc from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { apiBlob } from "@/api/client";
import { Spinner } from "@/components/ui";

pdfjs.GlobalWorkerOptions.workerSrc = workerSrc;

interface Props {
  documentId: string;
  page: number;
  /** Highlight rectangles in PDF points (top-left origin) for the cited passage. */
  rects?: number[][];
  pageWidth?: number;
  pageHeight?: number;
  onPageCount?: (n: number) => void;
}

export function PdfView({ documentId, page, rects = [], pageWidth, onPageCount }: Props) {
  const [url, setUrl] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [width, setWidth] = useState(560);
  const box = useRef<HTMLDivElement>(null);
  const [current, setCurrent] = useState(page);

  useEffect(() => setCurrent(page), [page, documentId]);

  useEffect(() => {
    let revoked = false; let obj: string | null = null;
    setUrl(null); setErr(null);
    apiBlob(`/documents/${documentId}/file`).then((b) => {
      if (revoked) return;
      obj = URL.createObjectURL(b); setUrl(obj);
    }).catch((e) => setErr(e instanceof Error ? e.message : "Could not load the file"));
    return () => { revoked = true; if (obj) URL.revokeObjectURL(obj); };
  }, [documentId]);

  useEffect(() => {
    const el = box.current; if (!el) return;
    const ro = new ResizeObserver(() => setWidth(Math.max(280, Math.floor(el.clientWidth - 2))));
    ro.observe(el); return () => ro.disconnect();
  }, []);

  const scale = pageWidth ? width / pageWidth : 1;
  const showRects = current === page;
  return (
    <div ref={box} className="w-full">
      {err && <div className="text-sm text-red-600">{err}</div>}
      {!url && !err && <Spinner label="Loading source document…" />}
      {url && (
        <Document file={url} loading={<Spinner label="Rendering…" />} error={<div className="text-sm text-red-600">Could not render this PDF.</div>}
          onLoadSuccess={(d) => onPageCount?.(d.numPages)}>
          <div className="relative inline-block border border-slate-200 shadow-sm" data-testid="pdf-page">
            <Page pageNumber={current} width={width} renderTextLayer={false} renderAnnotationLayer={false} />
            {showRects && rects.map((r, i) => (
              <div key={i} data-testid="pdf-highlight" className="pointer-events-none absolute rounded-sm bg-yellow-300/50 ring-1 ring-yellow-500"
                style={{ left: r[0] * scale - 1, top: r[1] * scale - 1, width: (r[2] - r[0]) * scale + 2, height: (r[3] - r[1]) * scale + 2 }} />
            ))}
          </div>
        </Document>
      )}
      {url && (
        <div className="mt-2 flex items-center gap-2 text-xs text-slate-600">
          <button className="btn-secondary px-2 py-1" disabled={current <= 1} onClick={() => setCurrent(current - 1)}>Prev</button>
          <span>Page {current}</span>
          <button className="btn-secondary px-2 py-1" onClick={() => setCurrent(current + 1)}>Next</button>
          {current !== page && <button className="ml-2 text-brand-600 underline" onClick={() => setCurrent(page)}>Back to cited page {page}</button>}
        </div>
      )}
    </div>
  );
}
