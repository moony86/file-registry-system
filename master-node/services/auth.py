import os
from flask import request


def require_node_token() -> bool:
    """Dev-friendly shared token check for node/admin endpoints."""
    expected = os.getenv("FSYS_NODE_TOKEN", "dev-token")
    received = request.headers.get("X-FSYS-Token")
    return expected == received
