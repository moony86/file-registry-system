import sys
from flask import Flask
from flask_cors import CORS

import config
from routes.debug import create_debug_blueprint
from routes.files import create_files_blueprint
from routes.pages import create_pages_blueprint
from routes.status import create_status_blueprint
from services.heartbeat import start_heartbeat
from services.master_client import MasterClient
from services.space_cache import SpaceCache


def create_app():
    config.SHARED_SPACE_DIR.mkdir(parents=True, exist_ok=True)

    app = Flask(__name__)
    CORS(app, origins=config.CORS_ORIGINS)

    space_cache = SpaceCache(config.SHARED_SPACE_DIR)
    master_client = MasterClient(
        master_url=config.MASTER_URL,
        node_token=config.NODE_TOKEN,
        node_id=config.NODE_ID,
        node_host=config.NODE_HOST,
        node_port=config.NODE_PORT,
    )

    app.extensions["space_cache"] = space_cache
    app.extensions["master_client"] = master_client

    app.register_blueprint(create_pages_blueprint(config))
    app.register_blueprint(create_files_blueprint(config, space_cache, master_client))
    app.register_blueprint(create_status_blueprint(config, space_cache))
    app.register_blueprint(create_debug_blueprint(config, space_cache))

    return app, space_cache, master_client


app, space_cache, master_client = create_app()


if __name__ == "__main__":
    print(f"FSYS Storage Node v2 starting: {config.NODE_ID} on {config.NODE_HOST}:{config.NODE_PORT}")

    space_cache.resync_from_disk()

    if master_client.register_node(
        shared_space_enabled=config.SHARED_SPACE_ENABLED,
        shared_space_limit_bytes=config.SHARED_SPACE_LIMIT_BYTES,
        shared_space_used_bytes=space_cache.used(),
    ):
        start_heartbeat(master_client, space_cache)
        app.run(host="0.0.0.0", port=config.NODE_PORT, debug=False)
    else:
        print("Failed to register with master. Exiting.")
        sys.exit(1)
