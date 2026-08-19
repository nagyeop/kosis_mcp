"""HTTP ASGI app — Streamable HTTP + health/auth/rate-limit."""

from __future__ import annotations

import hmac
import os
import re
import time
from collections import defaultdict

from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from kosis_mcp.config import SERVER_VERSION, TOOL_COUNT
from kosis_mcp.server import mcp


def scrub(s: str) -> str:
    return re.sub(
        r"(apiKey|kosis_api_key)=[^&\s]+",
        r"\1=***",
        s,
        flags=re.I,
    )


class AccessLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if os.environ.get("ACCESS_LOG") == "1":
            print(
                f"[access] {request.method} {request.url.path} "
                f'ip={request.client.host if request.client else "-"} '
                f'ua="{request.headers.get("user-agent", "-")}"',
                flush=True,
            )
        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, rpm: int = 60):
        super().__init__(app)
        self.rpm = rpm
        self.buckets: dict[str, dict[str, float]] = {}

    async def dispatch(self, request: Request, call_next):
        if self.rpm <= 0 or request.url.path in ("/health", "/"):
            return await call_next(request)
        ip = request.client.host if request.client else "unknown"
        now = time.time()
        b = self.buckets.get(ip)
        if not b or now >= b["resetAt"]:
            b = {"count": 0, "resetAt": now + 60}
            self.buckets[ip] = b
        b["count"] += 1
        # GC occasionally
        if len(self.buckets) > 5000:
            for k, v in list(self.buckets.items()):
                if now >= v["resetAt"]:
                    del self.buckets[k]
        if b["count"] > self.rpm:
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "error": {
                        "code": -32000,
                        "message": f"Rate limit exceeded ({self.rpm} rpm)",
                    },
                    "id": None,
                },
                status_code=429,
            )
        return await call_next(request)


class BearerAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, token: str):
        super().__init__(app)
        self.token = token

    async def dispatch(self, request: Request, call_next):
        if request.url.path != "/mcp" or request.method != "POST":
            return await call_next(request)
        auth = request.headers.get("authorization") or ""
        token = auth[7:] if auth.startswith("Bearer ") else ""
        a = token.encode()
        b = self.token.encode()
        if len(a) != len(b) or not hmac.compare_digest(a, b):
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "error": {"code": -32001, "message": "Unauthorized"},
                    "id": None,
                },
                status_code=401,
            )
        return await call_next(request)


@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Request) -> Response:
    return JSONResponse(
        {
            "status": "ok",
            "name": "kosis-mcp",
            "version": SERVER_VERSION,
            "tools": TOOL_COUNT,
        }
    )


@mcp.custom_route("/", methods=["GET"])
async def root(_request: Request) -> Response:
    return JSONResponse(
        {
            "name": "kosis-mcp",
            "version": SERVER_VERSION,
            "description": "KOSIS FastMCP — 92 keywords + district routing",
            "endpoint": "/mcp (POST)",
            "tools": TOOL_COUNT,
        }
    )


def create_http_app():
    cors_origin = os.environ.get("MCP_CORS_ORIGIN", "*")
    rpm = int(os.environ.get("RATE_LIMIT_RPM", "60"))
    auth_token = os.environ.get("MCP_AUTH_TOKEN", "")

    middleware = [
        Middleware(AccessLogMiddleware),
        Middleware(RateLimitMiddleware, rpm=rpm),
        Middleware(
            CORSMiddleware,
            allow_origins=[cors_origin] if cors_origin != "*" else ["*"],
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=["Content-Type", "mcp-session-id", "Authorization"],
            expose_headers=["mcp-session-id"],
        ),
    ]
    if auth_token:
        middleware.insert(1, Middleware(BearerAuthMiddleware, token=auth_token))

    return mcp.http_app(
        path="/mcp",
        stateless_http=True,
        middleware=middleware,
    )


app = create_http_app()
