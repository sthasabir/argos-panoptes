#!/usr/bin/env python3
"""
Phase 0 spike: connect to Tsenta's official MCP over HTTP+OAuth, prove we can
authenticate once (browser), persist a portable token bundle, and list the tools
+ jobs. This validates the auth path for the Cloud Run agent (refresh token ->
Secret Manager) and discovers the real tool names / job schema.

Run:  uv run --with mcp python spike_mcp.py
First run opens a browser to approve. Token bundle saved to .tsenta_token.json.
"""
import asyncio
import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from pydantic import AnyUrl
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.client.auth import OAuthClientProvider, TokenStorage
from mcp.shared.auth import OAuthToken, OAuthClientInformationFull, OAuthClientMetadata

SERVER_URL = "https://api.autojobs.me/api/v1/mcp"
CALLBACK_PORT = 8765
CALLBACK_PATH = "/callback"
TOKEN_FILE = Path(__file__).with_name(".tsenta_token.json")


class FileTokenStorage(TokenStorage):
    """Persist tokens + registered-client info to one JSON file so we can inspect
    the refresh token and reuse it headlessly."""

    def __init__(self, path: Path):
        self.path = path

    def _read(self) -> dict:
        if self.path.exists():
            return json.loads(self.path.read_text())
        return {}

    def _write(self, data: dict) -> None:
        self.path.write_text(json.dumps(data, indent=2))

    async def get_tokens(self) -> OAuthToken | None:
        d = self._read().get("tokens")
        return OAuthToken.model_validate(d) if d else None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        d = self._read()
        d["tokens"] = tokens.model_dump(exclude_none=True)
        self._write(d)

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        d = self._read().get("client_info")
        return OAuthClientInformationFull.model_validate(d) if d else None

    async def set_client_info(self, info: OAuthClientInformationFull) -> None:
        d = self._read()
        d["client_info"] = info.model_dump(exclude_none=True, mode="json")
        self._write(d)


def _capture_auth_code() -> tuple[str, str | None]:
    """Run a one-shot local HTTP server to catch the OAuth redirect."""
    result: dict[str, str | None] = {}
    done = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            q = parse_qs(urlparse(self.path).query)
            result["code"] = q.get("code", [None])[0]
            result["state"] = q.get("state", [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h2>Tsenta authorized. You can close this tab.</h2>")
            done.set()

        def log_message(self, *a):  # silence
            pass

    srv = HTTPServer(("localhost", CALLBACK_PORT), Handler)
    threading.Thread(target=srv.handle_request, daemon=True).start()
    done.wait(timeout=300)
    srv.server_close()
    return result.get("code"), result.get("state")


async def _redirect_handler(auth_url: str) -> None:
    print(f"\n>>> Opening browser to authorize Tsenta:\n{auth_url}\n")
    webbrowser.open(auth_url)


async def _callback_handler() -> tuple[str, str | None]:
    print(">>> Waiting for OAuth redirect on localhost:%d ..." % CALLBACK_PORT)
    return await asyncio.to_thread(_capture_auth_code)


async def main():
    oauth = OAuthClientProvider(
        server_url=SERVER_URL,
        client_metadata=OAuthClientMetadata(
            client_name="Mellow Bird Agent",
            redirect_uris=[AnyUrl(f"http://localhost:{CALLBACK_PORT}{CALLBACK_PATH}")],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            token_endpoint_auth_method="client_secret_post",
        ),
        storage=FileTokenStorage(TOKEN_FILE),
        redirect_handler=_redirect_handler,
        callback_handler=_callback_handler,
    )

    async with streamablehttp_client(SERVER_URL, auth=oauth) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("\n=== CONNECTED to Tsenta MCP ===\n")

            tools = await session.list_tools()
            print(f"TOOLS ({len(tools.tools)}):")
            for t in tools.tools:
                schema = json.dumps(t.inputSchema, indent=2) if t.inputSchema else "{}"
                print(f"\n- {t.name}: {t.description}")
                print(f"  input schema: {schema}")

            # Try to find + call a read-only 'list jobs' style tool (no applying).
            candidates = [
                t.name for t in tools.tools
                if any(k in t.name.lower() for k in ("list", "job", "recommend", "search", "browse", "match"))
                and "apply" not in t.name.lower()
            ]
            print(f"\n=== READ-ONLY LIST CANDIDATES: {candidates} ===")
            if candidates:
                name = candidates[0]
                print(f"\nCalling '{name}' (read-only)...")
                try:
                    res = await session.call_tool(name, {})
                    txt = "\n".join(getattr(c, "text", str(c)) for c in res.content)
                    print(txt[:3000])
                except Exception as e:
                    print(f"  call failed (may need args): {e}")

    # Show what got persisted (esp. refresh token presence) for the Cloud Run plan.
    d = json.loads(TOKEN_FILE.read_text()) if TOKEN_FILE.exists() else {}
    tok = d.get("tokens", {})
    print("\n=== TOKEN BUNDLE (persisted) ===")
    print("has access_token:", bool(tok.get("access_token")))
    print("has refresh_token:", bool(tok.get("refresh_token")))
    print("expires_in:", tok.get("expires_in"))
    print("scope:", tok.get("scope"))
    print("client registered:", bool(d.get("client_info")))


if __name__ == "__main__":
    asyncio.run(main())
