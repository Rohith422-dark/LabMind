# Smart Lab Assistant (pharma)

Conversational access to approved lab knowledge for scientists: SOP search with **citations that open the source PDF at the
cited page with the passage highlighted**, a consent-based online fallback, troubleshooting by **rule-based SOP comparison**,
reagent inventory with atomic issue, and a tamper-evident audit trail. Approved documents are the single source of truth;
the scientist makes the final decision.

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
`DATABASE_URL`, `TEST_DATABASE_URL`, `JWT_SECRET`, `GEMINI_API_KEY`, `GEMINI_MODEL_FAST`, `GEMINI_MODEL_FALLBACK`,
`GEMINI_MODEL_REASONING`, `GEMINI_EMBED_MODEL` (`gemini-embedding-001`), `EMBED_DIM` (768), `VECTOR_MIN_SCORE`, `LLM_RPM`,
`ENABLE_SEARCH_GROUNDING`, `DEMO_MODE`, `DEMO_CARDS`, `LLM_MOCK`, `USER_PASSWORDS` (`user:pass,...`), `PORT`, `SIMULATE_429`.
Model names are never hardcoded. Secrets live only in the git-ignored `backend/.env`.

## Scripts
| command | purpose |
|---|---|
| `npm run dev` | API (reload) on :8010 + Vite on :5173 (proxies `/api`) |
| `npm run build` / `npm start` | production build served by FastAPI on http://127.0.0.1:8010 |
| `npm run seed` | reset + seed (same ingestion path as uploads) and pre-warm the answer cache |
| `npm run snapshot` / `npm run demo:reset` | freeze the seeded state / restore it in ~1 s, **no AI calls** (CLI only) |
| `npm run demo:verify` | run every demo question through the real pipeline, report cited doc/page |
| `npm run calibrate` | suggest `VECTOR_MIN_SCORE` from the demo questions |
| `npm run preflight` | green/red checklist: env, DB, indexes, triggers, AI reachability, models, cache, RBAC |
| `npm run models:check` | list Gemini models available to your key |
| `npm test`, `test:rbac`, `test:inventory` | backend tests (use `TEST_DATABASE_URL`, never the demo DB) |
| `npm run gen:api` | regenerate frontend types from the FastAPI OpenAPI schema |

## Demo accounts
`DEMO_CARDS=1` (default) shows four one-click cards on the login page; passwords come from `USER_PASSWORDS`.
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
