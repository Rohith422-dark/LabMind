"""12.1 Project management: ownership, password workflow, collaborator roles, revocation, IDOR."""
import psycopg
from sqlalchemy import text

from app.db import session_maker
from tests.conftest import _test_url, auth
from tests.util import add_member, mk_experiment, mk_project, ROLE_USERNAMES, upload_text, uid  # noqa: F401

PW = "correct horse battery"


async def test_create_and_manage_project(client, tokens):
    sci = tokens["scientist"]
    p = await mk_project(client, sci, password=PW)
    assert p["role"] == "owner" and p["has_password"] is True and p["members"] == 1
    # secrets never leave the server
    body = (await client.get(f"/api/projects/{p['id']}", headers=auth(sci))).text
    assert "password_hash" not in body and PW not in body and "argon2" not in body

    r = await client.patch(f"/api/projects/{p['id']}", headers=auth(sci), json={"name": "Renamed", "tags": ["a", " b "]})
    assert r.status_code == 200 and r.json()["name"] == "Renamed" and r.json()["tags"] == ["a", "b"]
    assert any(x["id"] == p["id"] for x in (await client.get("/api/projects", headers=auth(sci))).json())

    # stored as an argon2id hash, not plaintext
    async with session_maker()() as s:
        h = (await s.execute(text("SELECT password_hash FROM projects WHERE id=:i"), {"i": p["id"]})).scalar_one()
    assert h.startswith("$argon2id$") and PW not in h

    # archive makes it read-only for writes, restore reverses it
    assert (await client.post(f"/api/projects/{p['id']}/archive", headers=auth(sci))).json()["archived"] is True
    r = await client.post(f"/api/projects/{p['id']}/experiments", headers=auth(sci), json={"identifier": "E1", "title": "x"})
    assert r.status_code == 409
    assert all(x["id"] != p["id"] for x in (await client.get("/api/projects", headers=auth(sci))).json())
    assert (await client.post(f"/api/projects/{p['id']}/restore", headers=auth(sci))).json()["archived"] is False

    # password can be cleared and re-set; validation rejects short passwords
    assert (await client.put(f"/api/projects/{p['id']}/password", headers=auth(sci), json={"password": "short"})).status_code == 422
    assert (await client.delete(f"/api/projects/{p['id']}/password", headers=auth(sci))).status_code == 204
    assert (await client.get(f"/api/projects/{p['id']}", headers=auth(sci))).json()["has_password"] is False


async def test_password_alone_never_grants_access(client, tokens, uid):
    owner, ana = tokens["scientist"], tokens["lab_analyst"]
    p = await mk_project(client, owner, password=PW)
    pid = p["id"]

    # outsiders cannot see that the project exists
    assert (await client.get(f"/api/projects/{pid}", headers=auth(ana))).status_code == 404
    assert pid not in [x["id"] for x in (await client.get("/api/projects", headers=auth(ana))).json()]

    # wrong password: one generic 403, nothing created
    bad = await client.post(f"/api/projects/{pid}/access-requests", headers=auth(ana), json={"password": "nope nope nope"})
    assert bad.status_code == 403 and "password" in bad.json()["detail"].lower()

    # right password: only a PENDING request exists - access is still denied
    ok = await client.post(f"/api/projects/{pid}/access-requests", headers=auth(ana), json={"password": PW, "message": "please"})
    assert ok.status_code == 201 and ok.json()["status"] == "pending"
    assert (await client.get(f"/api/projects/{pid}", headers=auth(ana))).status_code == 404
    assert (await client.get(f"/api/projects/{pid}/experiments", headers=auth(ana))).status_code == 404
    # duplicate pending request is refused
    assert (await client.post(f"/api/projects/{pid}/access-requests", headers=auth(ana), json={"password": PW})).status_code == 409

    # the owner is notified, sees the request, and only the owner can decide
    reqs = (await client.get(f"/api/projects/{pid}/access-requests", headers=auth(owner))).json()
    assert len(reqs) == 1 and reqs[0]["user_id"] == uid["lab_analyst"]
    assert (await client.get(f"/api/projects/{pid}/access-requests", headers=auth(ana))).status_code == 404
    assert (await client.post(f"/api/projects/{pid}/access-requests/{reqs[0]['id']}/decision", headers=auth(ana),
                              json={"approve": True, "role": "editor"})).status_code == 404
    notes = (await client.get("/api/notifications", headers=auth(owner))).json()
    assert any("asked for access" in n["message"] for n in notes)

    d = await client.post(f"/api/projects/{pid}/access-requests/{reqs[0]['id']}/decision", headers=auth(owner),
                          json={"approve": True, "role": "viewer"})
    assert d.status_code == 200 and d.json()["status"] == "approved"
    assert (await client.get(f"/api/projects/{pid}", headers=auth(ana))).json()["role"] == "viewer"
    # deciding twice is a conflict
    assert (await client.post(f"/api/projects/{pid}/access-requests/{reqs[0]['id']}/decision", headers=auth(owner),
                              json={"approve": False})).status_code == 409


