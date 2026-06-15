from flask import Blueprint, jsonify
from services.auth import require_node_token


def create_debug_blueprint(config, space_cache):
    bp = Blueprint("debug", __name__, url_prefix="/api/debug")

    @bp.route("/resync", methods=["POST"])
    def force_resync():
        if not require_node_token(config.NODE_TOKEN):
            return jsonify({"error": "Unauthorized"}), 401

        space_cache.resync_from_disk()
        return jsonify({"status": "success", "shared_space_used_bytes": space_cache.used()})

    return bp
