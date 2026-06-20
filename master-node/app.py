import os
import logging
from flask import Flask
from dotenv import load_dotenv

from database import Database
from routes.files import create_files_blueprint
from routes.media import create_media_blueprint
from routes.nodes import create_nodes_blueprint
from routes.pages import create_pages_blueprint
from routes.status import create_status_blueprint
from services.cleanup import start_dead_node_cleanup
from services.storage_operations import start_storage_operations_worker

load_dotenv()


def create_app() -> Flask:
    app = Flask(__name__)
    db = Database()

    app.register_blueprint(create_pages_blueprint())
    app.register_blueprint(create_nodes_blueprint(db))
    app.register_blueprint(create_files_blueprint(db))
    app.register_blueprint(create_media_blueprint(db))
    app.register_blueprint(create_status_blueprint(db))

    start_dead_node_cleanup(db)
    try:
        start_storage_operations_worker(db)
    except Exception:
        logging.getLogger(__name__).exception("Failed to start storage operations worker")
    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.getenv("MASTER_PORT", "5000"))

    print("\n" + "=" * 50)
    print(f" * Dashboard Link: http://127.0.0.1:{port}/dashboard")
    print("=" * 50 + "\n")

    print(f"FSYS Master Registry v2 starting on 0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=os.getenv("FLASK_DEBUG", "0") == "1")