async def test_no_password_means_no_access_request_and_lockout(client, tokens):
    owner, sen = tokens["scientist"], tokens["senior_analyst"]
    open_p = await mk_project(client, owner)           # no password configured
    r = await client.post(f"/api/projects/{open_p['id']}/access-requests", headers=auth(sen), json={"password": "anything-at-all"})
    assert r.status_code == 403
    # unknown project id answers identically (no enumeration)
    r2 = await client.post("/api/projects/00000000-0000-0000-0000-000000000099/access-requests", headers=auth(sen),
                           json={"password": "anything-at-all"})
    assert r2.status_code == 403 and r2.json() == r.json()

    p = await mk_project(client, owner, password=PW)
    for _ in range(5):
        assert (await client.post(f"/api/projects/{p['id']}/access-requests", headers=auth(sen), json={"password": "wrong-wrong"})).status_code == 403
    # locked: even the correct password is refused (identical response) until the lock expires
    r = await client.post(f"/api/projects/{p['id']}/access-requests", headers=auth(sen), json={"password": PW})
    assert r.status_code == 403
    assert (await client.get(f"/api/projects/{p['id']}", headers=auth(sen))).status_code == 404


async def test_collaborator_permissions_and_revocation(client, tokens, uid):
    owner, viewer, editor = tokens["scientist"], tokens["lab_analyst"], tokens["senior_analyst"]
    p = await mk_project(client, owner)
    pid = p["id"]
    await add_member(client, owner, pid, ROLE_USERNAMES["lab_analyst"], "viewer")
    await add_member(client, owner, pid, ROLE_USERNAMES["senior_analyst"], "editor")
    assert (await client.post(f"/api/projects/{pid}/members", headers=auth(owner),
                              json={"username": ROLE_USERNAMES["lab_analyst"], "role": "editor"})).status_code == 409

    # viewer: read yes, write no
    assert (await client.get(f"/api/projects/{pid}/experiments", headers=auth(viewer))).status_code == 200
    assert (await client.post(f"/api/projects/{pid}/experiments", headers=auth(viewer), json={"identifier": "V1", "title": "x"})).status_code == 403
    assert (await client.post(f"/api/projects/{pid}/documents", headers=auth(viewer),
                              files={"file": ("a.txt", b"hello world text")})).status_code == 403
    # editor: can write, cannot administer
    assert (await client.post(f"/api/projects/{pid}/experiments", headers=auth(editor), json={"identifier": "E1", "title": "x"})).status_code == 201
    for method, path, body in (("PATCH", f"/api/projects/{pid}", {"name": "hijack"}),
                               ("PUT", f"/api/projects/{pid}/password", {"password": "hijack-password"}),
                               ("POST", f"/api/projects/{pid}/archive", None),
                               ("POST", f"/api/projects/{pid}/members", {"username": "t_admin", "role": "viewer"}),
                               ("PATCH", f"/api/projects/{pid}/members/{uid['lab_analyst']}", {"role": "editor"})):
        r = await client.request(method, path, headers=auth(editor), json=body)
        assert r.status_code == 403, (method, path, r.status_code)
        assert (await client.request(method, path, headers=auth(viewer), json=body)).status_code == 403
    assert (await client.delete(f"/api/projects/{pid}?confirm_name={p['name']}", headers=auth(editor))).status_code == 403
    # a non-owner cannot remove somebody else
    assert (await client.delete(f"/api/projects/{pid}/members/{uid['senior_analyst']}", headers=auth(viewer))).status_code == 403

    # owner revokes the editor -> immediately locked out of everything
    assert (await client.delete(f"/api/projects/{pid}/members/{uid['senior_analyst']}", headers=auth(owner))).status_code == 204
    for path in (f"/api/projects/{pid}", f"/api/projects/{pid}/experiments", f"/api/projects/{pid}/documents",
                 f"/api/projects/{pid}/memory"):
        assert (await client.get(path, headers=auth(editor))).status_code == 404, path
    assert (await client.post(f"/api/projects/{pid}/experiments", headers=auth(editor), json={"identifier": "E2", "title": "x"})).status_code == 404
    # ... and was told
    assert any("revoked" in n["message"] for n in (await client.get("/api/notifications", headers=auth(editor))).json())
    # the owner cannot be removed or demoted
    assert (await client.delete(f"/api/projects/{pid}/members/{uid['scientist']}", headers=auth(owner))).status_code == 409
    assert (await client.patch(f"/api/projects/{pid}/members/{uid['scientist']}", headers=auth(owner), json={"role": "viewer"})).status_code == 409
    # a member may leave
    assert (await client.delete(f"/api/projects/{pid}/members/{uid['lab_analyst']}", headers=auth(viewer))).status_code == 204
    assert (await client.get(f"/api/projects/{pid}", headers=auth(viewer))).status_code == 404


