"""CLI entry — stdio (default) or HTTP."""

from __future__ import annotations

import argparse
import os
import sys


def main() -> None:
    parser = argparse.ArgumentParser(prog="kosis-mcp")
    parser.add_argument(
        "--http",
        action="store_true",
        help="Run Streamable HTTP server (default: stdio)",
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("PORT", "3000"))
    )
    args = parser.parse_args()

    if args.http:
        import uvicorn

        from kosis_mcp.http_app import app

        print(
            f"[kosis-mcp] HTTP server listening on :{args.port}",
            file=sys.stderr,
        )
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    else:
        from kosis_mcp.config import validate_config
        from kosis_mcp.server import mcp

        validate_config()
        print("KOSIS MCP (FastMCP) starting on stdio…", file=sys.stderr)
        mcp.run()


if __name__ == "__main__":
    main()
