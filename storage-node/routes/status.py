from flask import Blueprint, jsonify


def create_status_blueprint(config, space_cache):
    bp = Blueprint("status", __name__, url_prefix="/api")

    @bp.route("/status", methods=["GET"])
    def node_status():
        used = space_cache.used()
        return jsonify({
            "node_id": config.NODE_ID,
            "status": "online",
            "host": config.NODE_HOST,
            "port": config.NODE_PORT,
            "shared_space_enabled": config.SHARED_SPACE_ENABLED,
            "shared_space_limit_bytes": config.SHARED_SPACE_LIMIT_BYTES,
            "shared_space_used_bytes": used,
            "shared_space_free_bytes": max(config.SHARED_SPACE_LIMIT_BYTES - used, 0),
        })

    return bp
