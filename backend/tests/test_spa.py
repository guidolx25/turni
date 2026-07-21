"""§9: the built frontend is served by the API process, from the same origin.

The image builds `frontend/` into `STATIC_DIR` and `app.main.create_app` mounts
it. Before this existed the Dockerfile built the SPA, copied it to /app/static,
set STATIC_DIR — and nothing read the variable, so `GET /` was a 404 and the
"single origin, therefore no CORS" premise in the deploy doc was not true of the
running code.

Since §7 v1.11 the API lives under `/api`, so the split this module implements is
a prefix and nothing more: `/api/*` is the API, everything else is the client's.
The tests below are written to fail if that ever stops being true in either
direction — an API path quietly serving HTML, or a client route quietly serving
JSON. The second is what the previous `Accept`-header scheme got wrong.

A fixture build directory is used rather than the real `frontend/dist`, so the
suite does not require `npm run build` to have been run.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

pytestmark = pytest.mark.phase6

# Enough of a Vite build to be recognisable: the shell the smoke test greps for.
INDEX_HTML = """<!doctype html>
<html lang="it">
  <head><title>Turni</title></head>
  <body><div id="root"></div><script type="module" src="/assets/index-abc123.js"></script></body>
</html>
"""

# Every §9 client route, including the five that used to collide with an API
# name. They are ordinary paths now; the point of the list is that none of them
# is special-cased anywhere in the server.
CLIENT_ROUTES = [
    "/",
    "/login",
    "/swaps",
    "/constraints",
    "/notifications",
    "/settings",
    "/admin",
    "/root",
]


@pytest.fixture
def static_dir(tmp_path: Path) -> Path:
    """A minimal built frontend: index.html, a hashed asset, a root-level file."""
    build = tmp_path / "static"
    (build / "assets").mkdir(parents=True)
    (build / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    (build / "assets" / "index-abc123.js").write_text("console.log('turni')", encoding="utf-8")
    (build / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    return build


@pytest.fixture
def client(static_dir: Path) -> TestClient:
    """The real app — every router registered — with the SPA mounted.

    `create_app` rather than the module-global `app`: `mount_spa` installs a
    catch-all, and adding one to the shared instance would turn every other
    suite's unknown-path 404s into HTML.
    """
    return TestClient(create_app(static_dir=static_dir))


# --- the client half --------------------------------------------------------


@pytest.mark.parametrize("path", CLIENT_ROUTES)
def test_every_client_route_serves_the_spa_shell(client: TestClient, path: str) -> None:
    """Deep links and refreshes. Each of these has no file behind it, so without
    the history fallback every reload outside `/` is a 404.

    `/swaps`, `/constraints`, `/notifications`, `/admin` and `/root` are the
    interesting rows: each shares a name with an API namespace, and each is now
    unambiguously the client's because the API moved under /api.
    """
    response = client.get(path)

    assert response.status_code == 200
    assert '<div id="root"' in response.text
    assert response.headers["content-type"].startswith("text/html")


@pytest.mark.parametrize("path", CLIENT_ROUTES)
def test_client_routes_do_not_depend_on_the_accept_header(client: TestClient, path: str) -> None:
    """The regression guard for the scheme this replaced.

    Routing used to be decided by `Accept`, which made it dependent on a header
    any proxy or CDN in the path is free to rewrite — a deployment could break
    deep links without a line of code changing. A client route must now serve the
    shell no matter what the caller claims to accept, including `application/json`.
    """
    response = client.get(path, headers={"Accept": "application/json"})

    assert response.status_code == 200
    assert '<div id="root"' in response.text


def test_a_nested_client_path_serves_the_spa_shell(client: TestClient) -> None:
    """`App.tsx` declares only depth-1 routes plus a `*` redirect to `/`, so this
    has no client route either — the shell is still right, because the redirect
    that sends the user home lives *in* the shell."""
    response = client.get("/settings/profile/whatever")

    assert response.status_code == 200
    assert '<div id="root"' in response.text


# --- the API half -----------------------------------------------------------


def test_an_unknown_api_path_returns_a_json_404(client: TestClient) -> None:
    """A removed or mistyped API path must keep the API's error shape. Serving
    HTML here surfaces in a client as a JSON parse error, not as the 404 it is."""
    response = client.get("/api/nonexistent")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"detail": "Not Found"}


def test_a_deep_unknown_api_path_returns_a_json_404(client: TestClient) -> None:
    """Depth is irrelevant: everything under /api belongs to the API."""
    response = client.get("/api/admin/definitely-not-an-endpoint")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")


def test_the_bare_api_prefix_is_not_a_client_route(client: TestClient) -> None:
    """`/api` itself is no one's page — it must not fall through to the shell."""
    response = client.get("/api")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")


def test_a_real_api_route_still_answers_under_the_prefix(client: TestClient) -> None:
    """The migration itself: /api/swaps reaches the endpoint. 401 rather than 200
    because this fixture carries no session — which is the point, since it proves
    the request reached the API's auth rather than the static handler."""
    response = client.get("/api/swaps")

    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/json")


def test_the_unprefixed_api_path_is_gone(client: TestClient) -> None:
    """The old URL must not still work. A surviving duplicate would be a second,
    undocumented API surface that no test or doc describes."""
    response = client.get("/swaps", headers={"Accept": "application/json"})

    assert response.status_code == 200
    assert '<div id="root"' in response.text, "/swaps must now be the client route, not the API"


