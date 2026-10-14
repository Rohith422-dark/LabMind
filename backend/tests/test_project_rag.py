"""12.3 Evidence-grounded RAG, troubleshooting, external-search consent, and cross-project isolation.

Runs with LLM_MOCK=1 (deterministic embeddings and a deterministic 'model'), so these tests prove the PIPELINE's rules
(access filtering, validation, consent) - not the quality of a real model. Adversarial 'model' outputs are injected to
show that the validation layer, not the model's good behaviour, is what protects the user.
"""
import psycopg
import pytest

from app.config import get_settings
from app.db import session_maker
from app.services import evidence, llm, project_retriever
from app.services.evidence import Draft, DraftClaim, Passage
from app.services.sanitizer import sanitize
from tests.conftest import _test_url, auth
from tests.util import ROLE_USERNAMES, add_member, ask, ev, mk_experiment, mk_project, text_of, upload_text, uid  # noqa: F401


@pytest.fixture(autouse=True)
def lenient_gate():
    s = get_settings()
    old = s.vector_min_score
    s.vector_min_score = 0.2          # mock embeddings are lexical; the production value is calibrated for Gemini
    yield
    s.vector_min_score = old


@pytest.fixture
def external_calls(monkeypatch):
    calls: list[str] = []
    real = llm.generate_grounded

    async def spy(prompt, **kw):
        calls.append(prompt)
        return await real(prompt, **kw)
    monkeypatch.setattr(llm, "generate_grounded", spy)
    return calls


def P(n, text, stype="document", label="Doc", page=None):
    return Passage(n=n, source_type=stype, source_id=f"id{n}", source_version=1, label=label, page=page, section=None, text=text)


# ------------------------------------------------------------------ the validation policy itself (no database, no model)
def test_validation_drops_unsupported_claims():
    ps = [P(1, "The incubation temperature was 37 C for 24 hours. Samples were turbid."), P(2, "Storage at 4 C.")]
    d = Draft(claims=[
        DraftClaim(text="The incubation temperature was 37 C for 24 hours.", kind="observed", cites=[1]),     # supported
        DraftClaim(text="The incubation temperature was 42 C.", kind="observed", cites=[1]),                   # invented value
        DraftClaim(text="The centrifuge speed was fixed.", kind="observed", cites=[]),                         # no citation
        DraftClaim(text="Samples were turbid.", kind="observed", cites=[9]),                                   # citation does not exist
        DraftClaim(text="Plates are kept in the cold room.", kind="observed", cites=[2]),                      # words not in passage
        DraftClaim(text='The log says "contamination was suspected in all wells".', kind="observed", cites=[1]),  # fake quote
        DraftClaim(text="The exact cause is not recorded.", kind="unknown"),
    ])
    v = evidence.validate(d, ps)
    assert [c.text for c in v.kept if c.kind == "observed"] == ["The incubation temperature was 37 C for 24 hours."]
    reasons = " | ".join(r.reason for r in v.rejected)
    assert "value not found" in reasons and "no valid citation" in reasons and "lexical" in reasons
    assert len(v.rejected) == 5 and v.verdict == "partial"


def test_verdicts_and_hypothesis_labelling():
    ps = [P(1, "Yield dropped to 40 percent when the pH was 9.1.")]
    nothing = evidence.validate(Draft(claims=[DraftClaim(text="Totally unrelated statement about lasers.", kind="observed", cites=[1])]), ps)
    assert nothing.verdict == "insufficient" and not nothing.kept
    only_hyp = evidence.validate(Draft(claims=[DraftClaim(text="Yield dropped when the pH was 9.1, possibly due to hydrolysis.", kind="hypothesis", cites=[1])]), ps)
    assert only_hyp.verdict == "insufficient"                    # a hypothesis alone never answers a question
    full = evidence.validate(Draft(claims=[DraftClaim(text="Yield dropped to 40 percent when the pH was 9.1.", kind="observed", cites=[1]),
                                           DraftClaim(text="Yield dropped when the pH was 9.1, possibly due to hydrolysis.", kind="hypothesis", cites=[1])]), ps)
    assert full.verdict == "sufficient"
    out = evidence.render(full, [])
    assert out.index("**Observed") < out.index("**Hypotheses") and "NOT verified" in out
    partial = evidence.validate(Draft(claims=[DraftClaim(text="Yield dropped to 40 percent when the pH was 9.1.", kind="observed", cites=[1])],
                                      missing_information=["Which buffer was used"], questions_for_user=["What was the temperature?"]), ps)
    assert partial.verdict == "partial"
    text = evidence.render(partial, [])
    assert "Not established" in text and "Which buffer was used" in text and "please provide" in text


