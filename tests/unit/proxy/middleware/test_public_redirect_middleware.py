from typing import Final

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse, RedirectResponse, Response
from starlette.routing import Mount, Route
from starlette.testclient import TestClient

from litellm.proxy.middleware.public_redirect_middleware import PublicRedirectMiddleware

INTERNAL_HOST: Final = "litellm.internal.example.net"


async def _ok(request: Request) -> Response:
    return PlainTextResponse("ok")


async def _to_identity_provider(request: Request) -> Response:
    return RedirectResponse("https://auth.example.org/realms/x/auth?client_id=litellm", status_code=302)


def _client(public_base_url: str | None) -> TestClient:
    app: Final = Starlette(
        routes=[
            Route("/sso/key/generate", _ok),
            Route("/login", _to_identity_provider),
            Mount("/ui", routes=[Route("/", _ok)]),
        ]
    )
    app.add_middleware(PublicRedirectMiddleware, public_base_url=lambda: public_base_url)
    return TestClient(app, base_url=f"http://{INTERNAL_HOST}", follow_redirects=False)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/sso/key/generate/?redirect_to=%2Fui%2F", "https://llm.example.org/sso/key/generate?redirect_to=%2Fui%2F"),
        ("/ui", "https://llm.example.org/ui/"),
    ],
)
def test_slash_redirect_goes_to_public_base_url(path: str, expected: str) -> None:
    response: Final = _client("https://llm.example.org").get(path)

    assert response.status_code == 307
    assert response.headers["location"] == expected


def test_redirect_to_another_host_is_untouched() -> None:
    response: Final = _client("https://llm.example.org").get("/login")

    assert response.headers["location"] == "https://auth.example.org/realms/x/auth?client_id=litellm"


@pytest.mark.parametrize("public_base_url", [None, "", "llm.example.org"])
def test_without_a_usable_public_base_url_redirects_are_untouched(public_base_url: str | None) -> None:
    response: Final = _client(public_base_url).get("/ui")

    assert response.headers["location"] == f"http://{INTERNAL_HOST}/ui/"
