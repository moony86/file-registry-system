import logging
import sys
from pathlib import Path

from flask import Flask
from flask_cors import CORS

from services.setup_wizard import maybe_run_setup_wizard

maybe_run_setup_wizard()
sys.argv = [arg for arg in sys.argv if arg not in {"--setup", "--reset-config"}]

import config
from routes.debug import create_debug_blueprint
from routes.files import create_files_blueprint
from routes.local import create_local_blueprint
from routes.pages import create_pages_blueprint
from routes.status import create_status_blueprint
from services.heartbeat import start_heartbeat
from services.master_client import MasterClient
from services.space_cache import SpaceCache
from services.registration import start_registration_loop


def configure_logging():
    logs_dir = Path("logs").resolve()
    logs_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(logs_dir / "node.log", encoding="utf-8"),
        ],
    )


configure_logging()


def create_app():
    config.SHARED_SPACE_DIR.mkdir(parents=True, exist_ok=True)
    config.THUMBNAILS_DIR.mkdir(parents=True, exist_ok=True)
    Path("logs").resolve().mkdir(parents=True, exist_ok=True)

    app = Flask(__name__)
    CORS(app, origins=config.CORS_ORIGINS)

    space_cache = SpaceCache(config.SHARED_SPACE_DIR)
    runtime_state = {}
    master_client = MasterClient(
        master_urls=config.MASTER_URLS,
        node_token=config.NODE_TOKEN,
        node_id=config.NODE_ID,
        node_host=config.NODE_HOST,
        node_port=config.NODE_PORT,
    )

    app.extensions["space_cache"] = space_cache
    app.extensions["master_client"] = master_client
    app.extensions["runtime_state"] = runtime_state

    app.register_blueprint(create_pages_blueprint(config))
    app.register_blueprint(create_files_blueprint(config, space_cache, master_client))
    app.register_blueprint(create_local_blueprint(config))
    app.register_blueprint(create_status_blueprint(config, space_cache, master_client, runtime_state))
    app.register_blueprint(create_debug_blueprint(config, space_cache))

    return app, space_cache, master_client


app, space_cache, master_client = create_app()


if __name__ == "__main__":
    print(f"FSYS Storage Node v2 starting: {config.NODE_ID} on {config.NODE_HOST}:{config.NODE_PORT}")

    space_cache.resync_from_disk()

    registration_thread = start_registration_loop(
        master_client=master_client,
        space_cache=space_cache,
        shared_space_enabled=config.SHARED_SPACE_ENABLED,
        shared_space_limit_bytes=config.SHARED_SPACE_LIMIT_BYTES,
    )
    app.extensions["runtime_state"]["registration_thread"] = registration_thread

    start_heartbeat(master_client, space_cache)

    app.run(host="0.0.0.0", port=config.NODE_PORT, debug=False)