def test_conflict_detector_reports_documents_not_runs():
    a, b = P(1, "Storage temperature: 4 C for all buffers.", label="SOP A"), P(2, "The storage temperature is 8 C.", label="SOP B")
    c = evidence.detect_conflicts([a, b])
    assert len(c) == 1 and {s["value"] for s in c[0]["statements"]} == {4.0, 8.0}
    same = evidence.detect_conflicts([a, P(3, "Storage temperature = 4 C", label="SOP C")])
    assert same == []
    runs = [P(1, "Temperature = 37 C", "experiment", "EXP-1"), P(2, "Temperature = 45 C", "experiment", "EXP-2")]
    assert evidence.detect_conflicts(runs) == []                 # different runs may differ; that is data, not a conflict


# ------------------------------------------------------------------ answers with evidence
async def test_answer_is_grounded_and_cites_document_and_experiment(client, tokens):
    sci = tokens["scientist"]
    pid = (await mk_project(client, sci))["id"]
    doc = await upload_text(client, sci, pid, "Culture protocol", "Incubation temperature is 37 C. Incubate the culture for 24 hours. Store plates at 4 C.")
    exp = await mk_experiment(client, sci, pid, "EXP-100", title="Precipitation test", observations="A white precipitate formed at pH 9.1 after ten minutes.")

    events = await ask(client, sci, pid, "What is the incubation temperature for the culture?")
    assert ev(events, "need_external") is None
    cites = ev(events, "citations")["citations"]
    assert cites and cites[0]["source_type"] == "document" and cites[0]["source_id"] == doc["id"] and cites[0]["label"] == "Culture protocol"
    assert "37" in text_of(events) and "[1]" in text_of(events)
    assert ev(events, "answer")["verdict"] in ("sufficient", "partial")

    events = await ask(client, sci, pid, "Did a white precipitate form at pH 9.1?")
    c = ev(events, "citations")["citations"][0]
    assert c["source_type"] == "experiment" and c["source_id"] == exp["id"] and c["source_version"] == 1 and c["label"].startswith("EXP-100")
    # edit -> next answer cites the new version, and the old version stays viewable exactly as cited
    await client.patch(f"/api/projects/{pid}/experiments/{exp['id']}", headers=auth(sci),
                       json={"expected_version": 1, "observations": "A white precipitate formed at pH 9.1 after ten minutes. Filtered and dried."})
    c2 = ev(await ask(client, sci, pid, "Did a white precipitate form at pH 9.1?"), "citations")["citations"][0]
    assert c2["source_version"] == 2
    v1 = (await client.get(f"/api/projects/{pid}/experiments/{exp['id']}/versions/{c['source_version']}", headers=auth(sci))).json()
    assert "Filtered" not in v1["snapshot"]["observations"]


async def test_insufficient_evidence_is_declared_not_invented(client, tokens, external_calls):
    sci = tokens["scientist"]
    pid = (await mk_project(client, sci))["id"]
    await upload_text(client, sci, pid, "Culture protocol", "Incubation temperature is 37 C. Incubate the culture for 24 hours.")
    events = await ask(client, sci, pid, "What is the melting point of unobtainium crystals?")
    answer = text_of(events)
    assert "do not contain enough information" in answer
    assert ev(events, "citations")["citations"] == []
    ne = ev(events, "need_external")
    assert ne and "search external sources" in ne["message"] and [o["value"] for o in ne["options"]] == ["allow_once", "allow_conversation", "deny"]
    assert external_calls == []                                   # asking is not searching
    # nothing project-specific was fabricated: no digits from the project leak into a non-answer
    assert "37" not in answer

    # an empty project behaves the same way
    empty = (await mk_project(client, sci))["id"]
    e2 = await ask(client, sci, empty, "What is the incubation temperature?")
    assert ev(e2, "need_external") and external_calls == []


