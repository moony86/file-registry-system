import json
import logging
import os
import threading
import time

import requests

logger = logging.getLogger(__name__)


def start_storage_operations_worker(db, interval_seconds=5):
    node_token = os.getenv("FSYS_NODE_TOKEN", "dev-token")

    def complete_as_cached(operation, payload):
        shared_path = payload.get("shared_space_path")
        if not shared_path:
            db.fail_storage_operation(
                operation["operation_id"],
                "Storage node did not return shared_space_path",
                result_json=json.dumps(payload),
            )
            return

        db.upsert_content_location(
            content_hash=operation["content_hash"],
            node_id=operation["target_node_id"],
            physical_path=shared_path,
            location_type="CACHED",
            is_primary=False,
        )
        db.complete_storage_operation(operation["operation_id"], result_json=json.dumps(payload))

    def process_operation(operation):
        if operation.get("operation_type") != "promote_local_to_cached":
            db.fail_storage_operation(operation["operation_id"], f"Unsupported operation type: {operation.get('operation_type')}")
            return

        if db.file_has_cached_location(operation["file_id"]):
            db.complete_storage_operation(
                operation["operation_id"],
                result_json=json.dumps({"status": "already_cached", "reason": "CACHED location already exists"}),
            )
            return

        url = f"http://{operation['host']}:{operation['port']}/api/files/{operation['file_id']}/promote-to-cache"
        body = {
            "content_hash": operation["content_hash"],
            "physical_path": operation["physical_path"],
            "file_name": operation["file_name"],
        }
        try:
            response = requests.post(
                url,
                json=body,
                headers={"X-FSYS-Token": node_token},
                timeout=60 * 60,
            )
            try:
                payload = response.json()
            except Exception:
                payload = {"error": response.text or "Storage node returned non-JSON response"}

            if response.status_code == 200 and payload.get("status") in {"cached", "already_cached"}:
                complete_as_cached(operation, payload)
                return

            db.fail_storage_operation(
                operation["operation_id"],
                payload.get("error") or f"Storage node returned HTTP {response.status_code}",
                result_json=json.dumps(payload),
            )
        except Exception as exc:
            logger.warning("Storage operation %s failed", operation["operation_id"], exc_info=True)
            db.fail_storage_operation(operation["operation_id"], str(exc))

    def run():
        while True:
            try:
                operation = db.claim_pending_storage_operation()
                if operation:
                    process_operation(operation)
            except Exception:
                logger.exception("Storage operations worker tick failed")
            time.sleep(interval_seconds)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread
