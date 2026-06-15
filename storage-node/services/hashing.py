from pathlib import Path
import hashlib


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def path_for_hash(shared_space_dir: Path, content_hash: str, original_name: str) -> Path:
    ext = Path(original_name).suffix[:20]
    return shared_space_dir / content_hash[:2] / f"{content_hash}{ext}"


def safe_existing_file_path(raw_path: str) -> Path:
    path = Path(raw_path).expanduser().resolve()
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")
    return path
