import time
import requests


class MasterClient:
    def __init__(
        self,
        master_url: str,
        node_token: str,
        node_id: str,
        node_host: str,
        node_port: int,
    ):
        self.master_url = master_url.rstrip("/")
        self.node_token = node_token
        self.node_id = node_id
        self.node_host = node_host
        self.node_port = int(node_port)

    def auth_headers(self):
        return {"X-FSYS-Token": self.node_token}

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
                response = requests.post(
                    f"{self.master_url}/api/nodes/register",
                    json=payload,
                    headers=self.auth_headers(),
                    timeout=5,
                )

                if response.status_code == 200:
                    print(f"Registered with master on attempt {attempt + 1}")
                    return True

                print(f"Registration failed: HTTP {response.status_code} {response.text}")

            except Exception as exc:
                print(f"Registration attempt {attempt + 1} failed: {exc}")

            time.sleep(2)

        return False

    def send_heartbeat_once(self, shared_space_used_bytes: int):
        return requests.post(
            f"{self.master_url}/api/nodes/heartbeat",
            json={
                "node_id": self.node_id,
                "shared_space_used_bytes": shared_space_used_bytes,
            },
            headers=self.auth_headers(),
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

        return requests.post(
            f"{self.master_url}/api/files/register",
            json=payload,
            headers=self.auth_headers(),
            timeout=10,
        )

    def get_file_location(self, file_id: str, access_type: str | None = None):
        params = {"access_type": access_type} if access_type else None
        return requests.get(
            f"{self.master_url}/api/files/{file_id}/location",
            params=params,
            timeout=5,
        )
