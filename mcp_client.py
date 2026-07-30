"""
Tsenta MCP client wrapper (proven in Phase 0 spike).

Connects to Tsenta's official MCP over HTTP+OAuth and exposes the handful of
tools the agent needs. Auth modes:
  - local  : token bundle persisted to a JSON file on disk (Mac / first-run OAuth)
  - secret : token bundle loaded from / written back to GCP Secret Manager (Cloud Run)

The OAuth *interactive* step (browser Approve) is done ONCE via `authorize()`
(or the spike). After that everything runs headlessly off the refresh token.
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
import webbrowser
from contextlib import asynccontextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import asyncio
import httpx
from pydantic import AnyUrl
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.client.auth import OAuthClientProvider, TokenStorage
from mcp.shared.auth import OAuthToken, OAuthClientInformationFull, OAuthClientMetadata

SERVER_URL = os.environ.get("TSENTA_MCP_URL", "https://api.autojobs.me/api/v1/mcp")
TOKEN_ENDPOINT = os.environ.get("TSENTA_TOKEN_URL", "https://api.autojobs.me/oauth/token")
CALLBACK_PORT = int(os.environ.get("TSENTA_OAUTH_PORT", "8765"))
CLIENT_NAME = "Mellow Bird Agent"
# The token endpoint expects a standard browser client, so we mint the short-lived
# access token ourselves with a browser User-Agent before each run rather than
# relying on the SDK's default refresh path.
BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


def _refresh_access_token(storage_dict: dict) -> dict | None:
    """Blocking: exchange the (stable, reusable) refresh token for a fresh access token
    via a browser-standard request. Returns updated tokens dict or None."""
    tok = storage_dict.get("tokens") or {}
    info = storage_dict.get("client_info") or {}
    rt, cid = tok.get("refresh_token"), info.get("client_id")
    if not rt or not cid:
        return None
    r = httpx.post(TOKEN_ENDPOINT,
        data={"grant_type": "refresh_token", "refresh_token": rt, "client_id": cid},
        headers={"User-Agent": BROWSER_UA, "Content-Type": "application/x-www-form-urlencoded",
                 "Accept": "application/json"}, timeout=30)
    r.raise_for_status()
    data = r.json()
    new = dict(tok)
    new["access_token"] = data["access_token"]
    new["token_type"] = data.get("token_type", tok.get("token_type", "Bearer"))
    new["expires_in"] = data.get("expires_in", 3600)
    if data.get("refresh_token"):
        new["refresh_token"] = data["refresh_token"]   # keep whatever it returns (stable in practice)
    return new


async def prime_token(storage: "TokenStorage") -> None:
    """Refresh + persist a fresh access token before connecting, so the SDK never
    has to run its default refresh path mid-run. No-op on first-run (no token)."""
    tokens = await storage.get_tokens()
    info = await storage.get_client_info()
    if not tokens or not tokens.refresh_token or not info:
        return
    sd = {"tokens": tokens.model_dump(exclude_none=True),
          "client_info": info.model_dump(exclude_none=True, mode="json")}
    try:
        updated = await asyncio.to_thread(_refresh_access_token, sd)
        if updated:
            await storage.set_tokens(OAuthToken.model_validate(updated))
    except Exception as e:
        print("prime_token: refresh failed, falling back to stored token:", str(e)[:120])


# ---------------------------------------------------------------- token storage
class _BaseStorage(TokenStorage):
    def _read(self) -> dict: ...  # implemented by subclass
    def _write(self, data: dict) -> None: ...

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


class FileTokenStorage(_BaseStorage):
    def __init__(self, path: Path):
        self.path = Path(path)

    def _read(self) -> dict:
        return json.loads(self.path.read_text()) if self.path.exists() else {}

    def _write(self, data: dict) -> None:
        self.path.write_text(json.dumps(data, indent=2))


class SecretManagerStorage(_BaseStorage):
    """Cloud Run path: the whole token bundle lives in one Secret Manager secret;
    rotated tokens are written back as a new secret version each run."""

    def __init__(self, project: str, secret_id: str):
        from google.cloud import secretmanager  # lazy import
        self._sm = secretmanager.SecretManagerServiceClient()
        self._project = project
        self._secret_id = secret_id
        self._cache: dict | None = None

    def _name_latest(self) -> str:
        return f"projects/{self._project}/secrets/{self._secret_id}/versions/latest"

    def _parent(self) -> str:
        return f"projects/{self._project}/secrets/{self._secret_id}"

    def _read(self) -> dict:
        if self._cache is not None:
            return self._cache
        try:
            resp = self._sm.access_secret_version(name=self._name_latest())
            self._cache = json.loads(resp.payload.data.decode())
        except Exception:
            self._cache = {}
        return self._cache

    def _write(self, data: dict) -> None:
        self._cache = data
        self._sm.add_secret_version(
            parent=self._parent(),
            payload={"data": json.dumps(data).encode()},
        )


def make_storage() -> TokenStorage:
    mode = os.environ.get("MCP_AUTH_MODE", "local")
    if mode == "secret":
        return SecretManagerStorage(
            project=os.environ["GCP_PROJECT"],
            secret_id=os.environ.get("TSENTA_SECRET_ID", "tsenta-refresh-token"),
        )
    path = os.environ.get("TSENTA_TOKEN_FILE", str(Path(__file__).with_name(".tsenta_token.json")))
    return FileTokenStorage(Path(path))


# ---------------------------------------------------------------- oauth handlers
def _capture_auth_code() -> tuple[str, str | None]:
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

        def log_message(self, *a):
            pass

    srv = HTTPServer(("localhost", CALLBACK_PORT), Handler)
    threading.Thread(target=srv.handle_request, daemon=True).start()
    done.wait(timeout=300)
    srv.server_close()
    return result.get("code"), result.get("state")


async def _redirect_handler(auth_url: str) -> None:
    print(f"\n>>> Approve Tsenta access in your browser:\n{auth_url}\n")
    webbrowser.open(auth_url)


async def _callback_handler() -> tuple[str, str | None]:
    return await asyncio.to_thread(_capture_auth_code)


async def _headless_redirect(auth_url: str) -> None:
    raise RuntimeError(
        "Interactive OAuth required but running headless. Re-run authorize() once "
        "on a machine with a browser, then push the refresh token to the token store."
    )


async def _headless_callback() -> tuple[str, str | None]:
    raise RuntimeError("no interactive callback in headless mode")


def _provider(interactive: bool) -> OAuthClientProvider:
    return OAuthClientProvider(
        server_url=SERVER_URL,
        client_metadata=OAuthClientMetadata(
            client_name=CLIENT_NAME,
            redirect_uris=[AnyUrl(f"http://localhost:{CALLBACK_PORT}/callback")],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            token_endpoint_auth_method="client_secret_post",
        ),
        storage=make_storage(),
        redirect_handler=_redirect_handler if interactive else _headless_redirect,
        callback_handler=_callback_handler if interactive else _headless_callback,
    )


# ---------------------------------------------------------------- client
class TsentaMCP:
    """Async context manager exposing the tools the agent uses."""

    def __init__(self, interactive: bool = False):
        self._interactive = interactive
        self._session: ClientSession | None = None
        self._cm = None
        self._sess_cm = None

    async def __aenter__(self) -> "TsentaMCP":
        if not self._interactive:
            await prime_token(make_storage())   # mint fresh access token (bypasses CF-blocked SDK refresh)
        self._cm = streamablehttp_client(SERVER_URL, auth=_provider(self._interactive))
        read, write, _ = await self._cm.__aenter__()
        self._sess_cm = ClientSession(read, write)
        self._session = await self._sess_cm.__aenter__()
        await self._session.initialize()
        return self

    async def __aexit__(self, *exc):
        if self._sess_cm:
            await self._sess_cm.__aexit__(*exc)
        if self._cm:
            await self._cm.__aexit__(*exc)

    async def _call_json(self, name: str, args: dict):
        res = await self._session.call_tool(name, args)
        text = "\n".join(getattr(c, "text", "") for c in res.content)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"_raw": text}

    # -- read-only (free tier) --
    async def get_balance(self) -> dict:
        return await self._call_json("get-application-balance", {})

    async def get_recommendations(self, limit: int = 20, date_posted: str = "30d",
                                   page: int = 1, extra: dict | None = None) -> dict:
        args = {"limit": min(limit, 50), "datePosted": date_posted, "page": page}
        if extra:
            args.update(extra)
        return await self._call_json("get-job-recommendations", args)

    async def get_jobs_by_ids(self, ids: list[str]) -> dict:
        return await self._call_json("get-jobs-by-ids", {"jobIds": ids[:20]})

    async def list_resume_profiles(self) -> dict:
        return await self._call_json("list-resume-profiles", {})

    async def fetch_job_description(self, url: str) -> str:
        """Resolve a raw job URL (greenhouse/lever/workday/linkedin) to plain-text JD.
        Needed so the resume optimizer + Gate 2 have full context on external jobs."""
        res = await self._call_json("fetch-job-description", {"url": url})
        if isinstance(res, dict):
            return (res.get("jobDescription") or res.get("description")
                    or res.get("text") or res.get("_raw") or "")
        return str(res or "")

    # -- write (consumes credits; only used live) --
    async def apply_to_job(self, job_id: str | None = None, resume_profile_id: str | None = None,
                           url: str | None = None, job_description: str | None = None) -> dict:
        """Apply by Tsenta jobId (feed jobs) OR by raw url + jobDescription (external jobs)."""
        args: dict = {}
        if url:
            args["url"] = url
            if job_description:
                args["jobDescription"] = job_description[:10000]
        else:
            args["jobId"] = job_id
        if resume_profile_id:
            args["resumeProfileId"] = resume_profile_id
        return await self._call_json("apply-to-job", args)


async def authorize() -> None:
    """Run ONCE interactively (browser) to seed the token store."""
    async with TsentaMCP(interactive=True) as mcp:
        bal = await mcp.get_balance()
        print("Authorized. Balance:", bal)


if __name__ == "__main__":
    asyncio.run(authorize())
