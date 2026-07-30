#!/usr/bin/env python3
"""Reconnect using the PERSISTED token (no browser) and reveal which account the
MCP is authenticated as + whether the profile/resume we built exists.
Also proves headless token reuse for the Cloud Run path."""
import asyncio, json
from pathlib import Path
from pydantic import AnyUrl
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.client.auth import OAuthClientProvider, TokenStorage
from mcp.shared.auth import OAuthToken, OAuthClientInformationFull, OAuthClientMetadata

SERVER_URL = "https://api.autojobs.me/api/v1/mcp"
TOKEN_FILE = Path(__file__).with_name(".tsenta_token.json")


class FileTokenStorage(TokenStorage):
    def __init__(self, path): self.path = path
    def _read(self): return json.loads(self.path.read_text()) if self.path.exists() else {}
    def _write(self, d): self.path.write_text(json.dumps(d, indent=2))
    async def get_tokens(self):
        d = self._read().get("tokens"); return OAuthToken.model_validate(d) if d else None
    async def set_tokens(self, t):
        d = self._read(); d["tokens"] = t.model_dump(exclude_none=True); self._write(d)
    async def get_client_info(self):
        d = self._read().get("client_info"); return OAuthClientInformationFull.model_validate(d) if d else None
    async def set_client_info(self, i):
        d = self._read(); d["client_info"] = i.model_dump(exclude_none=True, mode="json"); self._write(d)


async def _noop_redirect(u): raise RuntimeError("Browser auth required but we should have a valid token!")
async def _noop_cb(): raise RuntimeError("no callback expected")


def _dump(res, limit=1500):
    return "\n".join(getattr(c, "text", str(c)) for c in res.content)[:limit]


async def main():
    oauth = OAuthClientProvider(
        server_url=SERVER_URL,
        client_metadata=OAuthClientMetadata(
            client_name="Mellow Bird Agent",
            redirect_uris=[AnyUrl("http://localhost:8765/callback")],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            token_endpoint_auth_method="client_secret_post",
        ),
        storage=FileTokenStorage(TOKEN_FILE),
        redirect_handler=_noop_redirect,
        callback_handler=_noop_cb,
    )
    async with streamablehttp_client(SERVER_URL, auth=oauth) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            print("=== HEADLESS RECONNECT OK (no browser) ===\n")
            for tool in ("get-profile-status", "get-inbox-address", "get-resume-profile", "get-application-balance"):
                try:
                    res = await s.call_tool(tool, {})
                    print(f"--- {tool} ---\n{_dump(res)}\n")
                except Exception as e:
                    print(f"--- {tool} --- ERROR: {e}\n")


if __name__ == "__main__":
    asyncio.run(main())
