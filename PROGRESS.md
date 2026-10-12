# PROGRESS

## Done (all verified by automated tests and by running the production build in a browser)
- **Platform**: schema (HNSW, GIN tsvector, one-effective-version partial unique index, DB-enforced append-only triggers),
  4-role RBAC (`permissions.py` + `require()`), JWT/argon2, hash-chained audit with `Verify integrity`, rate limits,
  security headers, clean JSON errors.
- **Ingestion**: PDF/DOCX parser (heading detection, scanned-page OCR fallback), chunker, auto-metadata, step extraction with
  heuristic fallback, background jobs with progress, atomic versioned publish (supersede, retire, gap resolve, notify).
- **Chat**: hybrid retrieval (pgvector + FTS, RRF), two answerability gates, NDJSON streaming, citations, PDF page-jump with
  highlight, safety notes from PubChem hazard data, consent-based external fallback with Search grounding, knowledge gaps,
  answer cache.
- **Troubleshooting**: deterministic comparison engine (units, tolerances, LIS ordering), clarifying questions, diagnosis with
  guide citations, expired-lot warning, deviation report export.
- **Inventory**: viewer, requests, atomic issue (10-way concurrency test: exactly 3 succeed), expired block, return/adjust/dispose,
  add lot incl. label-photo extraction.
- **Frontend**: all pages, guide panel + tour, notification bell, MOCK ribbon, dashboards computed from real rows.
- **Ops**: seed, snapshot, demo:reset (~1 s), preflight, calibrate, demo:verify, models:check, gen:api.
- **Tests (49)**: RBAC route coverage + matrix, concurrency, append-only, comparison engine/units, chunker, resilience
  (429 -> backoff -> model chain -> friendly error), full ingest-to-chat pipeline on real PDFs, troubleshooting API.

## Not verifiable here (needs a real Gemini key)
- Real-model answer quality, embedding-based `VECTOR_MIN_SCORE` calibration, Google Search grounding, OCR of the scanned page
  in the KFU HPLC SOP, label-photo extraction. Everything above runs under `LLM_MOCK=1` (dev only, red ribbon).
  Run: add key -> `models:check` -> `LLM_MOCK=0` -> `seed` -> `calibrate` -> `demo:verify` -> `snapshot` -> `preflight`.

## Known issues
- Under mock embeddings 3 demo questions (HPLC tailing/ghost peaks, balance spill) miss because mock vectors are lexical.
- Five requested university PDFs (Shimadzu, UKy, IIT-K, NCI-Frederick, St Andrews) were unreachable from the build network.
- Gemini function-calling for inventory chat was cut (SQL + templated reply instead).

## Assumptions
- Port 8010 (8000 is held by an unrelated container on this machine).
- At the user's request the **inventory CSV and user names are synthetic** (documented in README); documents and PubChem data are real.
- Seed documents are git-ignored (publisher licences unstated); SOURCES.md lists URLs.
- KFU pH SOP (an empty template) is excluded from the seed; its file is kept in `seed/docs`.
- Chunks never cross pages so every citation maps to one PDF page.
- UI primitives are hand-written Tailwind classes in the shadcn style.
