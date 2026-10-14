# PROGRESS

## 2026-10-13 - projects, grounded project assistant, request workflow (this release)
- Added: private projects (owner/editor/viewer, password-gated access requests), experimental records with immutable history, project documents
  (PDF/DOCX/TXT/MD/CSV), project-scoped corrective RAG with evidence validation and explicit external-search consent, persistent conversations
  (rename/delete) and three-level memory, per-reagent availability (physical/usable/reserved/expired), reservations, the six-state request lifecycle with
  audit/notifications, versioned stock edits. Migration `backend/migrations/001_*.sql`; docs in README.
- Verified: 93 backend tests pass (51 pre-existing + 42 new; mock model); frontend type-check + production build pass; manual browser walk-through against the real
  backend with a real Gemini key (create project, record experiment, grounded answer with citation, consent deny and allow-once, request an expired reagent, lab assistant
  approval, requester timeline, phone-width layout).
- Found by that live run and fixed: the lexical-support check rejected correct claims that echoed the document title (now counts the cited source name);
  experiment-form textareas lost focus on every keystroke; the app shell was unusable at phone width.
- Not verified: real-model behaviour beyond a handful of questions (no quality benchmark); label-photo extraction; Gemini web grounding (not available on the key);
  browser file-picker uploads (uploads were exercised through the same API call); frontend automated tests (none exist in this repo).


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

## Verified live with a real Gemini key (2026-10-13)
- `preflight` 20/20 green; `demo:verify` 11/11 (8 answerable cite the right document, 3 uncovered trigger the consent flow); `calibrate` separable -> `VECTOR_MIN_SCORE=0.68`.
- Models: fast `gemini-3.1-flash-lite`, fallback `gemini-3.5-flash`, reasoning `gemini-3-flash-preview` (medium thinking), embeddings `gemini-embedding-001` @768.
- Real OCR of the scanned KFU HPLC page, real metadata/step extraction, streaming answers with citations, consent fallback, troubleshooting (structure + align + diagnose).
- **Search grounding is NOT available on this key's free tier (429 for every model)**: external answers fall back to ungrounded Gemini and say "No web sources available" (spec fallback).
- Troubleshooting diagnosis takes ~30 s on the free tier (reasoning model + rate limit).

## Not verified
- Label-photo extraction (no bottle photo). DOCX highlight polish.

## (historical) Needed a real Gemini key
- Real-model answer quality, embedding-based `VECTOR_MIN_SCORE` calibration, Google Search grounding, OCR of the scanned page
  in the KFU HPLC SOP, label-photo extraction. Everything above runs under `LLM_MOCK=1` (dev only, red ribbon).
  Run: add key -> `models:check` -> `LLM_MOCK=0` -> `seed` -> `calibrate` -> `demo:verify` -> `snapshot` -> `preflight`.

## Known issues
- Under MOCK embeddings only, 3 demo questions miss (lexical vectors). With the real key all 11 pass.
- Five requested university PDFs (Shimadzu, UKy, IIT-K, NCI-Frederick, St Andrews) were unreachable from the build network.
- Gemini function-calling for inventory chat was cut (SQL + templated reply instead).

## Assumptions
- Port 8010 (8000 is held by an unrelated container on this machine).
- At the user's request the **inventory CSV and user names are synthetic** (documented in README); documents and PubChem data are real.
- Seed documents are git-ignored (publisher licences unstated); SOURCES.md lists URLs.
- KFU pH SOP (an empty template) is excluded from the seed; its file is kept in `seed/docs`.
- Chunks never cross pages so every citation maps to one PDF page.
- UI primitives are hand-written Tailwind classes in the shadcn style.
