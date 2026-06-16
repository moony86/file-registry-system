from flask import Blueprint, jsonify, request


def _optional_int(value):
    if value in (None, ""):
        return None
    return int(value)


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

    return bp
