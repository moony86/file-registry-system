from flask import Blueprint, jsonify, request
from services.auth import require_node_token


def create_nodes_blueprint(db):
    bp = Blueprint("nodes", __name__, url_prefix="/api/nodes")

    @bp.route("/register", methods=["POST"])
    def register_node():
        if not require_node_token():
            return jsonify({"error": "Unauthorized node"}), 401

        data = request.get_json(force=True)
        try:
            db.register_node(
                node_id=data["node_id"],
                host=data["host"],
                port=int(data["port"]),
                shared_space_enabled=bool(data.get("shared_space_enabled", False)),
                shared_space_limit_bytes=int(data.get("shared_space_limit_bytes", 0)),
                shared_space_used_bytes=int(data.get("shared_space_used_bytes", 0)),
            )
            return jsonify({"status": "registered", "node_id": data["node_id"]}), 200
        except KeyError as exc:
            return jsonify({"error": f"Missing field: {exc}"}), 400
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @bp.route("/heartbeat", methods=["POST"])
    def heartbeat():
        if not require_node_token():
            return jsonify({"error": "Unauthorized node"}), 401

        data = request.get_json(force=True)
        ok = db.update_heartbeat(
            data.get("node_id"),
            shared_space_used_bytes=data.get("shared_space_used_bytes"),
        )
        if ok:
            return jsonify({"status": "alive"}), 200
        return jsonify({"error": "Node not found"}), 404

    @bp.route("", methods=["GET"])
    def list_nodes():
        nodes = db.get_online_nodes()
        return jsonify({"count": len(nodes), "nodes": nodes}), 200

    return bp
