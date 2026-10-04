"""Runs the app for scripts/preview.sh, and only for it: every request is
presented to the app as if a TLS-terminating proxy had forwarded it.

The app is read-only over plain HTTP and its session cookie is Secure, both on
purpose, so a preview opened straight at http://host:8099 could be looked at
but not signed in to or used. Loosening that in the app would ship the
loosening. This wrapper is not in the image (the Dockerfile copies backend/ and
frontend/ only); preview.sh mounts it into the throwaway container and starts
it instead of backend.serve. With TRUST_PROXY_HEADERS=true the app then
believes the X-Forwarded-Proto set here, and COOKIE_SECURE=false lets the
browser keep the cookie on a plain-HTTP origin.

Never use this in front of real captures: it tells the app the wire is
encrypted when it is not.
"""
from __future__ import annotations

import uvicorn

from backend import main


class AsHttps:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] in ("http", "websocket"):
            headers = [(k, v) for k, v in scope["headers"] if k != b"x-forwarded-proto"]
            headers.append((b"x-forwarded-proto", b"https"))
            scope = dict(scope, headers=headers)
        await self.app(scope, receive, send)


if __name__ == "__main__":
    uvicorn.run(AsHttps(main.app), host="0.0.0.0", port=8080)
