# PROGRESS

## Done
- M1: repo, docker-compose (pgvector/pg17), uv backend, full schema + db_init (HNSW, GIN tsvector, partial-unique effective version, append-only triggers), permissions.py, JWT auth, require(), hash-chained audit, users/audit/health routes, RBAC route-coverage + role-matrix tests.

- M1b: frontend scaffold (Vite/React/TS/Tailwind), typed API client + gen:api, AuthContext, ProtectedRoute, role-filtered Layout, Login with demo cards, Audit Log + Admin Users pages, `npm run build` + `npm start` serving SPA and API on one port.

## Next
- M2: llm.py (limiter/retry/mock/chain), embeddings, parser/chunker, ingestion jobs, retriever + streaming RAG.

## Known issues
- No GEMINI_API_KEY yet: all AI paths verified only under LLM_MOCK=1 (dev) until a key is added to backend/.env.
- FastAPI 0.143 wraps included routers lazily; test_rbac walks `app.routers.ROUTERS` and cross-checks against OpenAPI paths.

## Assumptions
- App runs on port 8010, not 8000: an unrelated container (mjp-similarity-service) already owns 127.0.0.1:8000 on this machine. Port is set in root package.json, vite proxy and PORT env.
- UI primitives are hand-written Tailwind classes in the shadcn style (no shadcn CLI) to save time.
- Demo-card login (`/api/auth/demo-login`) only works when DEMO_MODE=1; public routes are health, login, demo-users, demo-login.
- Backend lives in backend/, run via `uv run` (Python 3.12 fetched by uv; system python is 3.11).
- Test users (t_<role>) are created only in sla_test.
