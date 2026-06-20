import logging
import time
import requests

logger = logging.getLogger(__name__)


class MasterClient:
    def __init__(
        self,
        master_urls,
        node_token: str,
        node_id: str,
        node_host: str,
        node_port: int,
    ):
        if isinstance(master_urls, str):
            master_urls = [url.strip() for url in master_urls.split(",") if url.strip()]
        self.master_urls = [url.rstrip("/") for url in master_urls if url]
        if not self.master_urls:
            raise ValueError("MasterClient requires at least one master URL")
        self.active_master_url = self.master_urls[0]
        self.node_token = node_token
        self.node_id = node_id
        self.node_host = node_host
        self.node_port = int(node_port)

    def auth_headers(self):
        return {"X-FSYS-Token": self.node_token}

    def _ordered_master_urls(self):
        urls = [self.active_master_url]
        urls.extend(url for url in self.master_urls if url != self.active_master_url)
        return urls

    def _request_with_fallback(self, method: str, path: str, *, success_statuses=None, **kwargs):
        success_statuses = set(success_statuses or range(200, 300))
        last_exception = None
        last_response = None

        for master_url in self._ordered_master_urls():
            try:
                response = requests.request(method, f"{master_url}{path}", **kwargs)
                if response.status_code in success_statuses:
                    if master_url != self.active_master_url:
                        logger.info("Active master switched to %s", master_url)
                    self.active_master_url = master_url
                    return response

                last_response = response
                logger.warning("%s %s failed on %s: HTTP %s", method, path, master_url, response.status_code)
            except Exception as exc:
                last_exception = exc
                logger.warning("%s %s failed on %s: %s", method, path, master_url, exc)

        if last_response is not None:
            return last_response
        if last_exception is not None:
            raise last_exception
        raise RuntimeError("No master URLs were available")

    def register_node(
        self,
        shared_space_enabled: bool,
        shared_space_limit_bytes: int,
        shared_space_used_bytes: int,
    ) -> bool:
        payload = {
            "node_id": self.node_id,
            "host": self.node_host,
            "port": self.node_port,
            "shared_space_enabled": shared_space_enabled,
            "shared_space_limit_bytes": shared_space_limit_bytes,
            "shared_space_used_bytes": shared_space_used_bytes,
        }

        for attempt in range(5):
            try:
                response = self._request_with_fallback(
                    "POST",
                    "/api/nodes/register",
                    json=payload,
                    headers=self.auth_headers(),
                    success_statuses={200},
                    timeout=5,
                )

                if response.status_code == 200:
                    logger.info("Registered with master %s on attempt %s", self.active_master_url, attempt + 1)
                    return True

                logger.warning("Registration failed: HTTP %s %s", response.status_code, response.text)

            except Exception as exc:
                logger.warning("Registration attempt %s failed: %s", attempt + 1, exc)

            time.sleep(2)

        return False

    def send_heartbeat_once(self, shared_space_used_bytes: int):
        return self._request_with_fallback(
            "POST",
            "/api/nodes/heartbeat",
            json={
                "node_id": self.node_id,
                "shared_space_used_bytes": shared_space_used_bytes,
            },
            headers=self.auth_headers(),
            success_statuses={200},
            timeout=2,
        )

    def register_file(
        self,
        *,
        content_hash: str,
        file_name: str,
        owner: str,
        size_bytes: int,
        mime_type: str,
        media_type: str,
        physical_path: str,
        location_type: str,
        technical_metadata: dict | None = None,
        thumbnail_metadata: dict | None = None,
    ):
        payload = {
            "content_hash": content_hash,
            "file_name": file_name,
            "owner": owner,
            "size_bytes": size_bytes,
            "mime_type": mime_type,
            "media_type": media_type,
            "node_id": self.node_id,
            "physical_path": physical_path,
            "location_type": location_type,
        }
        if technical_metadata is not None:
            payload["technical_metadata"] = technical_metadata
        if thumbnail_metadata is not None:
            payload["thumbnail_metadata"] = thumbnail_metadata

        return self._request_with_fallback(
            "POST",
            "/api/files/register",
            json=payload,
            headers=self.auth_headers(),
            success_statuses={201},
            timeout=10,
        )

    def get_file_location(self, file_id: str, access_type: str | None = None):
        params = {"access_type": access_type} if access_type else None
        return self._request_with_fallback(
            "GET",
            f"/api/files/{file_id}/location",
            params=params,
            success_statuses={200},
            timeout=5,
        )
