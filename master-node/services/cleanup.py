import os
import threading
import time


def start_dead_node_cleanup(db) -> threading.Thread:
    """Start background cleanup thread that marks stale nodes offline."""
    def cleanup_dead_nodes():
        while True:
            try:
                timeout = int(os.getenv("NODE_TIMEOUT_SECONDS", "30"))
                db.mark_dead_nodes(timeout_seconds=timeout)
            except Exception as exc:
                print(f"cleanup_dead_nodes failed: {exc}")
            time.sleep(10)

    thread = threading.Thread(target=cleanup_dead_nodes, daemon=True)
    thread.start()
    return thread