async def test_resource_ids_cannot_be_swapped_across_projects(client, tokens):
    """IDOR: knowing (or guessing) another project's document / experiment id must never work, even for a member of
    *another* project, an admin, or via the owner's own second project."""
    a_owner, b_owner, admin = tokens["scientist"], tokens["senior_analyst"], tokens["admin"]
    pa = await mk_project(client, a_owner)
    pb = await mk_project(client, b_owner)
    exp_a = await mk_experiment(client, a_owner, pa["id"], "A-1", parameters=[{"name": "pH", "value": 7.1}])
    doc_a = await upload_text(client, a_owner, pa["id"], "Secret protocol", "The secret protocol temperature is 99 C.")

    for token in (b_owner, admin):                      # not members of project A
        for path in (f"/api/projects/{pa['id']}/experiments/{exp_a['id']}", f"/api/projects/{pa['id']}/documents/{doc_a['id']}",
                     f"/api/projects/{pa['id']}/documents/{doc_a['id']}/content", f"/api/projects/{pa['id']}/documents/{doc_a['id']}/file",
                     f"/api/projects/{pa['id']}/experiments/{exp_a['id']}/versions"):
            assert (await client.get(path, headers=auth(token))).status_code == 404, path

    # member of B, but the ids belong to A: the project in the URL scopes the lookup
    for path in (f"/api/projects/{pb['id']}/experiments/{exp_a['id']}", f"/api/projects/{pb['id']}/documents/{doc_a['id']}",
                 f"/api/projects/{pb['id']}/documents/{doc_a['id']}/content", f"/api/projects/{pb['id']}/experiments/{exp_a['id']}/analysis"):
        assert (await client.get(path, headers=auth(b_owner))).status_code == 404, path
    assert (await client.patch(f"/api/projects/{pb['id']}/experiments/{exp_a['id']}", headers=auth(b_owner),
                               json={"expected_version": 1, "title": "pwn"})).status_code == 404
    assert (await client.delete(f"/api/projects/{pb['id']}/documents/{doc_a['id']}", headers=auth(b_owner))).status_code == 404
    # cross-project links / attachments are refused at write time
    exp_b = await mk_experiment(client, b_owner, pb["id"], "B-1")
    r = await client.patch(f"/api/projects/{pb['id']}/experiments/{exp_b['id']}", headers=auth(b_owner),
                           json={"expected_version": 1, "links": [{"experiment_id": exp_a["id"], "relation": "related"}]})
    assert r.status_code == 422
    r = await client.patch(f"/api/projects/{pb['id']}/experiments/{exp_b['id']}", headers=auth(b_owner),
                           json={"expected_version": 1, "attachments": [doc_a["id"]]})
    assert r.status_code == 422
    assert (await client.get(f"/api/projects/{pb['id']}/experiments/{exp_b['id']}/compare?with={exp_a['id']}", headers=auth(b_owner))).status_code == 404
    # nothing of A was touched
    assert (await client.get(f"/api/projects/{pa['id']}/experiments/{exp_a['id']}", headers=auth(a_owner))).json()["title"] == exp_a["title"]


async def test_delete_project_cascades_everything(client, tokens):
    owner = tokens["scientist"]
    p = await mk_project(client, owner, name="Doomed project")
    pid = p["id"]
    exp = await mk_experiment(client, owner, pid, "D-1", observations="turbid sample")
    await client.patch(f"/api/projects/{pid}/experiments/{exp['id']}", headers=auth(owner), json={"expected_version": 1, "results": "ok"})
    doc = await upload_text(client, owner, pid, "Doomed doc", "Some retrievable content about incubation.")
    from app.services import project_docs
    from tests.conftest import ROLE_USERNAMES  # noqa: F401
    assert (await client.delete(f"/api/projects/{pid}?confirm_name=wrong", headers=auth(owner))).status_code == 422
    assert (await client.delete(f"/api/projects/{pid}?confirm_name=Doomed project", headers=auth(owner))).status_code == 204
    with psycopg.connect(_test_url) as c:
        for table in ("project_chunks", "experiments", "experiment_versions", "project_documents", "project_members", "memories"):
            col = "project_id"
            assert c.execute(f"SELECT count(*) FROM {table} WHERE {col} = %s", (pid,)).fetchone()[0] == 0, table
        assert c.execute("SELECT count(*) FROM audit_log WHERE action='project_deleted' AND target=%s", (pid,)).fetchone()[0] == 1
    import uuid
    assert not (project_docs._root() / "projects" / pid).exists()
    assert (await client.get(f"/api/projects/{pid}", headers=auth(owner))).status_code == 404
    del doc, uuid
