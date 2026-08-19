"""Vercel ASGI entrypoint — re-exports the FastMCP HTTP app."""

from kosis_mcp.http_app import app

__all__ = ["app"]
