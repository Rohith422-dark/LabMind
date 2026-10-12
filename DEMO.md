# Demo runbook

## Pre-demo checklist (15 minutes before)
- [ ] Laptop on charger, battery > 80 %, Docker Desktop running (`docker ps` shows `sla-db`).
- [ ] Phone hotspot ready as wifi backup (Gemini needs internet).
- [ ] `backend/.env`: real `GEMINI_API_KEY`, `LLM_MOCK=0`, `DEMO_MODE=1`, models filled from `npm run models:check`.
- [ ] `npm run build`
- [ ] `npm run demo:reset` (clean seeded state, ~1 s, no AI calls)
- [ ] `npm run preflight` is **ALL GREEN** (checks DB, indexes, append-only triggers, models, embedding dim, cache, RBAC)
- [ ] `npm run demo:verify` — every answerable question cites the expected document, `not_covered` ones trigger the consent flow
- [ ] AI quota: roughly 10-15 requests/min and 1,500/day on the free tier. Do not rehearse the full flow more than twice
- [ ] `npm start`, open http://127.0.0.1:8010, keep a screen recording of a clean run as backup

## 5-minute script
| time | who | action | what to point out |
|---|---|---|---|
| 0:00 | — | Login page, click **Dr. Anika Rao (Scientist)** | one-click demo accounts, role-based sidebar |
| 0:30 | Scientist | Guide ▸ task 1: ask *How do I recalibrate the pH meter…* | streamed answer, cited from the *effective* version |
| 1:00 | Scientist | Click the **[1] chip** | real source PDF opens at the cited page, passage highlighted, "Effective v1" badge, download |
| 1:30 | Scientist | Ask an uncovered question (Guide ▸ task 3) → **Yes, search online** | consent first; amber *EXTERNAL AI RESULT* card with web links and warning; **Request official SOP** |
| 2:15 | Scientist | Troubleshooting (Guide ▸ task 4, prefilled narration) | stages, comparison table: critical steps missing, pH 6.00 vs 7.00 deviation, clarifying questions, diagnosis with guide citations, deviation report export |
| 3:15 | Scientist | Inventory → request a reagent | expiry/stock colours, hazard badges from PubChem |
| 3:30 | Analyst (Switch user) | Analyst console → issue; try the **expired** pH 10.00 buffer | atomic issue; expired lot blocked; scientist notified |
| 4:00 | Senior | Knowledge Gaps → Upload SOP → publish with change note | metadata auto-filled, gap resolved, requester notified |
| 4:30 | Scientist | Re-ask the question | now cited from the new document |
| 4:45 | Admin/Senior | Audit log → **Verify integrity** | chain of custody incl. `external_ai_used`, `access_denied` |
| 5:00 | Scientist | Open `/sop-management` | toast + audit entry (RBAC proof). `npm run test:rbac` prints the matrix |

Honesty notes for judges: documents are real public SOPs/guides; the **inventory register and user names are synthetic**
(see README ▸ Data). Versioning is shown live by uploading a newer real revision (no altered copies exist).

## If something fails
- **AI busy / 429**: the app retries, then falls to the fallback model; rehearsed questions are served from the pre-warmed
  cache even with no network. Switch to the phone hotspot if wifi drops.
- **Docker / DB down**: `docker compose up -d db`, then `npm run preflight`.
- **Anything odd mid-demo**: Ctrl+C, `npm run demo:reset`, `npm start` (about 10 seconds).
- **Last resort**: play the backup screen recording.

## Between judge groups
`npm run demo:reset` (CLI only, there is deliberately no HTTP endpoint). If you added or changed data, re-run
`npm run snapshot` first.
