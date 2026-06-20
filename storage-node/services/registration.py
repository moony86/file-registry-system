import logging
import threading
import time

logger = logging.getLogger(__name__)


class RegistrationState:
    def __init__(self):
        self._lock = threading.Lock()
        self.last_success_at = None
        self.last_failure_at = None
        self.last_error = None
        self.next_retry_seconds = None
        self.registered = False
        self.attempts = 0

    def mark_success(self):
        with self._lock:
            self.registered = True
            self.last_success_at = time.time()
            self.last_error = None
            self.next_retry_seconds = None
            self.attempts += 1

    def mark_failure(self, error, next_retry_seconds):
        with self._lock:
            self.registered = False
            self.last_failure_at = time.time()
            self.last_error = str(error)
            self.next_retry_seconds = next_retry_seconds
            self.attempts += 1

    def snapshot(self):
        with self._lock:
            return {
                "registered": self.registered,
                "last_success_at": self.last_success_at,
                "last_failure_at": self.last_failure_at,
                "last_error": self.last_error,
                "next_retry_seconds": self.next_retry_seconds,
                "attempts": self.attempts,
            }


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

    state = RegistrationState()

    def run():
        current_interval = base_interval

        while True:
            error = "registration failed"
            try:
                ok = master_client.register_node(
                    shared_space_enabled=shared_space_enabled,
                    shared_space_limit_bytes=shared_space_limit_bytes,
                    shared_space_used_bytes=space_cache.used(),
                )

                if ok:
                    state.mark_success()
                    current_interval = max_interval
                    time.sleep(current_interval)
                    continue

            except Exception as exc:
                error = exc
                logger.warning("Registration failed", exc_info=True)

            state.mark_failure(error, current_interval)
            logger.warning("Master unreachable, retrying registration in %ss", current_interval)
            time.sleep(current_interval)
            current_interval = min(current_interval * 2, max_interval)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.registration_state = state
    return thread
