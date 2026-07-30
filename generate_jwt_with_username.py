"""Generate JWT with context.username for testing."""
import base64
import hashlib
import hmac
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")
MCP_JWT_SECRET = os.environ.get("MCP_JWT_SECRET")


def create_jwt(username: str) -> str:
    payload = {"context": {"username": username}, "iat": int(time.time()), "exp": int(time.time()) + 3600}
    header = {"alg": "HS256", "typ": "JWT"}
    h = base64.urlsafe_b64encode(json.dumps(header).encode()).rstrip(b"=").decode()
    p = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    msg = f"{h}.{p}".encode()
    sig = base64.urlsafe_b64encode(hmac.new(MCP_JWT_SECRET.encode(), msg, hashlib.sha256).digest()).rstrip(b"=").decode()
    return f"{h}.{p}.{sig}"


if __name__ == "__main__":
    username = sys.argv[1] if len(sys.argv) > 1 else "Alice Chen"
    if not MCP_JWT_SECRET:
        print("MCP_JWT_SECRET must be set in .env")
        sys.exit(1)
    print(create_jwt(username))