async def test_external_search_needs_explicit_approval_and_is_labelled(client, tokens, external_calls):
    sci = tokens["scientist"]
    pid = (await mk_project(client, sci))["id"]
    await upload_text(client, sci, pid, "Culture protocol", "Incubation temperature is 37 C. Incubate the culture for 24 hours.")
    q = "What is the boiling point of dimethyl sulfoxide?"

    # --- deny: nothing is sent anywhere
    events = await ask(client, sci, pid, q)
    chat_id, cid = ev(events, "need_external")["chat_id"], ev(events, "meta")["conversation_id"]
    r = await client.post(f"/api/projects/{pid}/chat/{chat_id}/external", headers=auth(sci), json={"decision": "deny"})
    assert r.status_code == 200 and "No external search was made" in r.json()["message"] and external_calls == []
    assert (await client.post(f"/api/projects/{pid}/chat/{chat_id}/external", headers=auth(sci), json={"decision": "allow_once"})).status_code == 409
    assert external_calls == []                                   # a decision is final for that message

    # --- allow once: exactly one call, separate labelled message, question text only
    events = await ask(client, sci, pid, q)
    chat_id = ev(events, "need_external")["chat_id"]
    r = await client.post(f"/api/projects/{pid}/chat/{chat_id}/external", headers=auth(sci), json={"decision": "allow_once"})
    assert r.status_code == 200
    ext = r.json()["external"]
    assert ext["answer"].startswith("External information (NOT from your project records")
    assert len(external_calls) == 1 and external_calls[0] == sanitize(q) and "37" not in external_calls[0] and "Culture" not in external_calls[0]
    # stored as its own 'external' message, the project answer stays what it was, and nothing was indexed
    conv_id = ev(events, "meta")["conversation_id"]
    rows = (await client.get(f"/api/chat/conversations/{conv_id}", headers=auth(sci))).json()
    assert [x["source_type"] for x in rows] == ["internal", "external"]
    assert rows[0]["meta"]["verdict"] == "insufficient" and "External" not in rows[0]["answer"] and rows[0]["sources"] == []
    with psycopg.connect(_test_url) as c:
        assert c.execute("SELECT count(*) FROM project_chunks WHERE project_id=%s AND text ILIKE '%%placeholder external%%'", (pid,)).fetchone()[0] == 0
    # one-time approval is NOT standing consent: the next gap asks again
    again = await ask(client, sci, pid, "What is the refractive index of cyclohexanol?", conv_id)
    assert ev(again, "need_external") and ev(again, "external") is None and len(external_calls) == 1

    # --- allow for this conversation only
    ne = ev(again, "need_external")["chat_id"]
    r = await client.post(f"/api/projects/{pid}/chat/{ne}/external", headers=auth(sci), json={"decision": "allow_conversation"})
    assert r.status_code == 200 and len(external_calls) == 2
    auto = await ask(client, sci, pid, "What is the density of acetonitrile?", conv_id)
    assert ev(auto, "external") and ev(auto, "need_external") is None and len(external_calls) == 3
    other = await ask(client, sci, pid, "What is the density of toluene?")           # a different conversation still asks
    assert ev(other, "need_external") and len(external_calls) == 3
    # the user can withdraw the standing permission
    assert (await client.delete(f"/api/chat/conversations/{conv_id}/memory", headers=auth(sci))).status_code == 204
    after = await ask(client, sci, pid, "What is the density of xylene?", conv_id)
    assert ev(after, "need_external") and len(external_calls) == 3


