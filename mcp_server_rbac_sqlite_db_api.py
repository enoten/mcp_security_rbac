from datetime import datetime, timezone
import base64
import hashlib
import hmac
import json
import os
import sqlite3
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Sequence

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.middleware import Middleware, MiddlewareContext
from mcp.types import Tool

from dotenv import load_dotenv
load_dotenv()

DB_PATH = Path(__file__).parent / "sales.db"
MCP_JWT_SECRET = os.environ.get("MCP_JWT_SECRET")
MCP_JWT_ALGORITHM = os.environ.get("MCP_JWT_ALGORITHM")
SALES_API_URL = os.environ.get("SALES_API_URL", "http://localhost:8020")

IDENTITY_PERMISSIONS = {
    "identity_1": {"current_time"},
    "identity_2": {"current_time", "current_weather"},
    "Alice Chen": {"get_my_clients", "get_my_clients_via_api"},
    "Bob Smith": {"get_my_clients", "get_my_clients_via_api"},
    "Carol Johnson": {"get_my_clients", "get_my_clients_via_api"},
}


def _base64url_decode(s: str) -> bytes:
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)


def _decode_jwt(token: str) -> dict:
    """Verify HS256 JWT and return payload. Raises ValueError if invalid."""
    if not MCP_JWT_SECRET:
        raise ValueError("MCP_JWT_SECRET not configured")

    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid JWT format")

    header_b64, payload_b64, sig_b64 = parts

    message = f"{header_b64}.{payload_b64}".encode()
    secret_bytes = MCP_JWT_SECRET.encode() if isinstance(MCP_JWT_SECRET, str) else MCP_JWT_SECRET

    expected_sig = base64.urlsafe_b64encode(
        hmac.new(secret_bytes, message, hashlib.sha256).digest()
    ).rstrip(b"=").decode()

    if not hmac.compare_digest(sig_b64, expected_sig):
        raise ValueError("Invalid signature")

    payload_json = _base64url_decode(payload_b64).decode("utf-8")
    payload = json.loads(payload_json)

    exp = payload.get("exp")
    if exp is not None and exp < int(time.time()):
        raise ValueError("Token expired")

    return payload


def _verify_jwt_and_get_username(token: str) -> str:
    """
    Verify HS256 JWT and extract username from payload.context.username.
    Falls back to identity/sub for access-control style tokens.
    """
    payload = _decode_jwt(token)
    context = payload.get("context") or {}
    username = context.get("username") or payload.get("identity") or payload.get("sub")
    if not username:
        raise ValueError("JWT must contain context.username, identity, or sub")
    return str(username).strip()


def _get_token_from_headers() -> str:
    """Extract Bearer token from HTTP headers."""
    headers = get_http_headers()
    if not headers:
        raise ToolError("Unauthorized: No HTTP headers available (check transport)")
    auth_header = headers.get("authorization") or headers.get("Authorization")
    if not auth_header or not auth_header.lower().startswith("bearer "):
        raise ToolError("Unauthorized: Missing Authorization header")
    return auth_header[7:].strip()


def _extract_identity(context: MiddlewareContext) -> str:
    if not context.fastmcp_context or not context.fastmcp_context.request_context:
        raise ToolError("Unauthorized: Missing request context.")

    request = context.fastmcp_context.request_context.request
    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.lower().startswith("bearer "):
        raise ToolError("Unauthorized: Missing or invalid Authorization header.")

    token = auth_header[7:].strip()
    if not MCP_JWT_SECRET:
        raise ToolError("Unauthorized: MCP_JWT_SECRET is not configured.")
    try:
        payload = _decode_jwt(token)
    except ValueError as exc:
        raise ToolError(f"Unauthorized: {exc}") from exc

    print(f">>>>>>>>>>>>>>>>>>")
    print(f"Payload: {payload}")
    print(f">>>>>>>>>>>>>>>>>>")

    identity = payload.get("identity") or payload.get("sub")
    if identity not in IDENTITY_PERMISSIONS:
        raise ToolError("Unauthorized identity in JWT payload.")

    return identity


