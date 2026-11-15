"""
Points redirects the proxy builds from the request's own Host at PROXY_BASE_URL instead.

Starlette's trailing-slash redirects (and any other redirect built from request.url) use the Host header the
proxy received. Behind a reverse proxy that rewrites Host to an internal address, the browser is then sent to a
host it cannot reach. Only redirects back to the request's own host are rewritten, so redirects to an identity
provider or any other site pass through untouched.
"""

from collections.abc import Callable
from typing import Final
from urllib.parse import SplitResult, urlsplit, urlunsplit

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from litellm.proxy.utils import get_proxy_base_url


def _public_origin(public_base_url: str | None) -> SplitResult | None:
    if public_base_url is None:
        return None
    parsed: Final = urlsplit(public_base_url.strip())
    if parsed.scheme not in ("http", "https") or parsed.netloc == "":
        return None
    return parsed


def rewrite_location(location: str, request_host: str | None, public_origin: SplitResult) -> str:
    target: Final = urlsplit(location)
    if request_host is None or target.netloc.lower() != request_host.lower():
        return location
    return urlunsplit((public_origin.scheme, public_origin.netloc, target.path, target.query, target.fragment))


class PublicRedirectMiddleware:
    def __init__(self, app: ASGIApp, public_base_url: Callable[[], str | None] = get_proxy_base_url) -> None:
        self.app = app
        self.public_base_url = public_base_url

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        public_origin: Final = _public_origin(self.public_base_url()) if scope["type"] == "http" else None
        if public_origin is None:
            await self.app(scope, receive, send)
            return

        request_host: Final = Headers(scope=scope).get("host")

        async def send_with_public_location(message: Message) -> None:
            if message["type"] == "http.response.start" and 300 <= message["status"] < 400:
                headers: Final = MutableHeaders(scope=message)
                location: Final = headers.get("location")
                if location is not None:
                    headers["location"] = rewrite_location(location, request_host, public_origin)
            await send(message)

        await self.app(scope, receive, send_with_public_location)
