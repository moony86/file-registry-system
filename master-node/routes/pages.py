from flask import Blueprint, jsonify, render_template


def create_pages_blueprint():
    bp = Blueprint("pages", __name__)

    @bp.route("/")
    def index():
        return render_template("viewer.html")

    @bp.route("/dashboard")
    def dashboard():
        return render_template("dashboard.html")

    @bp.route("/watch/<file_id>")
    def watch(file_id):
        return render_template("watch.html", file_id=file_id)

    return bp
