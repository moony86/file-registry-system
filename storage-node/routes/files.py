from flask import Blueprint, Response, current_app, jsonify, request, send_file
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

        incoming_bytes = request.content_length or 0
        free_bytes = max(config.SHARED_SPACE_LIMIT_BYTES - space_cache.used(), 0)
        multipart_overhead_allowance = 1024 * 1024
        if incoming_bytes and incoming_bytes > free_bytes + multipart_overhead_allowance:
            return jsonify({
                "error": "Shared Space quota exceeded",
                "used_bytes": space_cache.used(),
                "free_bytes": free_bytes,
                "limit_bytes": config.SHARED_SPACE_LIMIT_BYTES,
                "incoming_bytes": incoming_bytes,
            }), 507

        if "file" not in request.files:
            return jsonify({"error": "Missing multipart file field named 'file'"}), 400

        upload = request.files["file"]
        owner = request.form.get("owner", "anonymous")
        location_type = request.form.get("location_type", "CACHED")
        original_name = Path(upload.filename or "uploaded.bin").name

        config.SHARED_SPACE_DIR.mkdir(parents=True, exist_ok=True)
        temp_path = config.SHARED_SPACE_DIR / f".upload-{time.time_ns()}"
        current_app.logger.info("Created temp upload: %s", temp_path)
        final_path = None
        moved_to_shared = False
        size_bytes = 0
        deduped = False

        def remove_temp_upload(reason):
            try:
                if temp_path.exists():
                    temp_path.unlink()
                    current_app.logger.info("Removed temp upload: %s reason=%s", temp_path, reason)
            except Exception:
                current_app.logger.exception("Failed to remove temp upload: %s reason=%s", temp_path, reason)

        try:
            upload.save(temp_path)
            size_bytes = temp_path.stat().st_size

            content_hash = sha256_file(temp_path)
            final_path = path_for_hash(config.SHARED_SPACE_DIR, content_hash, original_name)
            final_path.parent.mkdir(parents=True, exist_ok=True)

            if final_path.exists():
                remove_temp_upload("duplicate-content")
                deduped = True
            else:
                if space_cache.used() + size_bytes > config.SHARED_SPACE_LIMIT_BYTES:
                    remove_temp_upload("quota-exceeded-after-save")
                    return jsonify({
                        "error": "Shared Space quota exceeded",
                        "used_bytes": space_cache.used(),
                        "limit_bytes": config.SHARED_SPACE_LIMIT_BYTES,
                        "incoming_bytes": size_bytes,
                    }), 507

                try:
                    shutil.move(str(temp_path), str(final_path))
                    space_cache.add(size_bytes)
                    moved_to_shared = True
                    deduped = False
                    if temp_path.exists():
                        remove_temp_upload("post-move-leftover")
                except Exception:
                    remove_temp_upload("move-failed")
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

            if response.status_code >= 400:
                current_app.logger.error(
                    "Master rejected upload registration: status=%s body=%s",
                    response.status_code,
                    response.text[:500],
                )
                if moved_to_shared and final_path and final_path.exists():
                    final_path.unlink(missing_ok=True)
                    space_cache.subtract(size_bytes)
                try:
                    payload = response.json()
                except Exception:
                    payload = {"error": response.text or "Master registry rejected upload"}
                return jsonify(payload), response.status_code

            try:
                result = response.json()
            except Exception:
                current_app.logger.exception(
                    "Master returned a non-JSON response while registering upload: status=%s body=%s",
                    response.status_code,
                    response.text[:500],
                )
                if moved_to_shared and final_path and final_path.exists():
                    final_path.unlink(missing_ok=True)
                    space_cache.subtract(size_bytes)
                return jsonify({
                    "error": "Master registry returned a non-JSON response",
                    "master_status_code": response.status_code,
                }), 502

            result["deduped_on_node"] = deduped
            result["shared_space_path"] = str(final_path)
            result["shared_space_used_bytes"] = space_cache.used()
            result["media_type"] = media_type
            return jsonify(result), response.status_code

        except Exception as exc:
            current_app.logger.exception(
                "Cache upload failed: file_name=%s owner=%s location_type=%s temp_path=%s",
                original_name,
                owner,
                location_type,
                temp_path,
            )
            remove_temp_upload("exception")
            if moved_to_shared and final_path and final_path.exists():
                try:
                    final_path.unlink(missing_ok=True)
                    space_cache.subtract(size_bytes)
                except Exception:
                    current_app.logger.exception("Failed to clean up unregistered shared-space file: %s", final_path)
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


    @bp.route("/<file_id>/stream", methods=["GET"])
    def stream_file(file_id):
        try:
            response = master_client.get_file_location(file_id, access_type="stream_location")
            if response.status_code == 404:
                return jsonify({"error": "File not found in registry"}), 404
            if response.status_code != 200:
                return jsonify({"error": "Unable to resolve file location"}), response.status_code

            file_info = response.json()
            if file_info["node"]["id"] != config.NODE_ID:
                return jsonify({"error": "This node is not the selected source for this file"}), 409

            if file_info.get("media_type") != "video":
                return jsonify({"error": "Only video files can be streamed"}), 415

            physical_path = safe_existing_file_path(file_info["physical_path"])
            file_size = physical_path.stat().st_size
            mime_type = file_info.get("mime_type") or "application/octet-stream"
            range_header = request.headers.get("Range")
            chunk_size = 1024 * 1024

            def range_not_satisfiable():
                return Response(
                    status=416,
                    headers={
                        "Accept-Ranges": "bytes",
                        "Content-Range": f"bytes */{file_size}",
                    },
                )

            start = 0
            end = file_size - 1
            status_code = 200

            if range_header:
                if not range_header.startswith("bytes=") or "," in range_header:
                    return range_not_satisfiable()

                range_value = range_header.removeprefix("bytes=").strip()
                if "-" not in range_value:
                    return range_not_satisfiable()

                start_text, end_text = range_value.split("-", 1)
                try:
                    if start_text == "":
                        suffix_length = int(end_text)
                        if suffix_length <= 0:
                            return range_not_satisfiable()
                        start = max(file_size - suffix_length, 0)
                    else:
                        start = int(start_text)
                        if end_text:
                            end = int(end_text)
                except ValueError:
                    return range_not_satisfiable()

                if start < 0 or end < start or start >= file_size:
                    return range_not_satisfiable()

                end = min(end, file_size - 1)
                status_code = 206

            content_length = end - start + 1

            def generate_chunks():
                remaining = content_length
                with physical_path.open("rb") as file:
                    file.seek(start)
                    while remaining > 0:
                        chunk = file.read(min(chunk_size, remaining))
                        if not chunk:
                            break
                        remaining -= len(chunk)
                        yield chunk

            headers = {
                "Accept-Ranges": "bytes",
                "Content-Type": mime_type,
                "Content-Length": str(content_length),
            }
            if status_code == 206:
                headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"

            return Response(generate_chunks(), status=status_code, headers=headers, direct_passthrough=True)

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


    @bp.route("/<file_id>/restore-from-trash", methods=["POST"])
    def restore_from_trash(file_id):
        if not require_node_token():
            return jsonify({"error": "Unauthorized"}), 401

        data = request.get_json(force=True) or {}
        content_hash = data.get("content_hash")
        raw_trash_path = data.get("trash_path")
        location_type = data.get("location_type", "LOCAL")

        if location_type not in {"CACHED", "PINNED", "REPLICATED"}:
            return jsonify({
                "status": "skipped",
                "reason": "Only managed Shared Space copies can be restored",
                "location_type": location_type,
            }), 200

        if not content_hash or not raw_trash_path:
            return jsonify({"error": "Missing content_hash or trash_path"}), 400

        try:
            import re

            trash_root = getattr(config, "TRASH_DIR", config.SHARED_SPACE_DIR.parent / "trash")
            trash_path = Path(raw_trash_path).expanduser().resolve()

            def find_matching_trash_path():
                if not trash_root.exists():
                    return None, None

                mismatches = []
                for candidate in trash_root.rglob(f"{file_id}-*"):
                    if not candidate.is_file():
                        continue
                    try:
                        candidate.resolve().relative_to(trash_root.resolve())
                    except Exception:
                        continue

                    actual_hash = sha256_file(candidate)
                    if actual_hash == content_hash:
                        return candidate.resolve(), None
                    mismatches.append({
                        "path": str(candidate.resolve()),
                        "actual": actual_hash,
                    })

                if mismatches:
                    return None, mismatches
                return None, None

            if not trash_path.exists() or not trash_path.is_file():
                fallback_path, mismatches = find_matching_trash_path()
                if fallback_path:
                    trash_path = fallback_path
                elif mismatches:
                    return jsonify({
                        "error": "Trash candidate hash mismatch",
                        "expected": content_hash,
                        "candidates": mismatches,
                    }), 409
                else:
                    return jsonify({"status": "already_missing", "path": str(trash_path)}), 200

            # Safety: ensure this is inside the node's trash directory
            try:
                trash_path.resolve().relative_to(trash_root.resolve())
            except Exception:
                if is_path_inside(config.SHARED_SPACE_DIR, trash_path):
                    actual_hash = sha256_file(trash_path)
                    if actual_hash == content_hash:
                        return jsonify({
                            "status": "already_restored",
                            "reason": "content already exists in shared space",
                            "shared_space_path": str(trash_path),
                        }), 200

                fallback_path, mismatches = find_matching_trash_path()
                if fallback_path:
                    trash_path = fallback_path
                elif mismatches:
                    return jsonify({
                        "error": "Trash candidate hash mismatch",
                        "expected": content_hash,
                        "candidates": mismatches,
                    }), 409
                else:
                    return jsonify({"error": "Refusing to restore file outside TRASH_DIR", "path": str(trash_path)}), 403

            # Derive original filename from trash entry. Trash names were created as:
            #   {file_id}-{source_name}  or {file_id}-{counter}-{source_name}
            m = re.match(r'^' + re.escape(str(file_id)) + r'(?:-\d+)?-(.+)$', trash_path.name)
            if m:
                original_name = m.group(1)
            else:
                original_name = trash_path.name

            final_path = path_for_hash(config.SHARED_SPACE_DIR, content_hash, original_name)
            final_path.parent.mkdir(parents=True, exist_ok=True)

            size_bytes = trash_path.stat().st_size

            if final_path.exists():
                # Verify existing shared-space file matches expected content hash before deleting trash copy
                actual_hash = sha256_file(final_path)
                if actual_hash != content_hash:
                    return jsonify({
                        "error": "Existing shared_space file hash mismatch",
                        "expected": content_hash,
                        "actual": actual_hash,
                    }), 409

                trash_path.unlink(missing_ok=True)
                return jsonify({
                    "status": "already_restored",
                    "reason": "content already exists in shared space",
                    "shared_space_path": str(final_path)
                }), 200

            shutil.move(str(trash_path), str(final_path))

            # Verify checksum after restore to avoid swapping in incorrect file
            actual_hash = sha256_file(final_path)
            if actual_hash != content_hash:
                # Move it back to trash and report error
                try:
                    shutil.move(str(final_path), str(trash_path))
                except Exception:
                    pass
                return jsonify({
                    "error": "Checksum mismatch after restore",
                    "expected": content_hash,
                    "actual": actual_hash,
                }), 409

            try:
                # Increase recorded used bytes
                space_cache.add(size_bytes)
            except Exception:
                pass

            # Best-effort cleanup of empty trash directory
            try:
                trash_path.parent.rmdir()
            except OSError:
                pass

            return jsonify({
                "status": "restored",
                "content_hash": content_hash,
                "shared_space_path": str(final_path),
                "size_bytes": size_bytes,
            }), 200

        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    return bp
