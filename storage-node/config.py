import os
import re
import uuid
import socket
import json
import sys
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

IS_FROZEN = getattr(sys, "frozen", False)
RUNTIME_DIR = Path(sys.executable).resolve().parent if IS_FROZEN else Path.cwd().resolve()

if IS_FROZEN:
    os.chdir(RUNTIME_DIR)
load_dotenv()

DATA_DIR = Path(os.getenv("DATA_DIR", "./data")).resolve()
IDENTITY_FILE = DATA_DIR / "node_identity.json"


def sanitize_hostname(name: str) -> str:
    name = (name or "unknown-host").strip().lower()
    name = re.sub(r"[^a-z0-9\-_]", "-", name)
    name = re.sub(r"-+", "-", name)
    return name.strip("-") or "unknown-host"


def get_local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception as exc:
        print(f"[WARNING] Could not detect local IP, using 127.0.0.1: {exc}")
        return "127.0.0.1"
    finally:
        s.close()


def read_identity_file() -> dict:
    if not IDENTITY_FILE.exists():
        return {}

    try:
        with open(IDENTITY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Node identity file is corrupted: {IDENTITY_FILE}. "
            "Fix it manually or delete it only if you intentionally want a new node identity."
        ) from exc


def write_identity_file(data: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(IDENTITY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


def load_or_create_node_identity() -> dict:
    existing = read_identity_file()

    hostname = sanitize_hostname(socket.gethostname())
    current_ip = get_local_ip()
    now = datetime.utcnow().isoformat()

    node_id = existing.get("node_id")
    if not node_id:
        node_id = f"node-{hostname}-{uuid.uuid4().hex[:8]}"

    created_at = existing.get("created_at") or now

    identity = {
        "node_id": node_id,
        "generated_host": current_ip,
        "hostname": hostname,
        "created_at": created_at,
        "updated_at": now,
    }

    if identity != existing:
        write_identity_file(identity)

    return identity


node_identity = load_or_create_node_identity()

env_node_id = os.getenv("NODE_ID", "auto").strip()
if env_node_id.lower() in {"auto", ""}:
    NODE_ID = node_identity["node_id"]
else:
    NODE_ID = env_node_id

env_node_host = os.getenv("NODE_HOST", "auto").strip()
if env_node_host.lower() in {"auto", ""}:
    NODE_HOST = node_identity["generated_host"]
else:
    NODE_HOST = env_node_host


NODE_PORT = int(os.getenv("NODE_PORT", "5001"))


def parse_master_urls():
    raw_urls = os.getenv("MASTER_URLS") or os.getenv("MASTER_URL") or ""
    if raw_urls.strip():
        return [url.strip().rstrip("/") for url in raw_urls.split(",") if url.strip()]
    return [
        "http://192.168.1.111:5123",
        "http://100.93.140.49:5123",
        "http://localhost:5000",
    ]


MASTER_URLS = parse_master_urls()
if not MASTER_URLS:
    raise RuntimeError("At least one MASTER_URL or MASTER_URLS entry is required")

MASTER_URL = MASTER_URLS[0]

NODE_TOKEN = os.getenv("FSYS_NODE_TOKEN", "dev-token")

SHARED_SPACE_DIR = Path(os.getenv("SHARED_SPACE_DIR", "./shared_space")).resolve()
THUMBNAILS_DIR = Path(os.getenv("THUMBNAILS_DIR", "./thumbnails")).resolve()
SHARED_SPACE_LIMIT_BYTES = int(os.getenv("SHARED_SPACE_LIMIT_BYTES", str(1024 * 1024 * 1024)))
SHARED_SPACE_ENABLED = os.getenv("SHARED_SPACE_ENABLED", "true").lower() in {"1", "true", "yes"}

CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "FSYS_CORS_ORIGINS",
        "http://localhost:5000,http://127.0.0.1:5000",
    ).split(",")
    if origin.strip()
]
