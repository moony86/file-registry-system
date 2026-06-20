import re
import time
from pathlib import Path

from flask import Blueprint, jsonify, request, send_file
from werkzeug.utils import secure_filename


def _optional_int(value):
    if value in (None, ""):
        return None
    return int(value)


SUBTITLES_ROOT = Path(__file__).resolve().parents[1] / "subtitles"
SUPPORTED_SUBTITLE_FORMATS = {"srt", "vtt", "ass"}


def _subtitle_format(filename):
    suffix = Path(filename or "").suffix.lower().lstrip(".")
    return suffix if suffix in SUPPORTED_SUBTITLE_FORMATS else "unknown"


def _bool_form(value):
    return str(value or "").lower() in {"1", "true", "yes", "on"}


def convert_srt_to_vtt(srt_path, vtt_path):
    text = Path(srt_path).read_text(encoding="utf-8-sig", errors="replace")
    text = re.sub(
        r"(\d{2}:\d{2}:\d{2}),(\d{3})",
        r"\1.\2",
        text,
    )
    Path(vtt_path).write_text("WEBVTT\n\n" + text.strip() + "\n", encoding="utf-8")


def create_media_blueprint(db):
    bp = Blueprint("media", __name__, url_prefix="/api/media")

    @bp.route("/collections", methods=["GET"])
    def list_collections():
        try:
            collections = db.list_media_collections()
            return jsonify({"count": len(collections), "collections": collections}), 200
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @bp.route("/collections", methods=["POST"])
    def create_collection():
        data = request.get_json(force=True) or {}
        try:
            collection = db.create_media_collection(
                title=data.get("title"),
                collection_type=data.get("collection_type", "unknown"),
            )
            return jsonify({"status": "created", "collection": collection}), 201
        except (TypeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @bp.route("/collections/<int:collection_id>", methods=["DELETE"])
    def delete_collection(collection_id):
        try:
            result = db.delete_media_collection(collection_id)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

        if result.get("status") == "not_found":
            return jsonify(result), 404
        if result.get("status") == "not_empty":
            return jsonify(result), 409
        return jsonify(result), 200

    @bp.route("/library", methods=["GET"])
    def get_library():
        try:
            return jsonify(db.get_media_library_grouped()), 200
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @bp.route("/library/videos", methods=["GET"])
    def list_library_videos():
        try:
            items = db.list_media_items(include_deleted=False)
            return jsonify({"count": len(items), "items": items}), 200
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @bp.route("/drafts", methods=["GET"])
    def list_drafts():
        review_status = request.args.get("review_status", "pending")
        try:
            drafts = db.list_media_drafts(review_status=review_status)
            return jsonify({"count": len(drafts), "drafts": drafts}), 200
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @bp.route("/drafts/<int:draft_id>", methods=["GET"])
    def get_draft(draft_id):
        draft = db.get_media_draft(draft_id)
        if not draft:
            return jsonify({"error": "Draft not found", "draft_id": draft_id}), 404
        return jsonify(draft), 200

    @bp.route("/drafts/<int:draft_id>", methods=["PATCH"])
    def update_draft(draft_id):
        data = request.get_json(force=True) or {}
        try:
            ok = db.update_media_draft(
                draft_id=draft_id,
                user_media_kind=data.get("media_kind"),
                user_title=data.get("final_title"),
                collection_id=_optional_int(data.get("collection_id")),
                collection_title=data.get("collection_title"),
                collection_type=data.get("collection_type", "unknown"),
                season_number=_optional_int(data.get("season_number")),
                episode_number=_optional_int(data.get("episode_number")),
            )
        except (TypeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

        if not ok:
            return jsonify({"error": "Draft not found or not pending", "draft_id": draft_id}), 404

        draft = db.get_media_draft(draft_id)
        return jsonify({"status": "saved", "draft": draft}), 200

    @bp.route("/drafts/<int:draft_id>/approve", methods=["POST"])
    def approve_draft(draft_id):
        data = request.get_json(force=True) or {}
        try:
            ok = db.approve_media_draft(
                draft_id=draft_id,
                final_media_kind=data.get("final_media_kind"),
                final_title=data.get("final_title"),
                year=_optional_int(data.get("year")),
                season=_optional_int(data.get("season")),
                episode=_optional_int(data.get("episode")),
                language=data.get("language"),
                reviewed_by=data.get("reviewed_by", "dashboard-dev"),
                collection_id=_optional_int(data.get("collection_id")),
                collection_title=data.get("collection_title"),
                collection_type=data.get("collection_type", "unknown"),
                season_number=_optional_int(data.get("season_number")),
                episode_number=_optional_int(data.get("episode_number")),
                display_order=_optional_int(data.get("display_order")),
            )
        except (TypeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

        if not ok:
            return jsonify({"error": "Draft not found or not pending", "draft_id": draft_id}), 404

        draft = db.get_media_draft(draft_id)
        return jsonify({"status": "approved", "draft": draft}), 200

    @bp.route("/drafts/<int:draft_id>/reject", methods=["POST"])
    def reject_draft(draft_id):
        data = request.get_json(force=True) or {}
        try:
            ok = db.reject_media_draft(
                draft_id=draft_id,
                reviewed_by=data.get("reviewed_by", "dashboard-dev"),
                reason=data.get("reason"),
            )
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

        if not ok:
            return jsonify({"error": "Draft not found or not pending", "draft_id": draft_id}), 404

        draft = db.get_media_draft(draft_id)
        return jsonify({"status": "rejected", "draft": draft}), 200

    @bp.route("/files/<file_id>", methods=["GET"])
    def get_media_for_file(file_id):
        try:
            return jsonify(db.get_media_for_file(file_id)), 200
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @bp.route("/files/<file_id>/neighbors", methods=["GET"])
    def get_media_neighbors(file_id):
        try:
            return jsonify(db.get_media_neighbors(file_id)), 200
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @bp.route("/files/<file_id>", methods=["PATCH"])
    def update_media_for_file(file_id):
        data = request.get_json(force=True) or {}
        try:
            ok = db.update_media_item_for_file(
                file_id=file_id,
                media_kind=data.get("media_kind"),
                title=data.get("title"),
                collection_id=_optional_int(data.get("collection_id")),
                collection_title=data.get("collection_title"),
                collection_type=data.get("collection_type", "unknown"),
                season_number=_optional_int(data.get("season_number")),
                episode_number=_optional_int(data.get("episode_number")),
                year=_optional_int(data.get("year")),
                language=data.get("language"),
                display_order=_optional_int(data.get("display_order")),
            )
        except (TypeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

        if not ok:
            return jsonify({"error": "Media item not found for file", "file_id": file_id}), 404

        return jsonify({"status": "saved", **db.get_media_for_file(file_id)}), 200

    @bp.route("/files/<file_id>/subtitles", methods=["GET"])
    def list_file_subtitles(file_id):
        try:
            tracks = db.list_subtitle_tracks(file_id)
            return jsonify({"count": len(tracks), "subtitles": tracks}), 200
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @bp.route("/files/<file_id>/subtitles", methods=["POST"])
    def upload_file_subtitle(file_id):
        if "file" not in request.files:
            return jsonify({"error": "Missing subtitle file"}), 400

        content_hash = db.get_file_content_hash(file_id)
        if not content_hash:
            return jsonify({"error": "Video file not found", "file_id": file_id}), 404

        upload = request.files["file"]
        original_name = Path(upload.filename or "subtitle").name
        subtitle_format = _subtitle_format(original_name)
        if subtitle_format == "unknown":
            return jsonify({"error": "Unsupported subtitle format", "allowed": sorted(SUPPORTED_SUBTITLE_FORMATS)}), 400

        safe_name = secure_filename(original_name) or f"subtitle.{subtitle_format}"
        target_dir = SUBTITLES_ROOT / str(file_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        stored_name = f"{int(time.time() * 1000)}-{safe_name}"
        storage_path = target_dir / stored_name
        upload.save(storage_path)

        vtt_path = None
        if subtitle_format == "srt":
            vtt_path = storage_path.with_suffix(".vtt")
            try:
                convert_srt_to_vtt(storage_path, vtt_path)
            except Exception as exc:
                vtt_path = None
                # Keep the original subtitle even when browser-ready conversion fails.
                label = request.form.get("label") or request.form.get("language") or "Unknown"
                subtitle_id = db.create_subtitle_track(
                    file_id=file_id,
                    content_hash=content_hash,
                    subtitle_file_name=original_name,
                    subtitle_format=subtitle_format,
                    language=request.form.get("language", "unknown"),
                    label=label,
                    is_default=_bool_form(request.form.get("is_default")),
                    storage_path=str(storage_path),
                    vtt_path=None,
                )
                track = db.get_subtitle_track(subtitle_id)
                return jsonify({
                    "status": "stored",
                    "warning": f"SRT to VTT conversion failed: {exc}",
                    "subtitle": track,
                }), 201

        label = request.form.get("label") or request.form.get("language") or "Unknown"
        subtitle_id = db.create_subtitle_track(
            file_id=file_id,
            content_hash=content_hash,
            subtitle_file_name=original_name,
            subtitle_format=subtitle_format,
            language=request.form.get("language", "unknown"),
            label=label,
            is_default=_bool_form(request.form.get("is_default")),
            storage_path=str(storage_path),
            vtt_path=str(vtt_path) if vtt_path else None,
        )
        return jsonify({"status": "created", "subtitle": db.get_subtitle_track(subtitle_id)}), 201

    @bp.route("/subtitles/<int:subtitle_id>", methods=["DELETE"])
    def delete_subtitle(subtitle_id):
        ok = db.soft_delete_subtitle_track(subtitle_id)
        if not ok:
            return jsonify({"error": "Subtitle not found or already deleted", "subtitle_id": subtitle_id}), 404
        return jsonify({"status": "deleted", "subtitle_id": subtitle_id}), 200

    @bp.route("/subtitles/<int:subtitle_id>/default", methods=["PATCH"])
    def set_default_subtitle(subtitle_id):
        ok = db.set_default_subtitle_track(subtitle_id)
        if not ok:
            return jsonify({"error": "Active subtitle not found", "subtitle_id": subtitle_id}), 404
        return jsonify({"status": "default_set", "subtitle": db.get_subtitle_track(subtitle_id)}), 200

    @bp.route("/subtitles/<int:subtitle_id>/file", methods=["GET"])
    def get_subtitle_file(subtitle_id):
        track = db.get_subtitle_track(subtitle_id)
        if not track or track.get("status") != "active":
            return jsonify({"error": "Subtitle not found"}), 404

        if track.get("subtitle_format") == "ass":
            return jsonify({"error": "ASS subtitles are stored only and unsupported by the browser player"}), 415

        path = track.get("vtt_path") or track.get("storage_path")
        if not path:
            return jsonify({"error": "No playable subtitle file available"}), 404

        subtitle_path = Path(path).resolve()
        try:
            subtitle_path.relative_to(SUBTITLES_ROOT.resolve())
        except Exception:
            return jsonify({"error": "Invalid subtitle path"}), 403
        if not subtitle_path.exists() or not subtitle_path.is_file():
            return jsonify({"error": "Subtitle file missing"}), 404

        mimetype = "text/vtt" if subtitle_path.suffix.lower() == ".vtt" else "text/plain"
        return send_file(subtitle_path, mimetype=mimetype, conditional=True)

    return bp