# --- the safety net ---------------------------------------------------------


def test_healthz_is_not_shadowed_by_the_fallback(client: TestClient) -> None:
    """§11 puts the health endpoint outside /api on purpose, so it is exactly the
    kind of root-level route the reserved-segment net exists to protect."""
    response = client.get("/healthz")

    assert response.json() == {"status": "ok"}
    assert response.headers["content-type"].startswith("application/json")


def test_the_api_docs_are_not_shadowed_by_the_fallback(client: TestClient) -> None:
    """`/docs` and `/openapi.json` are FastAPI's own and appear in no router, so
    they cannot be discovered from the route table."""
    assert client.get("/openapi.json").status_code == 200
    assert '<div id="root"' not in client.get("/docs").text


def test_a_route_mounted_outside_the_api_prefix_keeps_its_json_404(static_dir: Path) -> None:
    """The net, stated directly.

    The prefix check is the mechanism; this is what catches a future router that
    is mounted outside /api by mistake. Without it such a router's 404s would
    silently become HTML — the failure mode that is hardest to notice, because
    every successful request still looks fine.
    """
    from fastapi import APIRouter

    from app.spa import api_segments

    app = create_app(static_dir=static_dir)
    router = APIRouter()

    @router.get("/stray/thing")
    def _thing() -> dict[str, str]:
        return {}

    app.include_router(router)
    app.openapi_schema = None  # force a rebuild; FastAPI caches the schema

    assert "stray" in api_segments(app)


def test_openapi_documents_only_prefixed_paths() -> None:
    """Every documented route lives under /api except the health endpoint.

    This is the assertion that would fail if a future router were added to
    `create_app` outside the `api` group — which is the mistake the net above
    only mitigates.
    """
    from app.config import API_PREFIX

    app = create_app(static_dir=None)
    documented = set(app.openapi()["paths"])
    stray = {p for p in documented if not p.startswith(f"{API_PREFIX}/") and p != "/healthz"}

    assert not stray, f"routes outside {API_PREFIX} and not /healthz: {sorted(stray)}"


def test_the_ics_feed_is_under_the_api_prefix() -> None:
    """Workers paste this URL into a calendar app, so where it lives is a
    user-facing decision, recorded here: it is §7 API surface and follows the
    prefix. `/healthz` is the only root exception, because the host probes it."""
    app = create_app(static_dir=None)

    assert "/api/export/ics" in app.openapi()["paths"]


# --- static assets ----------------------------------------------------------


def test_hashed_assets_are_served(client: TestClient) -> None:
    """The bundle itself, via the StaticFiles mount rather than the fallback."""
    response = client.get("/assets/index-abc123.js")

    assert response.status_code == 200
    assert "console.log('turni')" in response.text


def test_a_missing_asset_is_a_404_not_the_shell(client: TestClient) -> None:
    """A mistyped bundle must fail, not return HTML: a <script> tag served an
    HTML body is a syntax error at parse time, miles from the real cause."""
    assert client.get("/assets/index-does-not-exist.js").status_code == 404


def test_a_root_level_static_file_is_served(client: TestClient) -> None:
    """index.html references /favicon.svg, which is not under /assets."""
    response = client.get("/favicon.svg")

    assert response.status_code == 200
    assert "<svg/>" in response.text


def test_the_fallback_refuses_to_traverse_out_of_the_build_directory(
    client: TestClient, tmp_path: Path
) -> None:
    """The fallback resolves a candidate file from a client-supplied path, so it
    must not be able to escape STATIC_DIR."""
    (tmp_path / "secret.txt").write_text("not for the internet", encoding="utf-8")

    response = client.get("/../secret.txt")

    assert "not for the internet" not in response.text


# --- degraded configurations ------------------------------------------------


def test_no_frontend_configured_leaves_the_api_intact() -> None:
    """Dev and test run with STATIC_DIR unset: no fallback, and an unknown path
    stays a JSON 404 rather than becoming HTML."""
    client = TestClient(create_app(static_dir=None))

    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/definitely-nothing").status_code == 404


def test_a_static_dir_without_a_build_does_not_break_the_api(tmp_path: Path) -> None:
    """A broken image (STATIC_DIR set, nothing built into it) must still serve the
    API — refusing to boot would take a deployment down over a frontend problem."""
    client = TestClient(create_app(static_dir=tmp_path))

    assert client.get("/healthz").json() == {"status": "ok"}


# --- the client route table -------------------------------------------------


def test_client_routes_match_the_frontend_route_table() -> None:
    """`CLIENT_ROUTES` mirrors `frontend/src/App.tsx`.

    Nothing at runtime depends on this list any more — that is the improvement
    the prefix bought. It is still checked, because these are the paths the
    fallback tests claim to cover, and a view added to App.tsx that no test
    exercises would otherwise go unnoticed.
    """
    app_tsx = Path(__file__).resolve().parents[2] / "frontend" / "src" / "App.tsx"
    declared = set(re.findall(r'<Route\s+path="([^"*]+)"', app_tsx.read_text(encoding="utf-8")))
    declared.add("/")  # `<Route index>` carries no path of its own.

    assert declared == set(CLIENT_ROUTES)
