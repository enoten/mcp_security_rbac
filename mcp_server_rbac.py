from datetime import datetime, timezone
import base64
import hashlib
import hmac
import json
import os
import time
from typing import Sequence

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import Middleware, MiddlewareContext
from mcp.types import Tool

from dotenv import load_dotenv
load_dotenv()


MCP_JWT_SECRET = os.environ.get("MCP_JWT_SECRET")
MCP_JWT_ALGORITHM = os.environ.get("MCP_JWT_ALGORITHM")

IDENTITY_PERMISSIONS = {
    "identity_1": {"current_time"},
    "identity_2": {"current_time", "current_weather"},
}


def _base64url_decode(s: str) -> bytes:
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)


def _decode_jwt(token: str, secret: str, algorithm: str) -> dict:
    if algorithm != "HS256":
        raise ToolError("Unauthorized: Only HS256 is supported.")

    parts = token.split(".")
    if len(parts) != 3:
        raise ToolError("Unauthorized: Malformed JWT.")

    header_b64, payload_b64, signature_b64 = parts
    signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
    expected_signature = hmac.new(
        secret.encode("utf-8"),
        signing_input,
        hashlib.sha256,
    ).digest()
    provided_signature = _base64url_decode(signature_b64)

    if not hmac.compare_digest(expected_signature, provided_signature):
        raise ToolError("Unauthorized: Invalid JWT signature.")

    try:
        header = json.loads(_base64url_decode(header_b64))
        payload = json.loads(_base64url_decode(payload_b64))
    except Exception as exc:
        raise ToolError(f"Unauthorized: Invalid JWT encoding: {exc}") from exc

    if header.get("alg") != "HS256":
        raise ToolError("Unauthorized: JWT alg mismatch.")

    exp = payload.get("exp")
    if exp is not None and int(exp) <= int(time.time()):
        raise ToolError("Unauthorized: JWT expired.")

    return payload

def _decode_jwt(token: str) -> str:
    """Verify HS256 JWT and extract context.username. Raises ValueError if invalid."""
    if not MCP_JWT_SECRET:
        raise ValueError("MCP_JWT_SECRET not configured")
    
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid JWT format")
    
    header_b64, payload_b64, sig_b64 = parts

    message = f"{header_b64}.{payload_b64}".encode()
    print("message  >>", message, type(message))
    
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
    payload = _decode_jwt(token)

    print(f">>>>>>>>>>>>>>>>>>")
    print(f"Payload: {payload}")
    print(f">>>>>>>>>>>>>>>>>>")

    identity = payload.get("identity") or payload.get("sub")
    if identity not in IDENTITY_PERMISSIONS:
        raise ToolError("Unauthorized identity in JWT payload.")

    return identity


class AccessControlMiddleware(Middleware):
    async def on_list_tools(self,
                            context: MiddlewareContext,
                            call_next) -> Sequence[Tool]:
        identity = _extract_identity(context)
        tools = await call_next(context)
        allowed = IDENTITY_PERMISSIONS[identity]
        return [tool for tool in tools if tool.name in allowed]

    async def on_call_tool(self, 
                           context: MiddlewareContext, 
                           call_next) -> Sequence[Tool]:
        identity = _extract_identity(context)
        tool_name = context.message.name
        if tool_name not in IDENTITY_PERMISSIONS[identity]:
            raise ToolError(f"Forbidden: identity '{identity}' is not allowed to call '{tool_name}'.")
        return await call_next(context)

mcp = FastMCP("MCP Access Control Server")
mcp.add_middleware(AccessControlMiddleware())


@mcp.tool()
def current_time() -> str:
    """Return current UTC time in ISO format."""
    return datetime.now(timezone.utc).isoformat()


@mcp.tool()
def current_weather() -> str:
    """Return fixed weather text."""
    return "Weather is fine"


if __name__ == "__main__":
    mcp.run(transport="http", 
            host="0.0.0.0", 
            port=8011)