async def test_external_decision_endpoint_cannot_be_abused(client, tokens, external_calls):
    sci, ana, sen = tokens["scientist"], tokens["lab_analyst"], tokens["senior_analyst"]
    pid = (await mk_project(client, sci))["id"]
    pid2 = (await mk_project(client, sci))["id"]
    await add_member(client, sci, pid, ROLE_USERNAMES["lab_analyst"], "viewer")
    chat_id = ev(await ask(client, sci, pid, "What is the viscosity of glycerol at 20 C?"), "need_external")["chat_id"]
    body = {"decision": "allow_once"}
    assert (await client.post(f"/api/projects/{pid}/chat/{chat_id}/external", headers=auth(ana), json=body)).status_code == 404   # not their message
    assert (await client.post(f"/api/projects/{pid}/chat/{chat_id}/external", headers=auth(sen), json=body)).status_code == 404   # not a member
    assert (await client.post(f"/api/projects/{pid2}/chat/{chat_id}/external", headers=auth(sci), json=body)).status_code == 404  # wrong project
    assert (await client.post(f"/api/projects/{pid}/chat/00000000-0000-0000-0000-000000000001/external", headers=auth(sci), json=body)).status_code == 404
    assert (await client.post(f"/api/projects/{pid}/chat/{chat_id}/external", headers=auth(sci), json={"decision": "yes please"})).status_code == 422
    assert external_calls == []


async def test_conflicting_documents_are_reported_not_reconciled(client, tokens):
    sci = tokens["scientist"]
    pid = (await mk_project(client, sci))["id"]
    await upload_text(client, sci, pid, "Lab A SOP", "Storage temperature: 4 C for all buffers.")
    await upload_text(client, sci, pid, "Lab B SOP", "The storage temperature is 8 C for all buffers.")
    events = await ask(client, sci, pid, "What is the storage temperature for buffers?")
    ans = ev(events, "answer")
    assert ans["conflicts"] and {s["value"] for s in ans["conflicts"][0]["statements"]} == {4.0, 8.0}
    text = text_of(events)
    assert "Conflicting sources" in text and "Lab A SOP" in text and "Lab B SOP" in text and "not reconciled" in text
    labels = {c["label"] for c in ev(events, "citations")["citations"]}
    assert {"Lab A SOP", "Lab B SOP"} <= labels


async def test_troubleshooting_uses_recorded_numbers_and_flags_unusual_values(client, tokens):
    sci = tokens["scientist"]
    pid = (await mk_project(client, sci))["id"]
    for i, t in enumerate([36.5, 37.0, 37.2, 36.8]):
        await mk_experiment(client, sci, pid, f"GOOD-{i}", outcome="success", parameters=[{"name": "Temperature", "value": t, "unit": "C"}])
    await mk_experiment(client, sci, pid, "FAIL-9", outcome="failure", parameters=[{"name": "Temperature", "value": 45, "unit": "C"}])
    events = await ask(client, sci, pid, "Is the temperature in FAIL-9 unusual compared with earlier experiments?")
    cites = ev(events, "citations")["citations"]
    assert any(c["source_type"] == "analysis" and c["label"] == "Computed comparison for FAIL-9" for c in cites)
    text = text_of(events)
    assert "45" in text and "36.5" in text                        # numbers come from the records, not from the model
    # numeric claims that are not in the records are refused even if the 'model' invents them
    assert "99" not in text


async def test_adversarial_model_output_cannot_reach_the_user(client, tokens, monkeypatch, external_calls):
    sci = tokens["scientist"]
    pid = (await mk_project(client, sci))["id"]
    await upload_text(client, sci, pid, "Culture protocol", "Incubation temperature is 37 C. Incubate the culture for 24 hours.")

    async def liar(prompt, schema, **kw):
        return Draft(claims=[
            DraftClaim(text="The incubation temperature is 37 C.", kind="observed", cites=[1]),
            DraftClaim(text="The incubation temperature is 99 C.", kind="observed", cites=[1]),
            DraftClaim(text="The protocol was approved by Dr Smith in 2019.", kind="observed", cites=[1]),
            DraftClaim(text='The protocol states "always incubate overnight in the dark".', kind="observed", cites=[1]),
            DraftClaim(text="Contamination is certainly the cause of the failure.", kind="interpretation", cites=[]),
        ])
    monkeypatch.setattr(llm, "generate_structured", liar)
    events = await ask(client, sci, pid, "What is the incubation temperature?")
    text = text_of(events)
    assert "37" in text and "99" not in text and "Dr Smith" not in text and "overnight in the dark" not in text and "certainly" not in text
    rows = (await client.get(f"/api/chat/conversations/{ev(events, 'meta')['conversation_id']}", headers=auth(sci))).json()
    assert len(rows[0]["meta"]["rejected"]) == 4 and rows[0]["meta"]["verdict"] == "partial"

    async def nothing_valid(prompt, schema, **kw):
        return Draft(claims=[DraftClaim(text="The incubation temperature is 55 C.", kind="observed", cites=[1])])
    monkeypatch.setattr(llm, "generate_structured", nothing_valid)
    events = await ask(client, sci, pid, "What is the incubation temperature?")
    assert ev(events, "need_external") and "55" not in text_of(events) and external_calls == []


