from pathlib import Path
import threading


class SpaceCache:
    """In-memory approximate shared-space usage cache.

    Authoritative after startup resync and internal writes. External file changes
    require calling resync_from_disk().
    """

    def __init__(self, shared_space_dir: Path):
        self.shared_space_dir = shared_space_dir
        self._used_bytes = 0
        self._lock = threading.Lock()

    def resync_from_disk(self) -> int:
        total = 0
        if self.shared_space_dir.exists():
            for item in self.shared_space_dir.rglob("*"):
                if item.is_file():
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
