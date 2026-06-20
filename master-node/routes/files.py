from flask import Blueprint, Response, current_app, jsonify, redirect, request
import requests
from services.auth import require_node_token


def create_files_blueprint(db):
    bp = Blueprint("files", __name__, url_prefix="/api")

    @bp.route("/files/register", methods=["POST"])
    def register_file():
        """Register an alias + content hash + source location. No file upload here."""
        if not require_node_token():
            return jsonify({"error": "Unauthorized node"}), 401

        data = request.get_json(force=True)
        required = ["content_hash", "file_name", "size_bytes", "node_id", "physical_path"]
        missing = [key for key in required if not data.get(key)]
        if missing:
            return jsonify({"error": "Missing required fields", "fields": missing}), 400

        try:
            file_id = db.register_content_alias(
                content_hash=data["content_hash"],
                file_name=data["file_name"],
                owner=data.get("owner", "anonymous"),
                size_bytes=int(data["size_bytes"]),
                mime_type=data.get("mime_type", "application/octet-stream"),
                media_type=data.get("media_type", "other"),
                node_id=data["node_id"],
                physical_path=data["physical_path"],
                location_type=data.get("location_type", "LOCAL"),
            )
            technical_metadata = data.get("technical_metadata")
            if technical_metadata:
                try:
                    db.upsert_technical_metadata(data["content_hash"], technical_metadata)
                except Exception:
                    current_app.logger.warning(
                        "Failed to save technical metadata for content_hash=%s",
                        data["content_hash"],
                        exc_info=True,
                    )
            thumbnail_metadata = data.get("thumbnail_metadata")
            if thumbnail_metadata:
                try:
                    db.upsert_thumbnail_metadata(data["content_hash"], thumbnail_metadata)
                except Exception:
                    current_app.logger.warning(
                        "Failed to save thumbnail metadata for content_hash=%s",
                        data["content_hash"],
                        exc_info=True,
                    )
            return jsonify({
                "status": "registered",
                "file_id": str(file_id),
                "content_hash": data["content_hash"],
                "dedupe_key": data["content_hash"],
                "message": "Alias and content location registered",
            }), 201
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @bp.route("/contents/<content_hash>/locations", methods=["POST"])
    def add_content_location(content_hash):
        if not require_node_token():
            return jsonify({"error": "Unauthorized node"}), 401

        data = request.get_json(force=True)
        try:
            db.upsert_content_location(
                content_hash=content_hash,
                node_id=data["node_id"],
                physical_path=data["physical_path"],
                location_type=data.get("location_type", "LOCAL"),
                is_primary=bool(data.get("is_primary", False)),
            )
            return jsonify({"status": "location_registered", "content_hash": content_hash}), 200
        except KeyError as exc:
            return jsonify({"error": f"Missing field: {exc}"}), 400
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @bp.route("/files/<file_id>/location", methods=["GET"])
    def get_file_location(file_id):
        access_type = request.args.get("access_type", "download_location")
        is_stream_location = access_type == "stream_location"
        loc = db.get_best_location(file_id, record_access=not is_stream_location)
        if not loc:
            return jsonify({"error": "File not found or no online locations", "file_id": file_id}), 404

        if not is_stream_location:
            db.log_access(
                file_id=file_id,
                content_hash=loc["content_hash"],
                client_ip=request.remote_addr,
                access_type=access_type,
            )

        return jsonify({
            "file_id": str(file_id),
            "file_name": loc["file_name"],
            "owner": loc["owner"],
            "file_size": loc["size_bytes"],
            "mime_type": loc["mime_type"],
            "media_type": loc.get("media_type", "other"),
            "content_hash": loc["content_hash"],
            "location_type": loc["location_type"],
            "node": {
                "id": loc["node_id"],
                "host": loc["host"],
                "port": loc["port"],
                "status": loc["node_status"],
                "shared_space_enabled": loc["shared_space_enabled"],
            },
            "physical_path": loc["physical_path"],
            "is_primary": loc["is_primary"],
        }), 200

    @bp.route("/files/<file_id>", methods=["GET"])
    def get_file_info(file_id):
        locations = db.get_file_locations(file_id)
        if not locations:
            locations = db.get_locations_for_file(file_id)
        if not locations:
            return jsonify({"error": "File not found"}), 404

        first = locations[0]
        technical_metadata = db.get_technical_metadata(first["content_hash"])
        thumbnail_metadata = db.get_thumbnail_metadata(first["content_hash"])
        return jsonify({
            "file_id": str(file_id),
            "file_name": first["file_name"],
            "owner": first["owner"],
            "file_size": first["size_bytes"],
            "mime_type": first["mime_type"],
            "media_type": first.get("media_type", "other"),
            "created_at": first.get("created_at"),
            "file_status": first.get("file_status", "ACTIVE"),
            "content_hash": first["content_hash"],
            "popularity_score": first["popularity_score"],
            "is_hot": first.get("is_hot", 0),
            "technical_metadata": technical_metadata,
            "thumbnail": thumbnail_metadata,
            "thumbnail_url": f"/api/files/{file_id}/thumbnail",
            "locations": [
                {
                    "node_id": loc["node_id"],
                    "host": loc["host"],
                    "port": loc["port"],
                    "path": loc["physical_path"],
                    "location_type": loc["location_type"],
                    "is_primary": loc["is_primary"],
                    "node_status": loc["node_status"],
                    "last_seen": loc.get("last_seen"),
                    "location_id": loc.get("location_id"),
                }
                for loc in locations if loc.get("node_id")
            ],
        }), 200

    def placeholder_svg(media_type="video"):
        label = {
            "movie": "MOVIE",
            "series": "SERIES",
            "anime": "ANIME",
            "video": "VIDEO",
        }.get(media_type or "video", "VIDEO")
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360">
  <rect width="640" height="360" fill="#111827"/>
  <rect x="24" y="24" width="592" height="312" fill="#1f2937" stroke="#374151" stroke-width="2"/>
  <circle cx="320" cy="168" r="48" fill="#0891b2" opacity="0.85"/>
  <polygon points="305,140 305,196 352,168" fill="#ecfeff"/>
  <text x="320" y="260" text-anchor="middle" font-family="Arial, sans-serif" font-size="34" font-weight="700" fill="#d1d5db">{label}</text>