async def test_retrieval_never_crosses_projects_users_or_deleted_sources(client, tokens, uid):
    a_owner, b_owner, admin = tokens["scientist"], tokens["senior_analyst"], tokens["admin"]
    pa, pb = (await mk_project(client, a_owner))["id"], (await mk_project(client, b_owner))["id"]
    await upload_text(client, a_owner, pa, "A notes", "Project A uses the blue reactor at 20 bar.")
    secret = await upload_text(client, b_owner, pb, "B secrets", "The zebra reactor protocol sets the pressure to 77 bar.")
    await mk_experiment(client, b_owner, pb, "B-1", observations="zebra reactor leaked at 77 bar")

    # the same question in A finds nothing of B ...
    events = await ask(client, a_owner, pa, "What pressure does the zebra reactor protocol set?")
    assert ev(events, "need_external") and "77" not in text_of(events) and ev(events, "citations")["citations"] == []
    # ... and the retriever, asked directly, only ever returns rows of the project it was given
    qvec = await llm.embed_one("zebra reactor protocol pressure 77 bar")
    async with session_maker()() as s:
        for pid, expect_hits in ((pa, False), (pb, True)):
            rows = await project_retriever.retrieve(s, __import__("uuid").UUID(pid), qvec, "zebra reactor protocol pressure 77 bar")
            assert all(str(r["project_id"]) == pid for r in rows)
            assert any("zebra" in r["text"] for r in rows) is expect_hits
    # non-members (including an admin) cannot even open the stream
    for tok in (a_owner, admin):
        async with client.stream("POST", f"/api/projects/{pb}/chat/stream", headers=auth(tok), json={"question": "zebra reactor pressure"}) as r:
            assert r.status_code == 404
    # a conversation id from project A cannot be reused inside project B (or by someone else)
    cid = ev(events, "meta")["conversation_id"]
    cross = await ask(client, b_owner, pb, "zebra reactor", cid)
    assert ev(cross, "error")["message"] == "Conversation not found"
    cross2 = await ask(client, a_owner, pa, "blue reactor", None)
    other_user = await ask(client, a_owner, pa, "blue reactor pressure", ev(cross2, "meta")["conversation_id"])
    assert ev(other_user, "error") is None
    # deleting the source removes it from what the assistant can use
    ok = await ask(client, b_owner, pb, "What pressure does the zebra reactor protocol set?")
    assert ev(ok, "citations")["citations"] and "77" in text_of(ok)
    assert (await client.delete(f"/api/projects/{pb}/documents/{secret['id']}", headers=auth(b_owner))).status_code == 204
    after = await ask(client, b_owner, pb, "What pressure does the zebra reactor protocol set?")
    assert all(c["source_type"] == "experiment" for c in ev(after, "citations")["citations"])      # only the experiment record remains
    exp = (await client.get(f"/api/projects/{pb}/experiments", headers=auth(b_owner))).json()["items"][0]
    await client.delete(f"/api/projects/{pb}/experiments/{exp['id']}?reason=cleanup%20test", headers=auth(b_owner))
    gone = await ask(client, b_owner, pb, "What pressure does the zebra reactor protocol set?")
    assert ev(gone, "need_external") and "77" not in text_of(gone)