class AccessControlMiddleware(Middleware):
    async def on_list_tools(
        self,
        context: MiddlewareContext,
        call_next,
    ) -> Sequence[Tool]:
        identity = _extract_identity(context)
        tools = await call_next(context)
        allowed = IDENTITY_PERMISSIONS[identity]
        return [tool for tool in tools if tool.name in allowed]

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        identity = _extract_identity(context)
        tool_name = context.message.name
        if tool_name not in IDENTITY_PERMISSIONS[identity]:
            raise ToolError(
                f"Forbidden: identity '{identity}' is not allowed to call '{tool_name}'."
            )
        return await call_next(context)


def _query_clients_by_salesperson(sales_person_name: str) -> list[dict]:
    """Query SQLite for clients associated with the given salesperson."""
    if not DB_PATH.exists():
        return [{"error": f"Database not found: {DB_PATH}. Run init_sqlite_db.py first."}]
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            "SELECT sales_person_name, associate_client_name FROM sales_clients WHERE sales_person_name = ?",
            (sales_person_name,),
        )
        rows = cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _resolve_auth_username(auth_token: str = "") -> str:
    """Resolve salesperson username from auth_token arg or Authorization header."""
    token = auth_token.strip() if auth_token else None
    if not token:
        try:
            token = _get_token_from_headers()
        except ToolError:
            raise ToolError(
                "Unauthorized: Provide JWT via Authorization: Bearer header or auth_token argument. "
                "Some MCP transports (e.g. streamable HTTP) may not forward headers."
            ) from None
    try:
        return _verify_jwt_and_get_username(token)
    except ValueError as exc:
        raise ToolError(f"Unauthorized: {exc}") from exc


def _query_clients_via_sales_api(sales_person_name: str) -> list[dict]:
    """POST to fastapi_sales_db /clients/query and return the JSON list."""
    url = f"{SALES_API_URL.rstrip('/')}/clients/query"
    payload = json.dumps({"sales_person_name": sales_person_name}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            body = response.read().decode("utf-8")
            data = json.loads(body)
            if not isinstance(data, list):
                raise ToolError(f"Unexpected response from sales API: {data!r}")
            return data
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ToolError(f"Sales API HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise ToolError(
            f"Sales API unreachable at {url}. Is fastapi_sales_db running? ({exc.reason})"
        ) from exc


mcp = FastMCP("MCP Access Control Server with SQLite DB")
mcp.add_middleware(AccessControlMiddleware())


@mcp.tool()
def current_time() -> str:
    """Return current UTC time in ISO format."""
    return datetime.now(timezone.utc).isoformat()


@mcp.tool()
def current_weather() -> str:
    """Return fixed weather text."""
    return "Weather is fine"


@mcp.tool()
def get_my_clients(auth_token: str = "") -> list[dict]:
    """
    Get the list of clients associated with the authenticated salesperson.

    The salesperson identity is extracted from the JWT token's context.username.
    Token source (in order): 1) auth_token argument, 2) Authorization: Bearer header.

    JWT payload must contain: {"context": {"username": "<sales_person_name>"}}.

    Returns:
        List of dicts with sales_person_name and associate_client_name.
    """
    username = _resolve_auth_username(auth_token)
    return _query_clients_by_salesperson(username)


@mcp.tool()
def get_my_clients_via_api(auth_token: str = "") -> list[dict]:
    """
    Get clients for the authenticated salesperson by calling the FastAPI sales DB
    endpoint (POST /clients/query on fastapi_sales_db).

    Auth is the same as get_my_clients: JWT via auth_token or Authorization header.
    Requires fastapi_sales_db to be running (default http://localhost:8020).
    Override base URL with SALES_API_URL.
    """
    username = _resolve_auth_username(auth_token)
    return _query_clients_via_sales_api(username)


if __name__ == "__main__":
    mcp.run(transport="http",
            host="0.0.0.0",
            port=8011)
