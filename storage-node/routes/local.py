from pathlib import Path, PureWindowsPath
import mimetypes
import os

from flask import Blueprint, current_app, jsonify, request

from services.auth import require_node_token
from services.media import detect_media_type


def create_local_blueprint(config):
    bp = Blueprint("local", __name__, url_prefix="/api/local")

    def configured_libraries():
        raw_dirs = os.getenv("LOCAL_LIBRARY_DIRS", "").strip()
        if not raw_dirs:
            current_app.logger.warning("LOCAL_LIBRARY_DIRS is empty; local browsing is disabled")
            return []

        libraries = []
        for index, value in enumerate(raw_dirs.split(",")):
            raw_path = value.strip()
            if not raw_path:
                continue
            path = Path(raw_path).expanduser().resolve()
            libraries.append({
                "id": f"lib_{index}",
                "path": str(path),
                "exists": path.exists() and path.is_dir(),
                "_path": path,
            })
        return libraries

    def public_library(library):
        return {
            "id": library["id"],
            "path": library["path"],
            "exists": library["exists"],
        }

    def get_library(library_id):
        for library in configured_libraries():
            if library["id"] == library_id:
                return library
        return None

    def is_absolute_query_path(relative_path):
        if Path(relative_path).is_absolute():
            return True
        return PureWindowsPath(relative_path).is_absolute()

    def resolve_inside(base_path, relative_path):
        relative_path = (relative_path or "").strip()
        if is_absolute_query_path(relative_path):
            raise ValueError("Absolute paths are not allowed")

        target = (base_path / relative_path).resolve()
        try:
            target.relative_to(base_path.resolve())
        except ValueError as exc:
            raise PermissionError("Path is outside the selected library") from exc
        return target

    def is_hidden_or_system(path):
        name = path.name
        return name.startswith(".") or name in {"System Volume Information", "$RECYCLE.BIN"}

    def item_to_dict(base_path, path):
        relative_path = path.relative_to(base_path).as_posix()
        if path.is_dir():
            return {
                "name": path.name,
                "type": "directory",
                "relative_path": relative_path,
            }

        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return {
            "name": path.name,
            "type": "file",
            "relative_path": relative_path,
            "full_path": str(path),
            "size_bytes": path.stat().st_size,
            "media_type": detect_media_type(mime_type, path.name),
            "mime_type": mime_type,
        }

    @bp.route("/libraries", methods=["GET"])
    def list_local_libraries():
        if not require_node_token(config.NODE_TOKEN):
            return jsonify({"error": "Unauthorized"}), 401

        libraries = [public_library(library) for library in configured_libraries()]
        return jsonify({"libraries": libraries}), 200

    @bp.route("/browse", methods=["GET"])
    def browse_local_library():
        if not require_node_token(config.NODE_TOKEN):
            return jsonify({"error": "Unauthorized"}), 401

        library_id = request.args.get("library_id", "")
        relative_path = request.args.get("path", "")
        library = get_library(library_id)
        if not library:
            return jsonify({"error": "Library not found", "library_id": library_id}), 404
        if not library["exists"]:
            return jsonify({"error": "Library path does not exist", "library_id": library_id}), 404

        base_path = library["_path"]
        try:
            target = resolve_inside(base_path, relative_path)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except PermissionError as exc:
            return jsonify({"error": str(exc)}), 403

        if not target.exists():
            return jsonify({"error": "Path not found"}), 404
        if not target.is_dir():
            return jsonify({"error": "Browse path must be a directory"}), 400

        items = []
        try:
            for child in target.iterdir():
                if is_hidden_or_system(child):
                    continue
                if child.is_dir() or child.is_file():
                    items.append(item_to_dict(base_path, child))
        except PermissionError:
            return jsonify({"error": "Permission denied while reading directory"}), 403

        items.sort(key=lambda item: (item["type"] != "directory", item["name"].lower()))
        current_relative = target.relative_to(base_path).as_posix()
        parent_path = ""
        if current_relative != ".":
            parent = target.parent
            try:
                parent_path = "" if parent == base_path else parent.relative_to(base_path).as_posix()
            except ValueError:
                parent_path = ""

        return jsonify({
            "library_id": library["id"],
            "base_path": library["path"],
            "relative_path": "" if current_relative == "." else current_relative,
            "parent_path": parent_path,
            "items": items,
        }), 200

    return bp
