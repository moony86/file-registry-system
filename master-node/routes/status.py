import time
from flask import Blueprint, jsonify


def create_status_blueprint(db):
    bp = Blueprint("status", __name__, url_prefix="/api")

    @bp.route("/status", methods=["GET"])
    def system_status():
        nodes = db.get_online_nodes()
        return jsonify({
            "online_nodes": len(nodes),
            "nodes": nodes,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        }), 200

    return bp
