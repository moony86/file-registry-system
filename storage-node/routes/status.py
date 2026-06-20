from datetime import datetime, timezone

from flask import Blueprint, jsonify


def create_status_blueprint(config, space_cache, master_client=None, runtime_state=None):
    bp = Blueprint("status", __name__, url_prefix="/api")

    @bp.route("/status", methods=["GET"])
    def node_status():
        used = space_cache.used()
        state_ref = runtime_state or {}
        registration_thread = state_ref.get("registration_thread")
        registration_state = None
        if registration_thread is not None and hasattr(registration_thread, "registration_state"):
            registration_state = registration_thread.registration_state.snapshot()

        return jsonify({
            "node_id": config.NODE_ID,
            "status": "online",
            "node_host": config.NODE_HOST,
            "node_port": config.NODE_PORT,
            "master_urls": list(getattr(config, "MASTER_URLS", [getattr(config, "MASTER_URL", "")])),
            "active_master_url": getattr(master_client, "active_master_url", None),
            "shared_space_enabled": config.SHARED_SPACE_ENABLED,
            "shared_space_dir": str(config.SHARED_SPACE_DIR),
            "shared_space_limit_bytes": config.SHARED_SPACE_LIMIT_BYTES,
            "shared_space_used_bytes": used,
            "shared_space_free_bytes": max(config.SHARED_SPACE_LIMIT_BYTES - used, 0),
            "thumbnails_dir": str(config.THUMBNAILS_DIR),
            "registration": registration_state,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    return bp
