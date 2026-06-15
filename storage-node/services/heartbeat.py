import threading
import time


def start_heartbeat(master_client, space_cache, interval_seconds: int = 5) -> threading.Thread:
    def send_heartbeat():
        while True:
            try:
                master_client.send_heartbeat_once(space_cache.used())
            except Exception:
                pass
            time.sleep(interval_seconds)

    thread = threading.Thread(target=send_heartbeat, daemon=True)
    thread.start()
    return thread
