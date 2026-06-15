from flask import request


def require_node_token(node_token: str) -> bool:
    return request.headers.get("X-FSYS-Token") == node_token
