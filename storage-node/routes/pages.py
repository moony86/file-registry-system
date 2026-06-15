from flask import Blueprint, jsonify


def create_pages_blueprint(config):
    bp = Blueprint("pages", __name__)

    @bp.route("/")
    def index():
        return jsonify({
            "service": "FSYS Storage Node",
            "version": "2.2.0-secure-cached",
            "node_id": config.NODE_ID,
            "host": config.NODE_HOST,
            "port": config.NODE_PORT,
            "master": config.MASTER_URL,
            "shared_space_enabled": config.SHARED_SPACE_ENABLED,
            "shared_space_dir": str(config.SHARED_SPACE_DIR),
        })

    return bp
