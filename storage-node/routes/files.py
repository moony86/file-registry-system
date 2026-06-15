from flask import Blueprint, jsonify, request, send_file
from pathlib import Path
import mimetypes
import shutil
import time
from datetime import datetime

from services.hashing import sha256_file, path_for_hash, safe_existing_file_path
from services.media import detect_media_type


def create_files_blueprint(config, space_cache, master_client):
    bp = Blueprint("files", __name__, url_prefix="/api/files")

    def require_node_token():
        return request.headers.get("X-FSYS-Token") == config.NODE_TOKEN

    def is_path_inside(base_dir: Path, target_path: Path) -> bool:
        try:
            target_path.resolve().relative_to(base_dir.resolve())
            return True
        except ValueError:
            return False


    @bp.route("/register", methods=["POST"])
    def register_local_file():
        data = request.get_json(force=True)
        try:
            source_path = safe_existing_file_path(data.get("physical_path", ""))
            content_hash = data.get("content_hash") or sha256_file(source_path)
            size_bytes = source_path.stat().st_size

            mime_type = (
                data.get("mime_type")
                or mimetypes.guess_type(source_path.name)[0]
                or "application/octet-stream"
            )
            file_name = data.get("file_name", source_path.name)
            media_type = detect_media_type(mime_type, file_name)

            response = master_client.register_file(
                content_hash=content_hash,
                file_name=file_name,
                owner=data.get("owner", "anonymous"),
                size_bytes=size_bytes,
                mime_type=mime_type,
                media_type=media_type,
                physical_path=str(source_path),
                location_type="LOCAL",
            )
            return response.json(), response.status_code
        except FileNotFoundError as exc:
            return jsonify({"error": str(exc)}), 404
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @bp.route("/cache", methods=["POST"])
    def cache_upload():
        if not config.SHARED_SPACE_ENABLED:
            return jsonify({"error": "Shared Space is disabled on this node"}), 409

        if "file" not in request.files:
            return jsonify({"error": "Missing multipart file field named 'file'"}), 400

        upload = request.files["file"]
        owner = request.form.get("owner", "anonymous")
        location_type = request.form.get("location_type", "CACHED")
        original_name = Path(upload.filename or "uploaded.bin").name

        temp_path = config.SHARED_SPACE_DIR / f".upload-{time.time_ns()}"
        try:
            upload.save(temp_path)
            size_bytes = temp_path.stat().st_size

            content_hash = sha256_file(temp_path)
            final_path = path_for_hash(config.SHARED_SPACE_DIR, content_hash, original_name)
            final_path.parent.mkdir(parents=True, exist_ok=True)

            if final_path.exists():
                temp_path.unlink(missing_ok=True)
                deduped = True
            else:
                if space_cache.used() + size_bytes > config.SHARED_SPACE_LIMIT_BYTES:
                    temp_path.unlink(missing_ok=True)
                    return jsonify({
                        "error": "Shared Space quota exceeded",
                        "used_bytes": space_cache.used(),
                        "limit_bytes": config.SHARED_SPACE_LIMIT_BYTES,
                        "incoming_bytes": size_bytes,
                    }), 507

                try:
                    shutil.move(str(temp_path), str(final_path))
                    space_cache.add(size_bytes)
                    deduped = False
                except Exception:
                    temp_path.unlink(missing_ok=True)
                    raise

            mime_type = mimetypes.guess_type(original_name)[0] or "application/octet-stream"
            media_type = detect_media_type(mime_type, original_name)

            response = master_client.register_file(
                content_hash=content_hash,
                file_name=original_name,
                owner=owner,
                size_bytes=size_bytes,
                mime_type=mime_type,
                media_type=media_type,
                physical_path=str(final_path),
                location_type=location_type,
            )

            result = response.json()
            result["deduped_on_node"] = deduped
            result["shared_space_path"] = str(final_path)
            result["shared_space_used_bytes"] = space_cache.used()
            result["media_type"] = media_type
            return jsonify(result), response.status_code

        except Exception as exc:
            temp_path.unlink(missing_ok=True)
            return jsonify({"error": str(exc)}), 500

    @bp.route("/<file_id>/download", methods=["GET"])
    def download_file(file_id):
        try:
            response = master_client.get_file_location(file_id)
            if response.status_code != 200:
                return jsonify({"error": "File not found in registry"}), 404

            file_info = response.json()
            if file_info["node"]["id"] != config.NODE_ID:
                return jsonify({"error": "This node is not the selected source for this file"}), 409

            physical_path = safe_existing_file_path(file_info["physical_path"])
            actual_hash = sha256_file(physical_path)
            if actual_hash != file_info["content_hash"]:
                return jsonify({
                    "error": "Checksum mismatch; refusing to serve corrupted or replaced file",
                    "expected": file_info["content_hash"],
                    "actual": actual_hash,
                }), 409

            return send_file(
                physical_path,
                as_attachment=True,
                download_name=file_info["file_name"],
            )

        except FileNotFoundError as exc:
            return jsonify({"error": str(exc)}), 410
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500


    @bp.route("/<file_id>/trash", methods=["POST"])
    def trash_managed_file(file_id):
        """
        Move a managed Shared Space copy to node-local trash.

        This endpoint must never touch arbitrary LOCAL user files. It only accepts
        paths inside SHARED_SPACE_DIR and only for managed location types.
        """
        if not require_node_token():
            return jsonify({"error": "Unauthorized"}), 401

        data = request.get_json(force=True) or {}
        content_hash = data.get("content_hash")
        raw_path = data.get("physical_path")
        location_type = data.get("location_type", "LOCAL")

        if location_type not in {"CACHED", "PINNED", "REPLICATED"}:
            return jsonify({
                "status": "skipped",
                "reason": "Only managed Shared Space copies can be moved to trash",
                "location_type": location_type,
            }), 200

        if not content_hash or not raw_path:
            return jsonify({"error": "Missing content_hash or physical_path"}), 400

        try:
            source_path = Path(raw_path).expanduser().resolve()

            if not source_path.exists() or not source_path.is_file():
                return jsonify({
                    "status": "already_missing",
                    "path": str(source_path),
                }), 200

            if not is_path_inside(config.SHARED_SPACE_DIR, source_path):
                return jsonify({
                    "error": "Refusing to trash file outside SHARED_SPACE_DIR",
                    "path": str(source_path),
                }), 403

            actual_hash = sha256_file(source_path)
            if actual_hash != content_hash:
                return jsonify({
                    "error": "Checksum mismatch; refusing to move unexpected file",
                    "expected": content_hash,
                    "actual": actual_hash,
                }), 409

            size_bytes = source_path.stat().st_size
            trash_root = getattr(config, "TRASH_DIR", config.SHARED_SPACE_DIR.parent / "trash")
            trash_dir = trash_root / datetime.utcnow().strftime("%Y-%m-%d")
            trash_dir.mkdir(parents=True, exist_ok=True)

            safe_name = f"{file_id}-{source_path.name}"
            trash_path = trash_dir / safe_name
            counter = 1
            while trash_path.exists():
                trash_path = trash_dir / f"{file_id}-{counter}-{source_path.name}"
                counter += 1

            shutil.move(str(source_path), str(trash_path))
            space_cache.subtract(size_bytes)

            # Best-effort cleanup of now-empty hash shard directory.
            try:
                source_path.parent.rmdir()
            except OSError:
                pass

            return jsonify({
                "status": "trashed",
                "file_id": str(file_id),
                "content_hash": content_hash,
                "size_bytes": size_bytes,
                "trash_path": str(trash_path),
            }), 200

        except Exception as exc:
            return jsonify({"error": str(exc)}), 500


    return bp
