import asyncio
import base64
import hashlib
import hmac
import json
import os
import time
import sys

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from dotenv import load_dotenv
load_dotenv()

MCP_URL = os.environ.get("MCP_URL", "http://localhost:8011/mcp")
MCP_JWT_SECRET = os.environ.get("MCP_JWT_SECRET")
MCP_JWT_ALGORITHM = os.environ.get("MCP_JWT_ALGORITHM")

def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")

def create_jwt(identity: str) -> str:
    if (MCP_JWT_ALGORITHM or "HS256") != "HS256":
        raise ValueError("Only HS256 is supported by this sample client.")
    if not MCP_JWT_SECRET:
        raise ValueError("MCP_JWT_SECRET is required.")

    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": identity,
        "identity": identity,
        "iat": now,
        "exp": now + 3600,
    }
    header_b64 = _b64url_encode(
        json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    payload_b64 = _b64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
    signature = hmac.new(
        MCP_JWT_SECRET.encode("utf-8"),
        signing_input,
        hashlib.sha256,
    ).digest()
    signature_b64 = _b64url_encode(signature)
    return f"{header_b64}.{payload_b64}.{signature_b64}"


async def run_scenario(identity: str) -> None:
    token = create_jwt(identity)
    transport = StreamableHttpTransport(
        url=MCP_URL,
        headers={"Authorization": f"Bearer {token}"},
    )
    client = Client(transport)
    async with client:
        tools = await client.list_tools()
        tool_names = [tool.name for tool in tools]
        print(f"{identity} -> tools/list: {tool_names}")


async def run_forbidden_call_scenario() -> None:
    identity = "identity_1"
    token = create_jwt(identity)
    transport = StreamableHttpTransport(
        url=MCP_URL,
        headers={"Authorization": f"Bearer {token}"},
    )
    client = Client(transport)
    async with client:
        try:
            await client.call_tool("current_weather", {})
            print(f"{identity} -> unexpected success calling current_weather")
        except Exception as exc:  # Shows denied tool-call scenario.
            print(f"{identity} -> tools/call(current_weather) denied: {exc}")

def _print_tool_result(result) -> None:
    for content in result.content:
        if hasattr(content, "text"):
            try:
                data = json.loads(content.text)
                print(json.dumps(data, indent=2))
            except json.JSONDecodeError:
                print(content.text)
        else:
            print(content)


async def run_get_my_clients_scenario(identity: str) -> None:
    token = create_jwt(identity)
    transport = StreamableHttpTransport(
        url=MCP_URL,
        headers={"Authorization": f"Bearer {token}"},
    )
    client = Client(transport)
    async with client:
        result = await client.call_tool("get_my_clients", arguments={"auth_token": token})
        _print_tool_result(result)


async def run_get_my_clients_via_api_scenario(identity: str) -> None:
    """Call get_my_clients_via_api, which POSTs to fastapi_sales_db."""
    token = create_jwt(identity)
    transport = StreamableHttpTransport(
        url=MCP_URL,
        headers={"Authorization": f"Bearer {token}"},
    )
    client = Client(transport)
    async with client:
        result = await client.call_tool(
            "get_my_clients_via_api",
            arguments={"auth_token": token},
        )
        _print_tool_result(result)


async def main() -> None:
    identity = sys.argv[1] if len(sys.argv) > 1 else "Alice Chen"
    #print("Scenario A: identity_1 should see only current_time")
    #await run_scenario("identity_1")
    #print("\nScenario B: identity_2 should see current_time and current_weather")
    #await run_scenario("identity_2")
    #print("\nScenario C: identity_1 calls current_weather and should get 403")
    #await run_forbidden_call_scenario()

    print("\nScenario D: Salesperson calls get_my_clients and should get the list of clients")
    await run_get_my_clients_scenario(identity)

    print("\nScenario E: Salesperson calls get_my_clients_via_api (FastAPI sales.db endpoint)")
    await run_get_my_clients_via_api_scenario(identity)


if __name__ == "__main__":
    asyncio.run(main())
