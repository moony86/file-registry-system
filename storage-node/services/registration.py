import threading
import time


def start_registration_loop(
    master_client,
    space_cache,
    shared_space_enabled: bool,
    shared_space_limit_bytes: int,
    base_interval: int = 5,
    max_interval: int = 300,
) -> threading.Thread:
    """
    Keep trying to register this node with the master in the background.
    Does not block Flask startup.
    """

    def run():
        current_interval = base_interval

        while True:
            try:
                ok = master_client.register_node(
                    shared_space_enabled=shared_space_enabled,
                    shared_space_limit_bytes=shared_space_limit_bytes,
                    shared_space_used_bytes=space_cache.used(),
                )

                if ok:
                    current_interval = max_interval
                    time.sleep(current_interval)
                    continue

            except Exception as exc:
                print(f"[registration] failed: {exc}")

            print(f"[registration] master unreachable, retrying in {current_interval}s")
            time.sleep(current_interval)
            current_interval = min(current_interval * 2, max_interval)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread
