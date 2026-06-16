from pathlib import Path
import threading
import time


class SpaceCache:
    """In-memory approximate shared-space usage cache.

    Authoritative after startup resync and internal writes. External file changes
    require calling resync_from_disk().
    """

    def __init__(self, shared_space_dir: Path):
        self.shared_space_dir = shared_space_dir
        self._used_bytes = 0
        self._lock = threading.Lock()

    def cleanup_stale_uploads(self, max_age_seconds: int = 6 * 60 * 60, logger=None) -> int:
        """Remove abandoned upload temp files without touching active uploads."""
        removed = 0
        if not self.shared_space_dir.exists():
            return removed

        cutoff = time.time() - int(max_age_seconds)
        for item in self.shared_space_dir.glob(".upload-*"):
            if not item.is_file():
                continue
            try:
                if item.stat().st_mtime > cutoff:
                    continue
                item.unlink()
                removed += 1
                message = f"Cleanup stale upload: {item}"
                if logger:
                    logger.info(message)
                else:
                    print(f"[*] {message}")
            except Exception as exc:
                message = f"Failed to cleanup stale upload: {item} ({exc})"
                if logger:
                    logger.warning(message)
                else:
                    print(f"[!] {message}")

        return removed

    def resync_from_disk(self, cleanup_stale_uploads: bool = True) -> int:
        if cleanup_stale_uploads:
            self.cleanup_stale_uploads()

        total = 0
        if self.shared_space_dir.exists():
            for item in self.shared_space_dir.rglob("*"):
                if item.is_file():
                    if item.name.startswith(".upload-"):
                        continue
                    total += item.stat().st_size
        with self._lock:
            self._used_bytes = total
        print(f"[*] Space cache initialized/resynced: {total} bytes used on disk.")
        return total

    def used(self) -> int:
        with self._lock:
            return self._used_bytes

    def add(self, size_bytes: int) -> None:
        with self._lock:
            self._used_bytes += int(size_bytes)

    def subtract(self, size_bytes: int) -> None:
        with self._lock:
            self._used_bytes = max(0, self._used_bytes - int(size_bytes))
