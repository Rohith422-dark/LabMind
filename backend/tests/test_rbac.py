import re
import uuid

import pytest
from fastapi.routing import APIRoute

from app.main import app
from app.routers import ROUTERS
from app.permissions import PERMISSIONS, ROLES
from tests.conftest import auth

# The ONLY routes that may be reachable without a permission dependency.
PUBLIC = {
    ("GET", "/api/health"),
    ("POST", "/api/auth/login"),
    ("GET", "/api/auth/demo-users"),   # names/roles only, for login cards
    ("POST", "/api/auth/demo-login"),  # 404 unless DEMO_MODE=1
}
ZERO = str(uuid.UUID(int=0))


def _permission_of(route) -> str | None:
    def walk(dep):
        p = getattr(dep.call, "_permission", None)
        if p:
            return p
        for sub in dep.dependencies:
            r = walk(sub)
            if r:
                return r
        return None
    return walk(route.dependant)


def _api_routes() -> list[tuple[str, APIRoute]]:
    """Walk the routers main.py mounts (FastAPI wraps included routers lazily, so app.routes
    is not flat). Cross-checked against the live OpenAPI paths in test_routes_match_openapi."""
    out = []
    for router in ROUTERS:
        for r in router.routes:
            if isinstance(r, APIRoute):
                for m in sorted(r.methods - {"HEAD", "OPTIONS"}):
                    out.append((m, _Prefixed(r)))
    return out


class _Prefixed:
    """APIRoute view with the /api prefix applied."""
    def __init__(self, route: APIRoute):
        self._r = route
        self.path = "/api" + route.path
        self.dependant = route.dependant


def test_routes_match_openapi():
    found = {r.path for _, r in _api_routes()}
    assert found, "no routes discovered - route walker is broken"
    assert found == set(app.openapi()["paths"].keys())


def test_every_route_declares_a_permission():
    missing = [f"{m} {r.path}" for m, r in _api_routes()
               if (m, r.path) not in PUBLIC and _permission_of(r) is None]
    assert not missing, f"routes without require(...): {missing}"


def test_public_list_is_not_stale():
    existing = {(m, r.path) for m, r in _api_routes()}
    assert PUBLIC <= existing


async def test_role_matrix(client, tokens):
    rows = []
    failures = []
    for m, r in _api_routes():
        if (m, r.path) in PUBLIC:
            continue
        perm = _permission_of(r)
        allowed = set(PERMISSIONS[perm])
        path = re.sub(r"\{[^}]+\}", ZERO, r.path)

        async def call(headers):
            return (await client.request(m, path, headers=headers, json={} if m != "GET" else None)).status_code

        no_token = await call({})
        if no_token != 401:
            failures.append(f"{m} {r.path}: no token -> {no_token}, expected 401")
        cells = []
        for role in ROLES:
            code = await call(auth(tokens[role]))
            if role in allowed:
                ok = code not in (401, 403)
            else:
                ok = code == 403
            cells.append(f"{code}{'' if ok else '!'}")
            if not ok:
                failures.append(f"{m} {r.path} as {role}: got {code} (allowed={role in allowed})")
        rows.append((f"{m} {r.path}", perm, no_token, *cells))

    header = ("route", "permission", "none", *ROLES)
    widths = [max(len(str(x[i])) for x in [header, *rows]) for i in range(len(header))]
    print()
    for row in [header, *rows]:
        print("  ".join(str(c).ljust(w) for c, w in zip(row, widths)))
    assert not failures, "\n".join(failures)
