# LabMind (pharma)

Conversational access to approved lab knowledge for scientists: SOP search with **citations that open the source PDF at the
cited page with the passage highlighted**, a consent-based online fallback, troubleshooting by **rule-based SOP comparison**,
reagent inventory with atomic issue, and a tamper-evident audit trail. Approved documents are the single source of truth;
the scientist makes the final decision.

It also hosts **private research projects** (experimental records with full version history, project documentation, an
evidence-grounded project assistant with persistent chats and memory) and a **reagent request workflow** between users and lab
assistants - see [Research projects](#research-projects-evidence-grounded-assistant-and-memory) and
[Reagent requests](#reagent-inventory-and-the-request-workflow).

Stack: Python 3.12 + FastAPI · PostgreSQL 17 + pgvector · React + Vite + TypeScript + Tailwind · Gemini (free tier).

## Prerequisites
Python 3.12 via [`uv`](https://docs.astral.sh/uv/) (uv fetches 3.12 itself), Node 20+, Docker Desktop (or any Postgres with
pgvector, then only `DATABASE_URL` changes), a free Gemini API key from https://aistudio.google.com/apikey.

## First run
```bash
cp backend/.env.example backend/.env        # then edit it (see below)
npm run setup                               # installs everything, starts Postgres, creates the schema
npm run seed                                # users, reagents (PubChem), inventory, documents, cache pre-warm
npm run build && npm start                  # http://127.0.0.1:8010
```
Port **8010** (not 8000) because 8000 is commonly taken by other local services. Change it in `package.json`,
`frontend/vite.config.ts` and `PORT`.

### Switching from mock to the real AI (do this before any demo)
1. Put `GEMINI_API_KEY` in `backend/.env`, then `npm run models:check` and paste the recommended model names.
2. Set `LLM_MOCK=0` and `DEMO_MODE=1` (the server refuses to start with both `LLM_MOCK=1` and `DEMO_MODE=1`).
3. `npm run seed` again (chunks must be embedded by the same model that embeds questions), then
   `npm run calibrate` (set `VECTOR_MIN_SCORE`), `npm run demo:verify`, and `npm run snapshot`.
4. `npm run preflight` must be all green.

### Environment variables
`DATABASE_URL`, `TEST_DATABASE_URL`, `JWT_SECRET` (**set a long random value outside local dev**), `STORAGE_DIR` (uploaded project
files, default `backend/storage`, git-ignored), `PROJECT_MAX_UPLOAD_MB` (10), `PROJECT_MIN_SCORE` (optional cosine gate for project
retrieval, falls back to `VECTOR_MIN_SCORE`), `CORS_ORIGINS` (extra comma-separated origins), `GEMINI_API_KEY`, `GEMINI_MODEL_FAST`, `GEMINI_MODEL_FALLBACK`,
`GEMINI_MODEL_REASONING`, `GEMINI_EMBED_MODEL` (`gemini-embedding-001`), `EMBED_DIM` (768), `VECTOR_MIN_SCORE`, `LLM_RPM`,
`ENABLE_SEARCH_GROUNDING`, `DEMO_MODE`, `DEMO_CARDS`, `LLM_MOCK`, `USER_PASSWORDS` (`user:pass,...`), `PORT`, `SIMULATE_429`.
Model names are never hardcoded. Secrets live only in the git-ignored `backend/.env`.

## Scripts
| command | purpose |
|---|---|
| `npm run dev` | API (reload) on :8010 + Vite on :5173 (proxies `/api`) |
| `npm run build` / `npm start` | production build served by FastAPI on http://127.0.0.1:8010 |
| `npm run db:migrate` | apply `backend/migrations/*.sql` (also run by `db:init`; idempotent, safe on an existing database) |
| `npm run seed` | reset + seed (same ingestion path as uploads) and pre-warm the answer cache |
| `npm run snapshot` / `npm run demo:reset` | freeze the seeded state / restore it in ~1 s, **no AI calls** (CLI only) |
| `npm run demo:verify` | run every demo question through the real pipeline, report cited doc/page |
| `npm run calibrate` | suggest `VECTOR_MIN_SCORE` from the demo questions |
| `npm run preflight` | green/red checklist: env, DB, indexes, triggers, AI reachability, models, cache, RBAC |
| `npm run models:check` | list Gemini models available to your key |
| `npm test`, `test:rbac`, `test:inventory` | backend tests (use `TEST_DATABASE_URL`, never the demo DB) |
| `npm run gen:api` | regenerate frontend types from the FastAPI OpenAPI schema |

## Demo accounts
`DEMO_CARDS=1` (**off by default now**: the cards log in without a password, so enable them only on a demo machine; `DEMO_MODE=1` also enables them) shows four one-click cards on the login page; passwords come from `USER_PASSWORDS`.
Scientist, Lab Analyst, Senior Analyst, Admin. Names in `backend/seed/users.json` are **synthetic placeholders**: replace them
with your team's names.

## Roles (enforced in `backend/app/permissions.py` and in the UI)
Scientist / Lab Analyst / Senior Analyst / Admin. Every route except `/api/health`, `/api/auth/login`, `/api/auth/demo-users`
and `/api/auth/demo-login` declares `require(permission)`. `npm run test:rbac` fails if a route is missing one and prints the
full role matrix.

## Data
* **Documents are real**, unmodified public PDFs listed in `backend/seed/docs/SOURCES.md` (two USC BME SOPs: pH meter and
  analytical balance; KFU instrument SOPs; the ACE/John Dolan HPLC Troubleshooting Guide). They are git-ignored; re-download
  them from the URLs in SOURCES.md. Licence terms are not stated by the publishers: non-commercial demo use only.
* **Reagent master data** (name, CAS, formula, GHS hazards) is fetched from PubChem and cached with the CID as provenance.
* **Inventory lots, quantities, expiry dates and users are SYNTHETIC** (`inventory.csv`, `users.json`) and were generated for
  this demo at the team's request. They are labelled as such here, never presented as a real stock register. Replace
  `inventory.csv` with a real register when you have one (same columns; the seed validates every row with line numbers).
* The two **hand-reviewed SOP step lists** (pH meter, balance) in `manifest.json` are transcribed from the real documents.
* `demo-questions.json` (team-authored) drives the guide panel and `demo:verify`.

## Assumptions and limitations
* Free-tier Gemini inputs may be used by Google to improve its products: do not upload confidential data (banner shown).
* External AI answers are unverified, always amber-labelled, never embedded into the knowledge base.
* PyMuPDF is AGPL (fine for a hackathon). Permissive swap: pypdfium2 / pdfplumber.
* Inventory chat answers use parameterised SQL with a templated reply (the Gemini function-calling variant was cut).
* With `LLM_MOCK=1` (development only) answers are canned extracts of the top passage and a red **MOCK AI** ribbon shows.
* Production would add SSO, HTTPS, a private or paid no-training model, a QA approval workflow, managed Postgres and workers.


## Upgrading an existing database
```bash
docker exec sla-db pg_dump -U sla sla > backup.sql      # recommended first
npm run db:migrate                                      # additive; also remaps request statuses pending->submitted, issued->fulfilled
```
`npm run db:init` does the same (create new tables, then run the numbered SQL migrations). Old `demo:reset` snapshots keep working;
re-run `npm run snapshot` to refresh them. Restart the API afterwards and rebuild the frontend (`npm run build`).

## Research projects, evidence-grounded assistant and memory
Everything below lives in the existing FastAPI app (`backend/app/routers/{projects,experiments,project_documents,project_chat}.py`,
services in `backend/app/services/`) and the React app (`frontend/src/pages/Projects.tsx`, `ProjectDetail.tsx`, `pages/project/*`).
Interactive API docs: **http://127.0.0.1:8010/docs** (OpenAPI at `/openapi.json`).

**Access model** (`services/access.py`, the only place that decides):
* Access = a row in `project_members` (owner / editor / viewer). A global role (admins included), a project id or a project password
  never grants access on its own. Non-members get **404** for everything (ids cannot be probed). Child resources are always loaded
  *through* the project in the URL, so a document/experiment/memory id from another project is a 404 even for someone who belongs to both.
* Owner: edit/archive/delete the project, set or clear the password, add/change/revoke collaborators, decide access requests. Editor: create
  and edit experiments, upload documents, write project memory. Viewer: read and ask the assistant.
* **Password workflow**: the owner sets a password (argon2id hash, never returned or logged). A signed-in non-member sends project id +
  password to `POST /api/projects/{id}/access-requests`; a correct password only creates a *pending request* and notifies the owner, who
  approves with an explicit role. Wrong / locked / no-password / unknown project all return the same generic 403; 5 failures lock that
  user for that project for 15 minutes; the endpoint is also rate limited per IP.
* Revoking a member removes their access at once (chats, summaries, memory and the assistant become 404; their derived summaries are wiped).
  Deleting a project cascades to experiments + history, documents, chunks/embeddings, conversations, memories and stored files (the audit log keeps the event).

**Experimental records**: flexible model (structured numeric parameters with units, reagents, equipment, free-form conditions and custom
fields, procedure refs, links to other experiments, attachments). Every create/edit writes an immutable row to `experiment_versions` (a
DB trigger forbids UPDATE/DELETE); edits need `expected_version` (stale edit -> 409, no silent overwrite); "delete" is a **void** that keeps
history. Full-text search, filters (outcome, tag, parameter, date), sorting and pagination; version viewer, field-by-field compare, and a
deterministic troubleshooting analysis (`/experiments/{id}/analysis`).

**Documents**: PDF, DOCX, TXT, MD, CSV. The extension must be allow-listed *and* the bytes must really be that format; size limit; DOCX zip-bomb
guard; the client filename is display-only (files are stored under a server-generated key outside the DB). Page numbers/headings are kept and indexed;
replacing or deleting a document removes its chunks in the same transaction, so it can never be retrieved afterwards. Scanned pages are *not*
OCR'd in projects (a warning is shown).

**Corrective RAG** (`services/project_rag.py`, `evidence.py`):
1. the route authorises the caller for *this* project; 2. retrieval (pgvector + full text, RRF) has `project_id` in the SQL `WHERE` of both arms
(`project_retriever.retrieve` has no default and asserts every row), so other projects' data is never loaded, let alone sent to a model;
3. a gate (cosine threshold or lexical coverage): below it no model call is made; 4. the model drafts typed claims
(`observed | interpretation | hypothesis | unknown`) citing passage numbers; 5. `evidence.validate` keeps only claims whose citations exist, whose
numbers all occur in the cited passages, whose content words are supported by the cited passage or source name, and whose quotations are verbatim;
6. the answer text is **rendered by the server from validated claims only** (observed / interpretation / "hypotheses - NOT verified" / "not
established" / conflicts), so unsupported model prose cannot leak; 7. documents that state different values for the same quantity are shown
as *conflicting sources*, not reconciled; 8. no validated support -> "insufficient" and the user is asked.

**External search** never starts on its own: `need_external` offers *allow once* / *allow for this conversation* / *continue with project information
only*. The decision endpoint only acts on the caller's own, still-pending message of that project. Only the sanitised question text is sent
(never documents, records or memory); the result is stored as a separate amber "external, unverified" message, is never merged into project findings
and is never indexed. One-time approval is not standing consent; the conversation-level permission can be withdrawn.
Troubleshooting adds a computed passage (values vs earlier runs, unusual values, similar runs, success-vs-failure contrasts, missing parameters) when a
question names an experiment; correlations are labelled hypotheses, never causes. Answer caches are **not** used for project answers.

**Persistence and memory** (all in Postgres): `conversations` + `chat_history` (messages with citations and verdicts) survive refreshes, logins and
devices; list/rename/delete in the UI. Conversation memory = last 4 turns verbatim + a rolling AI summary (`conversations.summary`, labelled
unverified, rebuilt when stale, user-clearable). Project memory (`memories`, scope=project) is shared by members; user preferences (scope=user) are
private; both are editable/deletable in the UI, can be created by "Remember that ..." in chat, and are injected as *context, never evidence*.
Memories whose source experiment/document changed or was removed become **stale** and are skipped until a human confirms them. AI-suggested memories
are flagged and never "verified".

## Reagent inventory and the request workflow
Extends the existing inventory (no second system). "Lab assistant" = role `lab_analyst` (`inventory.manage`).
* **Stock model**: per reagent *physical* (everything), *usable* (in date, active, minus reserved), *reserved* (held for approved requests), *expired*
  and *unavailable* (quarantined) quantities; labels Available / Running low / Out of stock / Expired / Unavailable / Awaiting restocking
  (`GET /api/inventory/reagents/summary`). Expired or quarantined stock is never usable. Lots carry `row_version`; edits, adjustments and receipts are
  versioned or relative so concurrent updates cannot silently overwrite each other; negative or over-reserved quantities are rejected by the API and by CHECK constraints.
* **Requests**: any signed-in user (roles scientist / lab analyst / senior analyst) can submit, including for expired, out-of-stock, insufficient or unlisted
  reagents (quantity > 0, unit family checked, reason required, urgency, optional project/experiment). Users see only their own (`GET /requests/mine`,
  `/requests/{id}`) and answer clarifications (`/respond`); everything else on someone else's request is 404/403.
* **Lifecycle** (enforced server-side, `services/request_workflow.py`): `submitted -> under_review -> needs_clarification <-> under_review -> approved -> fulfilled`,
  `rejected` from any open state. **Approval never touches stock** and says so; an optional *reservation* sets stock aside without changing physical stock.
  `fulfil` is separate: issue from a lot (one atomic statement checking availability, expiry and others' reservations) or confirm against a real in-date lot;
  requests for reagents not in the register are fulfilled by note. Every change is an append-only `request_events` row (actor, time, from/to, comment).
* **Notifications** (existing bell): submitted (to assistants); review / clarification / approved / rejected / fulfilled (to the requester); clarification answered;
  and "reagent is available again" when a receipt or adjustment turns zero usable stock into usable stock.

## Security notes
Server-side authorisation on every route (`npm run test:rbac` fails if a route lacks `require(...)`); argon2id hashes; per-IP rate limits on login,
project passwords, uploads, chat, external search and request creation; CORS restricted to configured origins/methods; secrets only from the environment;
uploads validated and stored outside the DB; append-only DB triggers for audit, inventory transactions, request events and experiment versions; hash-chained audit log
for project, access, document, experiment, memory, request and stock events.

Known limits: JWTs last 8 h and cannot be revoked server-side (membership and role are re-checked on every request, but a stolen token works until it expires); the lexical
support check cannot catch a claim that reuses the right words with the wrong meaning; the conflict detector only recognises "label: number unit" statements; project
documents with scanned pages are not OCR'd; Gemini Search grounding is unavailable on a free-tier key, so external answers then say "no web sources"; a lab assistant sees the *name*
of a project a requester attached to a request; admins deliberately have **no** access to project data. Do not upload confidential data while using a free-tier Gemini key.

## Tests
```bash
npm test                     # backend: 93 tests (needs Postgres; uses TEST_DATABASE_URL, never the demo DB; LLM_MOCK=1)
npm run test:rbac            # route/role matrix, prints the table
cd frontend && npx tsc --noEmit && npm run build     # frontend type-check + production build (there is no frontend unit-test framework in this repo)
```
The suite covers project ownership/password/roles/revocation/IDOR, records and history, document upload/replace/delete vs the index, grounding and
adversarial model output, external-search consent, cross-project isolation, conversations and memory, the request lifecycle, concurrency and rate limits.
Tests run against a *mock* model, so they prove the pipeline's rules, not real-model answer quality; see PROGRESS.md for what was checked with a real key.