</svg>"""
        return Response(svg, mimetype="image/svg+xml")

    @bp.route("/files/<file_id>/thumbnail", methods=["GET"])
    def get_file_thumbnail(file_id):
        locations = db.get_file_locations(file_id)
        if not locations:
            locations = db.get_locations_for_file(file_id)
        if not locations:
            return placeholder_svg("video")

        first = locations[0]
        thumbnail = db.get_thumbnail_metadata(first["content_hash"])
        if thumbnail and thumbnail.get("thumbnail_status") == "success":
            for loc in locations:
                if loc.get("host") and loc.get("port") and loc.get("node_status") == "ONLINE":
                    return redirect(
                        f"http://{loc['host']}:{loc['port']}/api/files/thumbnails/{first['content_hash']}",
                        code=302,
                    )

        return placeholder_svg(request.args.get("kind") or first.get("media_type", "video"))

    @bp.route("/files", methods=["GET"])
    def list_all_files():
        files = db.list_all_files()
        return jsonify({"count": len(files), "files": files}), 200

    @bp.route("/files/deleted", methods=["GET"])
    def list_deleted_files():
        try:
            files = db.list_deleted_files()
            return jsonify({"count": len(files), "files": files}), 200
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @bp.route("/files/search", methods=["GET"])
    def search_files():
        query = request.args.get("q", "")
        files = db.search_files(query)
        return jsonify({"query": query, "count": len(files), "files": files}), 200

    @bp.route("/files/<file_id>/hot", methods=["POST"])
    def set_file_hot_status(file_id):
        if not require_node_token():
            return jsonify({"error": "Unauthorized"}), 401

        data = request.get_json(force=True) or {}
        ok = db.set_file_hot_status(file_id, data.get("is_hot", 1))
        if ok:
            return jsonify({"status": "updated", "file_id": str(file_id), "is_hot": int(data.get("is_hot", 1))}), 200
        return jsonify({"error": "File not found"}), 404


    @bp.route("/files/<file_id>", methods=["DELETE"])
    def delete_file(file_id):
        """
        Safe delete:
        - Hide the file alias from library/search.
        - Ask each online node to move managed Shared Space copies to local trash.
        - Never delete LOCAL original user files.
        """
        if not require_node_token():
            return jsonify({"error": "Unauthorized"}), 401

        locations = db.get_file_locations(file_id)
        if not locations:
            return jsonify({"error": "File not found"}), 404

        data = request.get_json(silent=True) or {}
        deleted_by = data.get("deleted_by", "dev-token")

        ok = db.soft_delete_file(file_id, deleted_by=deleted_by)
        if not ok:
            return jsonify({"error": "File is already deleted or not found"}), 404

        trash_results = []
        managed_types = {"CACHED", "PINNED", "REPLICATED"}

        for loc in locations:
            location_type = loc.get("location_type")
            node_id = loc.get("node_id")
            host = loc.get("host")
            port = loc.get("port")
            node_status = loc.get("node_status")

            # LOCAL means original user path. We never touch it.
            if location_type not in managed_types:
                trash_results.append({
                    "node_id": node_id,
                    "location_type": location_type,
                    "action": "skipped",
                    "reason": "LOCAL/original files are not modified by delete"
                })
                continue

            if not host or not port or node_status != "ONLINE":
                trash_results.append({
                    "node_id": node_id,
                    "location_type": location_type,
                    "action": "skipped",
                    "reason": "node is offline or missing host/port"
                })
                continue

            try:
                response = requests.post(
                    f"http://{host}:{port}/api/files/{file_id}/trash",
                    json={
                        "content_hash": loc["content_hash"],
                        "physical_path": loc["physical_path"],
                        "location_type": location_type,
                    },
                    headers={"X-FSYS-Token": request.headers.get("X-FSYS-Token", "")},
                    timeout=10,
                )
                try:
                    payload = response.json()
                except Exception:
                    payload = {"raw": response.text}

                trash_results.append({
                    "node_id": node_id,
                    "location_type": location_type,
                    "action": "trash_requested",
                    "status_code": response.status_code,
                    "response": payload,
                })

                if response.status_code == 200 and payload.get("status") == "trashed" and payload.get("trash_path"):
                    try:
                        updated = db.update_content_location_path(
                            location_id=loc.get("location_id"),
                            physical_path=payload["trash_path"],
                            location_type=location_type,
                        )
                        if not updated:
                            trash_results[-1]["location_update_error"] = "failed to record trash path"
                    except Exception:
                        trash_results[-1]["location_update_error"] = "failed to record trash path"
            except Exception as exc:
                trash_results.append({
                    "node_id": node_id,
                    "location_type": location_type,
                    "action": "trash_failed",
                    "error": str(exc),
                })

        return jsonify({
            "status": "deleted",
            "file_id": str(file_id),
            "message": "File hidden from library. Managed copies were moved to trash where possible.",
            "trash_results": trash_results,
        }), 200


    @bp.route("/files/<file_id>/restore", methods=["POST"])
    def restore_file(file_id):
        if not require_node_token():
            return jsonify({"error": "Unauthorized"}), 401

        # Read known locations for this file (including deleted state) without
        # flipping lifecycle yet. Master will mark ACTIVE only after node successes.
        locations = db.get_locations_for_file(file_id)
        if locations is None:
            return jsonify({"error": "File not found"}), 404

        if not locations:
            return jsonify({"error": "No locations known for file"}), 404

        restore_results = []
        managed_types = {"CACHED", "PINNED", "REPLICATED"}
        successful_nodes = 0

        for loc in locations:
            if not loc.get("location_type"):
                continue
            location_type = loc.get("location_type")
            node_id = loc.get("node_id")
            host = loc.get("host")
            port = loc.get("port")
            node_status = loc.get("node_status")

            # LOCAL means original user path. We never touch it.
            if location_type not in managed_types:
                restore_results.append({
                    "node_id": node_id,
                    "location_type": location_type,
                    "action": "skipped",
                    "reason": "LOCAL/original files are not modified by restore"
                })
                continue

            if not host or not port or node_status != "ONLINE":
                restore_results.append({
                    "node_id": node_id,
                    "location_type": location_type,
                    "action": "skipped",
                    "reason": "node is offline or missing host/port"
                })
                continue

            try:
                response = requests.post(
                    f"http://{host}:{port}/api/files/{file_id}/restore-from-trash",
                    json={
                        "content_hash": loc.get("content_hash"),
                        "trash_path": loc.get("physical_path"),
                        "location_type": location_type,
                    },
                    headers={"X-FSYS-Token": request.headers.get("X-FSYS-Token", "")},
                    timeout=10,
                )
                try:
                    payload = response.json()
                except Exception:
                    payload = {"raw": response.text}

                restore_results.append({
                    "node_id": node_id,
                    "location_type": location_type,
                    "action": "restore_requested",
                    "status_code": response.status_code,
                    "response": payload,
                })

                # On success, update registry location and count success
                if response.status_code == 200 and payload.get("status") in ("restored", "already_restored"):
                    successful_nodes += 1
                    shared_path = payload.get("shared_space_path")
                    if shared_path:
                        try:
                            updated = db.update_content_location_path(
                                location_id=loc.get("location_id"),
                                physical_path=shared_path,
                                location_type=location_type,
                            )
                            if not updated:
                                db.upsert_content_location(
                                    content_hash=loc.get("content_hash"),
                                    node_id=node_id,
                                    physical_path=shared_path,
                                    location_type=location_type,
                                )
                        except Exception:
                            # Don't fail the whole operation for a write error; record it
                            restore_results[-1]["location_update_error"] = "failed to update registry location"

            except Exception as exc:
                restore_results.append({
                    "node_id": node_id,
                    "location_type": location_type,
                    "action": "restore_failed",
                    "error": str(exc),
                })

        reactivated = False
        if successful_nodes > 0:
            try:
                ok = db.restore_file(file_id)
                reactivated = bool(ok)
            except Exception:
                reactivated = False

        return jsonify({
            "status": "restore_attempted",
            "file_id": str(file_id),
            "reactivated": reactivated,
            "successful_nodes": successful_nodes,
            "restore_results": restore_results,
        }), 200

    return bp
