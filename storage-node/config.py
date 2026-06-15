import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

NODE_ID = os.getenv("NODE_ID", "node-unknown")
NODE_HOST = os.getenv("NODE_HOST", "localhost")
NODE_PORT = int(os.getenv("NODE_PORT", "5001"))
MASTER_URL = os.getenv("MASTER_URL", "http://localhost:5000")
NODE_TOKEN = os.getenv("FSYS_NODE_TOKEN", "dev-token")

SHARED_SPACE_DIR = Path(os.getenv("SHARED_SPACE_DIR", "./shared_space")).resolve()
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
