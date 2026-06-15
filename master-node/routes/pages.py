from flask import Blueprint, jsonify, render_template


def create_pages_blueprint():
    bp = Blueprint("pages", __name__)

    @bp.route("/")
    def index():
        return jsonify({
            "service": "FSYS Master Registry",
            "version": "2.0.0-hybrid-registry",
            "status": "running",
        })

    @bp.route("/dashboard")
    def dashboard():
        return render_template("dashboard.html")

    return bp
