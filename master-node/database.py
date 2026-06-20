# master-node/database.py
"""
Thread-safe PostgreSQL data access layer for FSYS Master Registry.

Why this version exists:
- pg8000.native.Connection is not safe to share across concurrent Flask requests.
- A single global connection can corrupt unnamed prepared statement state under concurrency,
  causing errors such as: "unnamed prepared statement does not exist".
- This file uses a short-lived PostgreSQL connection per database operation and wraps
  multi-step writes in explicit transactions.

This is intentionally simple: no connection pool yet. For the current development stage,
it is a real fix for concurrency correctness without adding operational complexity.
Later, if request volume increases, replace _new_connection() with a small pool.
"""

import os
import uuid
import socket
import re
from contextlib import contextmanager
from dotenv import load_dotenv
import pg8000.native

load_dotenv()

NODE_TIMEOUT_SECONDS = int(os.getenv("NODE_TIMEOUT_SECONDS", "30"))

MEDIA_KIND_VALUES = {
    "movie",
    "series_episode",
    "anime_episode",
    "youtube_video",
    "short",
    "course",
    "clip",
    "other_video",
    "unknown",
}

REVIEW_STATUS_VALUES = {"pending", "approved", "rejected", "needs_edit"}

COLLECTION_TYPE_VALUES = {
    "anime",
    "series",
    "movie_collection",
    "youtube_channel",
    "course",
    "clips",
    "unknown",
}


def suggest_media_draft_from_filename(file_name):
    stem = os.path.splitext(os.path.basename(file_name or ""))[0]
    spaced = re.sub(r"[._\-]+", " ", stem)
    spaced = re.sub(r"\s+", " ", spaced).strip()

    season = None
    episode = None
    suggested_kind = "unknown"

    episode_match = re.search(r"\bS(\d{1,2})E(\d{1,3})\b", spaced, flags=re.IGNORECASE)
    if episode_match:
        season = int(episode_match.group(1))
        episode = int(episode_match.group(2))
        suggested_kind = "series_episode"

    year = None
    year_match = re.search(r"\b(19\d{2}|20\d{2})\b", spaced)
    if year_match:
        year = int(year_match.group(1))
        if suggested_kind == "unknown":
            suggested_kind = "movie"

    ep_match = re.search(r"\bEP\s*(\d{1,3})\b", spaced, flags=re.IGNORECASE)
    if ep_match and episode is None:
        episode = int(ep_match.group(1))

    title = spaced
    title = re.sub(r"\bS\d{1,2}E\d{1,3}\b", " ", title, flags=re.IGNORECASE)
    title = re.sub(r"\b(19\d{2}|20\d{2})\b", " ", title)
    title = re.sub(r"\b(720p|1080p|2160p|4k|8k|bluray|web[- ]?dl|webrip|hdrip|x264|x265|h264|h265)\b", " ", title, flags=re.IGNORECASE)
    title = re.sub(r"\s+", " ", title).strip()

    return {
        "suggested_media_kind": suggested_kind,
        "suggested_title": title or spaced or None,
        "year": year,
        "season": season,
        "episode": episode,
    }


class Database:
    def __init__(self):
        self.db_config = {
            "host": os.getenv("DB_HOST", "localhost"),
            "port": int(os.getenv("DB_PORT", "5432")),
            "database": os.getenv("DB_NAME", "file_registry"),
            "user": os.getenv("DB_USER", "registry_admin"),
            "password": os.getenv("DB_PASSWORD", "admin123"),
        }
        self.init_tables()

    def _new_connection(self):
        return pg8000.native.Connection(**self.db_config)

    @contextmanager
    def _connection(self):
        conn = self._new_connection()
        try:
            yield conn
        finally:
            try:
                conn.close()
            except Exception:
                pass

    @contextmanager
    def _transaction(self):
        conn = self._new_connection()
        try:
            conn.run("BEGIN")
            yield conn
            conn.run("COMMIT")
        except Exception:
            try:
                conn.run("ROLLBACK")
            except Exception:
                pass
            raise
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _fetch_all(self, sql, **params):
        with self._connection() as conn:
            rows = conn.run(sql, **params)
            return rows or []

    def _execute(self, sql, **params):
        with self._transaction() as conn:
            conn.run(sql, **params)

    def init_tables(self):
        with self._transaction() as conn:
            conn.run("""
                CREATE TABLE IF NOT EXISTS storage_nodes (
                    node_id VARCHAR(100) PRIMARY KEY,
                    host VARCHAR(255) NOT NULL,
                    port INTEGER NOT NULL,
                    status VARCHAR(20) DEFAULT 'OFFLINE',
                    shared_space_enabled BOOLEAN DEFAULT FALSE,
                    shared_space_limit_bytes BIGINT DEFAULT 0,
                    shared_space_used_bytes BIGINT DEFAULT 0,
                    last_heartbeat TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            for stmt in [
                "ALTER TABLE storage_nodes ADD COLUMN IF NOT EXISTS shared_space_enabled BOOLEAN DEFAULT FALSE",
                "ALTER TABLE storage_nodes ADD COLUMN IF NOT EXISTS shared_space_limit_bytes BIGINT DEFAULT 0",
                "ALTER TABLE storage_nodes ADD COLUMN IF NOT EXISTS shared_space_used_bytes BIGINT DEFAULT 0",
            ]:
                conn.run(stmt)

            conn.run("""
                CREATE TABLE IF NOT EXISTS contents (
                    content_hash VARCHAR(64) PRIMARY KEY,
                    size_bytes BIGINT NOT NULL,
                    mime_type VARCHAR(100) DEFAULT 'application/octet-stream',
                    risk_status VARCHAR(30) DEFAULT 'UNKNOWN',
                    popularity_score INTEGER DEFAULT 0,
                    is_hot INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_requested_at TIMESTAMP
                )
            """)

            conn.run("ALTER TABLE contents ADD COLUMN IF NOT EXISTS is_hot INTEGER DEFAULT 0")
            conn.run("ALTER TABLE contents ADD COLUMN IF NOT EXISTS media_type VARCHAR(20) DEFAULT 'other'")

            conn.run("""
                CREATE TABLE IF NOT EXISTS file_aliases (
                    file_id UUID PRIMARY KEY,
                    content_hash VARCHAR(64) REFERENCES contents(content_hash) ON DELETE CASCADE,
                    file_name VARCHAR(500) NOT NULL,
                    owner VARCHAR(100) NOT NULL DEFAULT 'anonymous',
                    original_path VARCHAR(1000),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Soft-delete lifecycle for file aliases.
            # ACTIVE: visible in library.
            # DELETED: hidden from normal lists; managed copies may be moved to node trash.
            # PURGED: final state for future permanent deletion workflows.
            conn.run("ALTER TABLE file_aliases ADD COLUMN IF NOT EXISTS file_status VARCHAR(20) DEFAULT 'ACTIVE'")
            conn.run("ALTER TABLE file_aliases ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP")
            conn.run("ALTER TABLE file_aliases ADD COLUMN IF NOT EXISTS deleted_by VARCHAR(100)")

            conn.run("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_alias
                ON file_aliases(content_hash, file_name, owner)
            """)

            conn.run("""
                CREATE TABLE IF NOT EXISTS content_locations (
                    location_id SERIAL PRIMARY KEY,
                    content_hash VARCHAR(64) REFERENCES contents(content_hash) ON DELETE CASCADE,
                    node_id VARCHAR(100) REFERENCES storage_nodes(node_id) ON DELETE CASCADE,
                    physical_path VARCHAR(1000) NOT NULL,
                    location_type VARCHAR(30) DEFAULT 'LOCAL',
                    is_primary BOOLEAN DEFAULT FALSE,
                    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(content_hash, node_id, physical_path)
                )
            """)

            conn.run("""
                CREATE TABLE IF NOT EXISTS access_logs (
                    log_id SERIAL PRIMARY KEY,
                    file_id UUID,
                    content_hash VARCHAR(64),
                    client_ip VARCHAR(50),
                    access_type VARCHAR(30),
                    accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            conn.run("""
                CREATE TABLE IF NOT EXISTS media_drafts (
                    draft_id SERIAL PRIMARY KEY,
                    file_id UUID REFERENCES file_aliases(file_id) ON DELETE CASCADE,
                    content_hash VARCHAR(64),
                    review_status VARCHAR(30) DEFAULT 'pending',
                    suggested_media_kind VARCHAR(50),
                    user_media_kind VARCHAR(50),
                    final_media_kind VARCHAR(50),
                    suggested_title VARCHAR(500),
                    user_title VARCHAR(500),
                    final_title VARCHAR(500),
                    year INTEGER,
                    season INTEGER,
                    episode INTEGER,
                    language VARCHAR(50),
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    reviewed_at TIMESTAMP,
                    reviewed_by VARCHAR(100),
                    UNIQUE(file_id)
                )
            """)

            conn.run("""
                CREATE TABLE IF NOT EXISTS media_items (
                    media_id SERIAL PRIMARY KEY,
                    file_id UUID REFERENCES file_aliases(file_id) ON DELETE CASCADE,
                    content_hash VARCHAR(64),
                    media_kind VARCHAR(50),
                    title VARCHAR(500),
                    year INTEGER,
                    season INTEGER,
                    episode INTEGER,
                    language VARCHAR(50),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(file_id)
                )
            """)

            conn.run("""
                CREATE TABLE IF NOT EXISTS media_collections (
                    collection_id SERIAL PRIMARY KEY,
                    title VARCHAR(500) NOT NULL,
                    collection_type VARCHAR(50) DEFAULT 'unknown',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(title, collection_type)
                )
            """)

            conn.run("""
                CREATE TABLE IF NOT EXISTS media_technical_metadata (
                    content_hash VARCHAR(64) PRIMARY KEY REFERENCES contents(content_hash) ON DELETE CASCADE,
                    duration_seconds DOUBLE PRECISION,
                    width INTEGER,
                    height INTEGER,
                    video_codec VARCHAR(100),
                    audio_codec VARCHAR(100),
                    audio_channels INTEGER,
                    bitrate BIGINT,
                    fps DOUBLE PRECISION,
                    format_name VARCHAR(200),
                    probe_status VARCHAR(30) DEFAULT 'unknown',
                    probe_error TEXT,
                    probed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            conn.run("""
                CREATE TABLE IF NOT EXISTS media_thumbnails (
                    content_hash VARCHAR(64) PRIMARY KEY REFERENCES contents(content_hash) ON DELETE CASCADE,
                    thumbnail_path VARCHAR(1000),
                    thumbnail_status VARCHAR(30) DEFAULT 'skipped',
                    width INTEGER,
                    height INTEGER,
                    generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    error_message TEXT
                )
            """)

            conn.run("""
                CREATE TABLE IF NOT EXISTS subtitle_tracks (
                    subtitle_id SERIAL PRIMARY KEY,
                    file_id UUID NOT NULL REFERENCES file_aliases(file_id) ON DELETE CASCADE,
                    content_hash VARCHAR(64),
                    subtitle_file_name VARCHAR(500),
                    subtitle_format VARCHAR(20) DEFAULT 'unknown',
                    language VARCHAR(50) DEFAULT 'unknown',
                    label VARCHAR(100),
                    is_default BOOLEAN DEFAULT FALSE,
                    storage_path TEXT NOT NULL,
                    vtt_path TEXT,
                    status VARCHAR(30) DEFAULT 'active',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    deleted_at TIMESTAMP
                )
            """)

            conn.run("""
                CREATE TABLE IF NOT EXISTS storage_operations (
                    operation_id UUID PRIMARY KEY,
                    file_id UUID NOT NULL REFERENCES file_aliases(file_id) ON DELETE CASCADE,
                    content_hash VARCHAR(64) NOT NULL,
                    operation_type VARCHAR(50) NOT NULL,
                    source_location_id INTEGER REFERENCES content_locations(location_id) ON DELETE SET NULL,
                    target_node_id VARCHAR(200) REFERENCES storage_nodes(node_id) ON DELETE SET NULL,
                    status VARCHAR(30) NOT NULL DEFAULT 'PENDING',
                    progress_percent INTEGER DEFAULT 0,
                    error_message TEXT,
                    result_json TEXT,
                    requested_by VARCHAR(200),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    started_at TIMESTAMP,
                    completed_at TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            conn.run("ALTER TABLE media_drafts ADD COLUMN IF NOT EXISTS collection_id INTEGER REFERENCES media_collections(collection_id)")
            conn.run("ALTER TABLE media_drafts ADD COLUMN IF NOT EXISTS collection_title VARCHAR(500)")
            conn.run("ALTER TABLE media_drafts ADD COLUMN IF NOT EXISTS collection_type VARCHAR(50) DEFAULT 'unknown'")
            conn.run("ALTER TABLE media_drafts ADD COLUMN IF NOT EXISTS season_number INTEGER")
            conn.run("ALTER TABLE media_drafts ADD COLUMN IF NOT EXISTS episode_number INTEGER")

            conn.run("ALTER TABLE media_items ADD COLUMN IF NOT EXISTS collection_id INTEGER REFERENCES media_collections(collection_id)")
            conn.run("ALTER TABLE media_items ADD COLUMN IF NOT EXISTS season_number INTEGER")
            conn.run("ALTER TABLE media_items ADD COLUMN IF NOT EXISTS episode_number INTEGER")
            conn.run("ALTER TABLE media_items ADD COLUMN IF NOT EXISTS display_order INTEGER")

            # Lightweight indexes for common dashboard and lookup paths.
            conn.run("CREATE INDEX IF NOT EXISTS idx_storage_nodes_status_heartbeat ON storage_nodes(status, last_heartbeat)")
            conn.run("CREATE INDEX IF NOT EXISTS idx_file_aliases_content_hash ON file_aliases(content_hash)")
            conn.run("CREATE INDEX IF NOT EXISTS idx_file_aliases_status_created ON file_aliases(file_status, created_at)")
            conn.run("CREATE INDEX IF NOT EXISTS idx_content_locations_content_hash ON content_locations(content_hash)")
            conn.run("CREATE INDEX IF NOT EXISTS idx_content_locations_node_id ON content_locations(node_id)")
            conn.run("CREATE INDEX IF NOT EXISTS idx_contents_hot_created ON contents(is_hot, created_at)")
            conn.run("CREATE INDEX IF NOT EXISTS idx_media_drafts_status_created ON media_drafts(review_status, created_at)")
            conn.run("CREATE INDEX IF NOT EXISTS idx_media_items_kind_title ON media_items(media_kind, title)")
            conn.run("CREATE INDEX IF NOT EXISTS idx_media_items_collection_order ON media_items(collection_id, season_number, episode_number, display_order)")
            conn.run("CREATE INDEX IF NOT EXISTS idx_media_collections_type_title ON media_collections(collection_type, title)")
            conn.run("CREATE INDEX IF NOT EXISTS idx_media_technical_metadata_status ON media_technical_metadata(probe_status)")
            conn.run("CREATE INDEX IF NOT EXISTS idx_media_thumbnails_status ON media_thumbnails(thumbnail_status)")
            conn.run("CREATE INDEX IF NOT EXISTS idx_subtitle_tracks_file_status ON subtitle_tracks(file_id, status)")
            conn.run("CREATE INDEX IF NOT EXISTS idx_storage_operations_file_status ON storage_operations(file_id, operation_type, status)")
            conn.run("CREATE INDEX IF NOT EXISTS idx_storage_operations_pending ON storage_operations(status, created_at)")

    # ========== Node Management ==========
    def register_node(self, node_id, host, port, shared_space_enabled=False,
                      shared_space_limit_bytes=0, shared_space_used_bytes=0):
        self._execute("""
            INSERT INTO storage_nodes (
                node_id, host, port, status, shared_space_enabled,
                shared_space_limit_bytes, shared_space_used_bytes, last_heartbeat
            )
            VALUES (
                :node_id, :host, :port, 'ONLINE', :shared_space_enabled,
                :shared_space_limit_bytes, :shared_space_used_bytes, CURRENT_TIMESTAMP
            )
            ON CONFLICT (node_id)
            DO UPDATE SET
                host = EXCLUDED.host,
                port = EXCLUDED.port,
                status = 'ONLINE',
                shared_space_enabled = EXCLUDED.shared_space_enabled,
                shared_space_limit_bytes = EXCLUDED.shared_space_limit_bytes,
                shared_space_used_bytes = EXCLUDED.shared_space_used_bytes,
                last_heartbeat = CURRENT_TIMESTAMP
        """, node_id=node_id, host=host, port=port,
             shared_space_enabled=shared_space_enabled,
             shared_space_limit_bytes=shared_space_limit_bytes,
             shared_space_used_bytes=shared_space_used_bytes)

    def update_heartbeat(self, node_id, shared_space_used_bytes=None):
        if not node_id:
            return False

        with self._transaction() as conn:
            rows = conn.run(
                "SELECT node_id FROM storage_nodes WHERE node_id = :node_id",
                node_id=node_id
            ) or []
            if not rows:
                return False

            if shared_space_used_bytes is None:
                conn.run("""
                    UPDATE storage_nodes
                    SET last_heartbeat = CURRENT_TIMESTAMP, status = 'ONLINE'
                    WHERE node_id = :node_id
                """, node_id=node_id)
            else:
                conn.run("""
                    UPDATE storage_nodes
                    SET last_heartbeat = CURRENT_TIMESTAMP,
                        status = 'ONLINE',
                        shared_space_used_bytes = :shared_space_used_bytes
                    WHERE node_id = :node_id
                """, node_id=node_id, shared_space_used_bytes=shared_space_used_bytes)

        return True

    def mark_dead_nodes(self, timeout_seconds=NODE_TIMEOUT_SECONDS):
        self._execute("""
            UPDATE storage_nodes
            SET status = 'OFFLINE'
            WHERE status = 'ONLINE'
            AND last_heartbeat < NOW() - (:timeout_seconds * INTERVAL '1 second')
        """, timeout_seconds=timeout_seconds)

    def get_online_nodes(self):
        rows = self._fetch_all("""
            SELECT node_id, host, port, status, shared_space_enabled,
                   shared_space_limit_bytes, shared_space_used_bytes,
                   last_heartbeat, registered_at
            FROM storage_nodes
            WHERE status = 'ONLINE'
            AND last_heartbeat > NOW() - (:timeout_seconds * INTERVAL '1 second')
            ORDER BY last_heartbeat DESC
        """, timeout_seconds=NODE_TIMEOUT_SECONDS)
        columns = [
            'node_id', 'host', 'port', 'status', 'shared_space_enabled',
            'shared_space_limit_bytes', 'shared_space_used_bytes',
            'last_heartbeat', 'registered_at'
        ]
        return [dict(zip(columns, row)) for row in rows]

    # ========== Content / Alias / Location Operations ==========
    def register_content_alias(self, content_hash, file_name, owner, size_bytes,
                            mime_type, node_id, physical_path,
                            location_type='LOCAL',  media_type='other'):
        file_id = uuid.uuid4()

        with self._transaction() as conn:
            conn.run("""
                INSERT INTO contents (content_hash, size_bytes, mime_type, media_type)
                VALUES (:content_hash, :size_bytes, :mime_type, :media_type)
                ON CONFLICT (content_hash)
                DO UPDATE SET
                    size_bytes = EXCLUDED.size_bytes,
                    mime_type = EXCLUDED.mime_type,
                    media_type = EXCLUDED.media_type
                """, content_hash=content_hash, size_bytes=size_bytes, mime_type=mime_type, media_type=media_type)

            existing = conn.run("""
                SELECT file_id
                FROM file_aliases
                WHERE content_hash = :content_hash
                AND file_name = :file_name
                AND owner = :owner
                LIMIT 1
                """, content_hash=content_hash, file_name=file_name, owner=owner) or []

            if existing:
                file_id = existing[0][0]
            else:
                conn.run("""
                    INSERT INTO file_aliases (
                        file_id,
                        content_hash,
                        file_name,
                        owner,
                        original_path
                    )
                    VALUES (
                        :file_id,
                        :content_hash,
                        :file_name,
                        :owner,
                        :original_path
                    )
                    ON CONFLICT (content_hash, file_name, owner)
                    DO NOTHING
                """, file_id=file_id, content_hash=content_hash, file_name=file_name,
                     owner=owner, original_path=physical_path)

                # Race-safe final lookup: if another request inserted the alias first,
                # return the real existing file_id instead of the generated one.
                final_rows = conn.run("""
                    SELECT file_id
                    FROM file_aliases
                    WHERE content_hash = :content_hash
                      AND file_name = :file_name
                      AND owner = :owner
                    LIMIT 1
                """, content_hash=content_hash, file_name=file_name, owner=owner) or []
                if final_rows:
                    file_id = final_rows[0][0]

            self._upsert_content_location_in_tx(
                conn, content_hash, node_id, physical_path, location_type, is_primary=False
            )

            if media_type == "video":
                draft = suggest_media_draft_from_filename(file_name)
                self._create_media_draft_in_tx(
                    conn,
                    file_id=file_id,
                    content_hash=content_hash,
                    suggested_media_kind=draft["suggested_media_kind"],
                    suggested_title=draft["suggested_title"],
                    year=draft["year"],
                    season=draft["season"],
                    episode=draft["episode"],
                )

        return file_id

    def _create_media_draft_in_tx(self, conn, file_id, content_hash, suggested_media_kind,
                                  suggested_title=None, year=None, season=None, episode=None):
        conn.run("""
            INSERT INTO media_drafts (
                file_id, content_hash, review_status, suggested_media_kind,
                suggested_title, year, season, episode
            )
            VALUES (
                :file_id, :content_hash, 'pending', :suggested_media_kind,
                :suggested_title, :year, :season, :episode
            )
            ON CONFLICT (file_id)
            DO NOTHING
        """, file_id=file_id, content_hash=content_hash,
             suggested_media_kind=suggested_media_kind,
             suggested_title=suggested_title,
             year=year, season=season, episode=episode)

    def _upsert_content_location_in_tx(self, conn, content_hash, node_id, physical_path,
                                       location_type='LOCAL', is_primary=False):
        conn.run("""
            INSERT INTO content_locations (
                content_hash, node_id, physical_path, location_type, is_primary, last_seen
            )
            VALUES (
                :content_hash, :node_id, :physical_path, :location_type, :is_primary, CURRENT_TIMESTAMP
            )
            ON CONFLICT (content_hash, node_id, physical_path)
            DO UPDATE SET
                location_type = EXCLUDED.location_type,
                is_primary = EXCLUDED.is_primary,
                last_seen = CURRENT_TIMESTAMP
        """, content_hash=content_hash, node_id=node_id,
             physical_path=physical_path, location_type=location_type,
             is_primary=is_primary)

    def upsert_content_location(self, content_hash, node_id, physical_path,
                                location_type='LOCAL', is_primary=False):
        with self._transaction() as conn:
            self._upsert_content_location_in_tx(
                conn, content_hash, node_id, physical_path, location_type, is_primary
            )

    def _storage_operation_row_to_dict(self, row):
        if not row:
            return None
        columns = [
            'operation_id', 'file_id', 'content_hash', 'operation_type',
            'source_location_id', 'target_node_id', 'status', 'progress_percent',
            'error_message', 'result_json', 'requested_by', 'created_at',
            'started_at', 'completed_at', 'updated_at',
        ]
        result = dict(zip(columns, row))
        result["operation_id"] = str(result["operation_id"])
        result["file_id"] = str(result["file_id"])
        return result

    def _storage_operation_rows_to_dicts(self, rows):
        return [self._storage_operation_row_to_dict(row) for row in rows]

    def create_promote_to_cache_operation(self, file_id, requested_by="dashboard-dev"):
        operation_type = "promote_local_to_cached"
        with self._transaction() as conn:
            file_rows = conn.run("""
                SELECT fa.file_id, fa.content_hash
                FROM file_aliases fa
                WHERE fa.file_id = :file_id
                  AND COALESCE(fa.file_status, 'ACTIVE') = 'ACTIVE'
                LIMIT 1
            """, file_id=file_id) or []
            if not file_rows:
                return {"created": False, "status": "not_found", "message": "File not found or not active"}

            _, content_hash = file_rows[0]

            cached_rows = conn.run("""
                SELECT location_id
                FROM content_locations
                WHERE content_hash = :content_hash
                  AND location_type = 'CACHED'
                LIMIT 1
            """, content_hash=content_hash) or []
            if cached_rows:
                return {"created": False, "status": "already_cached", "message": "File already has a CACHED location"}

            active_rows = conn.run("""
                SELECT operation_id, status
                FROM storage_operations
                WHERE file_id = :file_id
                  AND operation_type = :operation_type
                  AND status IN ('PENDING', 'RUNNING')
                ORDER BY created_at DESC
                LIMIT 1
            """, file_id=file_id, operation_type=operation_type) or []
            if active_rows:
                return {
                    "created": False,
                    "status": "already_queued",
                    "operation_id": str(active_rows[0][0]),
                    "operation_status": active_rows[0][1],
                    "message": "A promote operation is already pending or running for this file",
                }

            local_rows = conn.run("""
                SELECT
                    cl.location_id, cl.node_id, sn.host, sn.port, sn.status
                FROM content_locations cl
                JOIN storage_nodes sn ON cl.node_id = sn.node_id
                WHERE cl.content_hash = :content_hash
                  AND cl.location_type = 'LOCAL'
                  AND sn.status = 'ONLINE'
                  AND sn.last_heartbeat > NOW() - (:timeout_seconds * INTERVAL '1 second')
                ORDER BY cl.last_seen DESC
                LIMIT 1
            """, content_hash=content_hash, timeout_seconds=NODE_TIMEOUT_SECONDS) or []
            if not local_rows:
                return {"created": False, "status": "no_local_online", "message": "No online LOCAL location found"}

            source_location_id, target_node_id, _, _, _ = local_rows[0]
            operation_id = uuid.uuid4()
            rows = conn.run("""
                INSERT INTO storage_operations (
                    operation_id, file_id, content_hash, operation_type,
                    source_location_id, target_node_id, status, progress_percent,
                    requested_by, updated_at
                )
                VALUES (
                    :operation_id, :file_id, :content_hash, :operation_type,
                    :source_location_id, :target_node_id, 'PENDING', 0,
                    :requested_by, CURRENT_TIMESTAMP
                )
                RETURNING
                    operation_id, file_id, content_hash, operation_type,
                    source_location_id, target_node_id, status, progress_percent,
                    error_message, result_json, requested_by, created_at,
                    started_at, completed_at, updated_at
            """, operation_id=operation_id, file_id=file_id, content_hash=content_hash,
                 operation_type=operation_type, source_location_id=source_location_id,
                 target_node_id=target_node_id, requested_by=requested_by) or []

        operation = self._storage_operation_row_to_dict(rows[0]) if rows else None
        return {"created": True, "status": "queued", "operation": operation}

    def get_storage_operation(self, operation_id):
        rows = self._fetch_all("""
            SELECT
                operation_id, file_id, content_hash, operation_type,
                source_location_id, target_node_id, status, progress_percent,
                error_message, result_json, requested_by, created_at,
                started_at, completed_at, updated_at
            FROM storage_operations
            WHERE operation_id = :operation_id
            LIMIT 1
        """, operation_id=operation_id)
        return self._storage_operation_row_to_dict(rows[0]) if rows else None

    def list_storage_operations(self, file_id=None, limit=50):
        if file_id:
            rows = self._fetch_all("""
                SELECT
                    operation_id, file_id, content_hash, operation_type,
                    source_location_id, target_node_id, status, progress_percent,
                    error_message, result_json, requested_by, created_at,
                    started_at, completed_at, updated_at
                FROM storage_operations
                WHERE file_id = :file_id
                ORDER BY created_at DESC
                LIMIT :limit
            """, file_id=file_id, limit=limit)
        else:
            rows = self._fetch_all("""
                SELECT
                    operation_id, file_id, content_hash, operation_type,
                    source_location_id, target_node_id, status, progress_percent,
                    error_message, result_json, requested_by, created_at,
                    started_at, completed_at, updated_at
                FROM storage_operations
                ORDER BY created_at DESC
                LIMIT :limit
            """, limit=limit)
        return self._storage_operation_rows_to_dicts(rows)

    def file_has_cached_location(self, file_id):
        rows = self._fetch_all("""
            SELECT cl.location_id
            FROM file_aliases fa
            JOIN content_locations cl ON fa.content_hash = cl.content_hash
            WHERE fa.file_id = :file_id
              AND cl.location_type = 'CACHED'
            LIMIT 1
        """, file_id=file_id)
        return bool(rows)

    def claim_pending_storage_operation(self):
        with self._transaction() as conn:
            rows = conn.run("""
                SELECT
                    so.operation_id, so.file_id, so.content_hash, so.operation_type,
                    so.source_location_id, so.target_node_id, so.status, so.progress_percent,
                    so.error_message, so.result_json, so.requested_by, so.created_at,
                    so.started_at, so.completed_at, so.updated_at,
                    fa.file_name, cl.physical_path, sn.host, sn.port
                FROM storage_operations so
                JOIN file_aliases fa ON so.file_id = fa.file_id
                JOIN content_locations cl ON so.source_location_id = cl.location_id
                JOIN storage_nodes sn ON so.target_node_id = sn.node_id
                WHERE so.status = 'PENDING'
                ORDER BY so.created_at ASC
                LIMIT 1
                FOR UPDATE
            """) or []
            if not rows:
                return None

            operation_id = rows[0][0]
            conn.run("""
                UPDATE storage_operations
                SET status = 'RUNNING',
                    started_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP,
                    progress_percent = 0
                WHERE operation_id = :operation_id
            """, operation_id=operation_id)

        columns = [
            'operation_id', 'file_id', 'content_hash', 'operation_type',
            'source_location_id', 'target_node_id', 'status', 'progress_percent',
            'error_message', 'result_json', 'requested_by', 'created_at',
            'started_at', 'completed_at', 'updated_at',
            'file_name', 'physical_path', 'host', 'port',
        ]
        operation = dict(zip(columns, rows[0]))
        operation["operation_id"] = str(operation["operation_id"])
        operation["file_id"] = str(operation["file_id"])
        operation["status"] = "RUNNING"
        return operation

    def complete_storage_operation(self, operation_id, result_json=None):
        with self._transaction() as conn:
            rows = conn.run("""
                UPDATE storage_operations
                SET status = 'COMPLETED',
                    progress_percent = 100,
                    result_json = :result_json,
                    completed_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP,
                    error_message = NULL
                WHERE operation_id = :operation_id
                RETURNING
                    operation_id, file_id, content_hash, operation_type,
                    source_location_id, target_node_id, status, progress_percent,
                    error_message, result_json, requested_by, created_at,
                    started_at, completed_at, updated_at
            """, operation_id=operation_id, result_json=result_json) or []
        return self._storage_operation_row_to_dict(rows[0]) if rows else None

    def fail_storage_operation(self, operation_id, error_message, result_json=None):
        with self._transaction() as conn:
            rows = conn.run("""
                UPDATE storage_operations
                SET status = 'FAILED',
                    error_message = :error_message,
                    result_json = :result_json,
                    completed_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE operation_id = :operation_id
                RETURNING
                    operation_id, file_id, content_hash, operation_type,
                    source_location_id, target_node_id, status, progress_percent,
                    error_message, result_json, requested_by, created_at,
                    started_at, completed_at, updated_at
            """, operation_id=operation_id, error_message=error_message, result_json=result_json) or []
        return self._storage_operation_row_to_dict(rows[0]) if rows else None

    def upsert_technical_metadata(self, content_hash, metadata):
        if not content_hash or not metadata:
            return False

        def clean_int(value):
            if value in (None, ""):
                return None
            try:
                return int(float(value))
            except (TypeError, ValueError):
                return None

        def clean_float(value):
            if value in (None, ""):
                return None
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        probe_status = metadata.get("probe_status") or "unknown"
        if probe_status not in {"success", "failed", "unavailable", "skipped", "unknown"}:
            probe_status = "unknown"

        self._execute("""
            INSERT INTO media_technical_metadata (
                content_hash, duration_seconds, width, height, video_codec,
                audio_codec, audio_channels, bitrate, fps, format_name,
                probe_status, probe_error, probed_at
            )
            VALUES (
                :content_hash, :duration_seconds, :width, :height, :video_codec,
                :audio_codec, :audio_channels, :bitrate, :fps, :format_name,
                :probe_status, :probe_error, CURRENT_TIMESTAMP
            )
            ON CONFLICT (content_hash)
            DO UPDATE SET
                duration_seconds = EXCLUDED.duration_seconds,
                width = EXCLUDED.width,
                height = EXCLUDED.height,
                video_codec = EXCLUDED.video_codec,
                audio_codec = EXCLUDED.audio_codec,
                audio_channels = EXCLUDED.audio_channels,
                bitrate = EXCLUDED.bitrate,
                fps = EXCLUDED.fps,
                format_name = EXCLUDED.format_name,
                probe_status = EXCLUDED.probe_status,
                probe_error = EXCLUDED.probe_error,
                probed_at = CURRENT_TIMESTAMP
        """,
            content_hash=content_hash,
            duration_seconds=clean_float(metadata.get("duration_seconds")),
            width=clean_int(metadata.get("width")),
            height=clean_int(metadata.get("height")),
            video_codec=metadata.get("video_codec"),
            audio_codec=metadata.get("audio_codec"),
            audio_channels=clean_int(metadata.get("audio_channels")),
            bitrate=clean_int(metadata.get("bitrate")),
            fps=clean_float(metadata.get("fps")),
            format_name=metadata.get("format_name"),
            probe_status=probe_status,
            probe_error=metadata.get("probe_error"),
        )
        return True

    def get_technical_metadata(self, content_hash):
        rows = self._fetch_all("""
            SELECT
                content_hash, duration_seconds, width, height, video_codec,
                audio_codec, audio_channels, bitrate, fps, format_name,
                probe_status, probe_error, probed_at
            FROM media_technical_metadata
            WHERE content_hash = :content_hash
            LIMIT 1
        """, content_hash=content_hash)
        if not rows:
            return None

        columns = [
            'content_hash', 'duration_seconds', 'width', 'height', 'video_codec',
            'audio_codec', 'audio_channels', 'bitrate', 'fps', 'format_name',
            'probe_status', 'probe_error', 'probed_at'
        ]
        return dict(zip(columns, rows[0]))

    def upsert_thumbnail_metadata(self, content_hash, metadata):
        if not content_hash or not metadata:
            return False

        def clean_int(value):
            if value in (None, ""):
                return None
            try:
                return int(float(value))
            except (TypeError, ValueError):
                return None

        thumbnail_status = metadata.get("thumbnail_status") or metadata.get("status") or "skipped"
        if thumbnail_status not in {"success", "failed", "unavailable", "skipped"}:
            thumbnail_status = "skipped"

        self._execute("""
            INSERT INTO media_thumbnails (
                content_hash, thumbnail_path, thumbnail_status,
                width, height, generated_at, error_message
            )
            VALUES (
                :content_hash, :thumbnail_path, :thumbnail_status,
                :width, :height, CURRENT_TIMESTAMP, :error_message
            )
            ON CONFLICT (content_hash)
            DO UPDATE SET
                thumbnail_path = EXCLUDED.thumbnail_path,
                thumbnail_status = EXCLUDED.thumbnail_status,
                width = EXCLUDED.width,
                height = EXCLUDED.height,
                generated_at = CURRENT_TIMESTAMP,
                error_message = EXCLUDED.error_message
        """,
            content_hash=content_hash,
            thumbnail_path=metadata.get("thumbnail_path"),
            thumbnail_status=thumbnail_status,
            width=clean_int(metadata.get("width")),
            height=clean_int(metadata.get("height")),
            error_message=metadata.get("error_message") or metadata.get("error"),
        )
        return True

    def get_thumbnail_metadata(self, content_hash):
        rows = self._fetch_all("""
            SELECT
                content_hash, thumbnail_path, thumbnail_status,
                width, height, generated_at, error_message
            FROM media_thumbnails
            WHERE content_hash = :content_hash
            LIMIT 1
        """, content_hash=content_hash)
        if not rows:
            return None

        columns = [
            'content_hash', 'thumbnail_path', 'thumbnail_status',
            'width', 'height', 'generated_at', 'error_message'
        ]
        return dict(zip(columns, rows[0]))

    def get_file_content_hash(self, file_id):
        rows = self._fetch_all("""
            SELECT fa.content_hash
            FROM file_aliases fa
            WHERE fa.file_id = :file_id
            LIMIT 1
        """, file_id=file_id)
        return rows[0][0] if rows else None

    def list_subtitle_tracks(self, file_id, include_deleted=False):
        status_filter = "" if include_deleted else "AND status = 'active'"
        rows = self._fetch_all(f"""
            SELECT
                subtitle_id, file_id, content_hash, subtitle_file_name,
                subtitle_format, language, label, is_default,
                storage_path, vtt_path, status, created_at, deleted_at
            FROM subtitle_tracks
            WHERE file_id = :file_id
              {status_filter}
            ORDER BY is_default DESC, created_at ASC
        """, file_id=file_id)
        columns = [
            'subtitle_id', 'file_id', 'content_hash', 'subtitle_file_name',
            'subtitle_format', 'language', 'label', 'is_default',
            'storage_path', 'vtt_path', 'status', 'created_at', 'deleted_at'
        ]
        return [dict(zip(columns, row)) for row in rows]

    def create_subtitle_track(self, file_id, content_hash, subtitle_file_name,
                              subtitle_format, language, label, is_default,
                              storage_path, vtt_path=None):
        subtitle_format = subtitle_format if subtitle_format in {"srt", "vtt", "ass", "unknown"} else "unknown"
        language = (language or "unknown").strip() or "unknown"
        label = (label or language or "Unknown").strip() or "Unknown"
        is_default = bool(is_default)

        with self._transaction() as conn:
            if is_default:
                conn.run("""
                    UPDATE subtitle_tracks
                    SET is_default = FALSE
                    WHERE file_id = :file_id
                      AND status = 'active'
                """, file_id=file_id)

            rows = conn.run("""
                INSERT INTO subtitle_tracks (
                    file_id, content_hash, subtitle_file_name, subtitle_format,
                    language, label, is_default, storage_path, vtt_path, status
                )
                VALUES (
                    :file_id, :content_hash, :subtitle_file_name, :subtitle_format,
                    :language, :label, :is_default, :storage_path, :vtt_path, 'active'
                )
                RETURNING subtitle_id
            """,
                file_id=file_id,
                content_hash=content_hash,
                subtitle_file_name=subtitle_file_name,
                subtitle_format=subtitle_format,
                language=language,
                label=label,
                is_default=is_default,
                storage_path=storage_path,
                vtt_path=vtt_path,
            ) or []

        return rows[0][0] if rows else None

    def get_subtitle_track(self, subtitle_id):
        rows = self._fetch_all("""
            SELECT
                subtitle_id, file_id, content_hash, subtitle_file_name,
                subtitle_format, language, label, is_default,
                storage_path, vtt_path, status, created_at, deleted_at
            FROM subtitle_tracks
            WHERE subtitle_id = :subtitle_id
            LIMIT 1
        """, subtitle_id=subtitle_id)
        if not rows:
            return None
        columns = [
            'subtitle_id', 'file_id', 'content_hash', 'subtitle_file_name',
            'subtitle_format', 'language', 'label', 'is_default',
            'storage_path', 'vtt_path', 'status', 'created_at', 'deleted_at'
        ]
        return dict(zip(columns, rows[0]))

    def soft_delete_subtitle_track(self, subtitle_id):
        with self._transaction() as conn:
            rows = conn.run("""
                UPDATE subtitle_tracks
                SET status = 'deleted',
                    is_default = FALSE,
                    deleted_at = CURRENT_TIMESTAMP
                WHERE subtitle_id = :subtitle_id
                  AND status = 'active'
                RETURNING subtitle_id
            """, subtitle_id=subtitle_id) or []
        return bool(rows)

    def set_default_subtitle_track(self, subtitle_id):
        with self._transaction() as conn:
            rows = conn.run("""
                SELECT file_id
                FROM subtitle_tracks
                WHERE subtitle_id = :subtitle_id
                  AND status = 'active'
                LIMIT 1
            """, subtitle_id=subtitle_id) or []
            if not rows:
                return False

            file_id = rows[0][0]
            conn.run("""
                UPDATE subtitle_tracks
                SET is_default = FALSE
                WHERE file_id = :file_id
                  AND status = 'active'
            """, file_id=file_id)
            conn.run("""
                UPDATE subtitle_tracks
                SET is_default = TRUE
                WHERE subtitle_id = :subtitle_id
            """, subtitle_id=subtitle_id)
        return True

    def update_content_location_path(self, location_id, physical_path, location_type=None):
        if not location_id or not physical_path:
            return False

        with self._transaction() as conn:
            if location_type is None:
                rows = conn.run("""
                    UPDATE content_locations
                    SET physical_path = :physical_path,
                        last_seen = CURRENT_TIMESTAMP
                    WHERE location_id = :location_id
                    RETURNING location_id
                """, location_id=location_id, physical_path=physical_path) or []
            else:
                rows = conn.run("""
                    UPDATE content_locations
                    SET physical_path = :physical_path,
                        location_type = :location_type,
                        last_seen = CURRENT_TIMESTAMP
                    WHERE location_id = :location_id
                    RETURNING location_id
                """, location_id=location_id, physical_path=physical_path, location_type=location_type) or []

        return bool(rows)

    def set_file_hot_status(self, file_id, is_hot=1):
        normalized_hot = 1 if int(is_hot) else 0

        with self._transaction() as conn:
            rows = conn.run(
                "SELECT content_hash FROM file_aliases WHERE file_id = :file_id",
                file_id=file_id
            ) or []
            if not rows:
                return False

            content_hash = rows[0][0]
            conn.run("""
                UPDATE contents
                SET is_hot = :is_hot
                WHERE content_hash = :content_hash
            """, is_hot=normalized_hot, content_hash=content_hash)

        return True

    def get_file_locations(self, file_id):
        rows = self._fetch_all("""
            SELECT
                fa.file_id, fa.file_name, fa.owner, fa.original_path,
                fa.created_at, fa.file_status, fa.deleted_at, fa.deleted_by,
                c.content_hash, c.size_bytes, c.mime_type, c.media_type, c.risk_status,
                c.popularity_score, c.is_hot,
                cl.location_id, cl.node_id, cl.physical_path, cl.location_type,
                cl.is_primary, cl.last_seen,
                sn.host, sn.port, sn.status AS node_status,
                sn.shared_space_enabled
            FROM file_aliases fa
            JOIN contents c ON fa.content_hash = c.content_hash
            LEFT JOIN content_locations cl ON c.content_hash = cl.content_hash
            LEFT JOIN storage_nodes sn ON cl.node_id = sn.node_id
            WHERE fa.file_id = :file_id
              AND COALESCE(fa.file_status, 'ACTIVE') = 'ACTIVE'
            ORDER BY
                c.is_hot DESC,
                CASE cl.location_type
                    WHEN 'PINNED' THEN 1
                    WHEN 'CACHED' THEN 2
                    WHEN 'REPLICATED' THEN 3
                    WHEN 'LOCAL' THEN 4
                    ELSE 5
                END,
                cl.is_primary DESC,
                sn.status DESC,
                cl.last_seen DESC
        """, file_id=file_id)

        columns = [
            'file_id', 'file_name', 'owner', 'original_path',
            'created_at', 'file_status', 'deleted_at', 'deleted_by',
            'content_hash', 'size_bytes', 'mime_type', 'media_type', 'risk_status', 'popularity_score', 'is_hot',
            'location_id', 'node_id', 'physical_path',
            'location_type', 'is_primary', 'last_seen', 'host', 'port',
            'node_status', 'shared_space_enabled'
        ]
        return [dict(zip(columns, row)) for row in rows]

    def get_best_location(self, file_id, record_access=True):
        with self._transaction() as conn:
            rows = conn.run("""
                SELECT
                    fa.file_id, fa.file_name, fa.owner, fa.original_path,
                    fa.created_at, fa.file_status, fa.deleted_at, fa.deleted_by,
                    c.content_hash, c.size_bytes, c.mime_type, c.media_type, c.risk_status,
                    c.popularity_score, c.is_hot,
                    cl.location_id, cl.node_id, cl.physical_path, cl.location_type,
                    cl.is_primary, cl.last_seen,
                    sn.host, sn.port, sn.status AS node_status,
                    sn.shared_space_enabled
                FROM file_aliases fa
                JOIN contents c ON fa.content_hash = c.content_hash
                JOIN content_locations cl ON c.content_hash = cl.content_hash
                JOIN storage_nodes sn ON cl.node_id = sn.node_id
                WHERE fa.file_id = :file_id
                  AND COALESCE(fa.file_status, 'ACTIVE') = 'ACTIVE'
                  AND sn.status = 'ONLINE'
                  AND sn.last_heartbeat > NOW() - (:timeout_seconds * INTERVAL '1 second')
                ORDER BY
                    CASE cl.location_type
                        WHEN 'PINNED' THEN 1
                        WHEN 'CACHED' THEN 2
                        WHEN 'REPLICATED' THEN 3
                        WHEN 'LOCAL' THEN 4
                        ELSE 5
                    END,
                    cl.is_primary DESC,
                    cl.last_seen DESC
                LIMIT 1
            """, file_id=file_id, timeout_seconds=NODE_TIMEOUT_SECONDS) or []

            if not rows:
                return None

            columns = [
                'file_id', 'file_name', 'owner', 'original_path',
                'created_at', 'file_status', 'deleted_at', 'deleted_by',
                'content_hash', 'size_bytes', 'mime_type', 'media_type', 'risk_status',
                'popularity_score', 'is_hot',
                'location_id', 'node_id', 'physical_path',
                'location_type', 'is_primary', 'last_seen', 'host', 'port',
                'node_status', 'shared_space_enabled'
            ]
            best = dict(zip(columns, rows[0]))

            if record_access:
                conn.run("""
                    UPDATE contents
                    SET popularity_score = popularity_score + 1,
                        last_requested_at = CURRENT_TIMESTAMP
                    WHERE content_hash = :content_hash
                """, content_hash=best['content_hash'])

            return best

    def list_all_files(self):
        rows = self._fetch_all("""
            SELECT
                fa.file_id, fa.file_name, fa.owner, c.size_bytes, c.mime_type, c.media_type,
                c.content_hash, c.popularity_score, c.is_hot, fa.created_at, fa.file_status,
                COUNT(cl.location_id) AS locations_count,
                COALESCE(bool_or(sn.status = 'ONLINE'), FALSE) AS is_available,
                COALESCE(bool_or(cl.location_type IN ('PINNED', 'CACHED', 'REPLICATED')), FALSE) AS in_shared_space
            FROM file_aliases fa
            JOIN contents c ON fa.content_hash = c.content_hash
            LEFT JOIN content_locations cl ON c.content_hash = cl.content_hash
            LEFT JOIN storage_nodes sn ON cl.node_id = sn.node_id
            WHERE COALESCE(fa.file_status, 'ACTIVE') = 'ACTIVE'
            GROUP BY fa.file_id, c.content_hash, c.media_type, fa.file_status
            ORDER BY c.is_hot DESC, fa.created_at DESC
            LIMIT 100
        """)
        columns = [
            'file_id', 'file_name', 'owner', 'file_size', 'mime_type', 'media_type',
            'content_hash', 'popularity_score', 'is_hot', 'created_at', 'file_status',
            'locations_count', 'is_available', 'in_shared_space'
        ]
        return [dict(zip(columns, row)) for row in rows]

    def search_files(self, query):
        rows = self._fetch_all("""
            SELECT
                fa.file_id, fa.file_name, fa.owner, c.size_bytes, c.media_type,
                c.content_hash, c.popularity_score, c.is_hot, fa.created_at, fa.file_status,
                COALESCE(bool_or(sn.status = 'ONLINE'), FALSE) AS is_available,
                COALESCE(bool_or(cl.location_type IN ('PINNED', 'CACHED', 'REPLICATED')), FALSE) AS in_shared_space
            FROM file_aliases fa
            JOIN contents c ON fa.content_hash = c.content_hash
            LEFT JOIN content_locations cl ON c.content_hash = cl.content_hash
            LEFT JOIN storage_nodes sn ON cl.node_id = sn.node_id
            WHERE fa.file_name ILIKE '%' || :query || '%'
              AND COALESCE(fa.file_status, 'ACTIVE') = 'ACTIVE'
            GROUP BY fa.file_id, c.content_hash, c.media_type, fa.file_status
            ORDER BY c.is_hot DESC, fa.created_at DESC
            LIMIT 50
        """, query=query)
        columns = [
            'file_id', 'file_name', 'owner', 'file_size', 'media_type', 'content_hash',
            'popularity_score', 'is_hot', 'created_at', 'file_status', 'is_available',
            'in_shared_space'
        ]
        return [dict(zip(columns, row)) for row in rows]

    def soft_delete_file(self, file_id, deleted_by="dev"):
        """
        Hide a file alias from the library without deleting original user files.

        This only changes registry lifecycle state. Managed physical copies are moved
        to node trash by the master route after it reads the file locations.
        """
        with self._transaction() as conn:
            rows = conn.run("""
                SELECT file_id
                FROM file_aliases
                WHERE file_id = :file_id
                  AND COALESCE(file_status, 'ACTIVE') = 'ACTIVE'
            """, file_id=file_id) or []

            if not rows:
                return False

            conn.run("""
                UPDATE file_aliases
                SET file_status = 'DELETED',
                    deleted_at = CURRENT_TIMESTAMP,
                    deleted_by = :deleted_by
                WHERE file_id = :file_id
            """, file_id=file_id, deleted_by=deleted_by)

        return True

    def list_deleted_files(self):
        rows = self._fetch_all("""
            SELECT
                fa.file_id, fa.file_name, fa.owner, c.size_bytes, c.mime_type, c.media_type,
                c.content_hash, c.popularity_score, c.is_hot, fa.created_at,
                fa.file_status, fa.deleted_at, fa.deleted_by
            FROM file_aliases fa
            JOIN contents c ON fa.content_hash = c.content_hash
            WHERE COALESCE(fa.file_status, 'ACTIVE') = 'DELETED'
            ORDER BY fa.deleted_at DESC
            LIMIT 100
        """)
        columns = [
            'file_id', 'file_name', 'owner', 'file_size', 'mime_type', 'media_type',
            'content_hash', 'popularity_score', 'is_hot', 'created_at',
            'file_status', 'deleted_at', 'deleted_by'
        ]
        return [dict(zip(columns, row)) for row in rows]

    def get_locations_for_file(self, file_id):
        """Return all known locations for a file alias regardless of lifecycle state."""
        rows = self._fetch_all("""
            SELECT
                fa.file_id, fa.file_name, fa.owner, fa.original_path,
                fa.created_at, fa.file_status, fa.deleted_at, fa.deleted_by,
                c.content_hash, c.size_bytes, c.mime_type, c.media_type, c.risk_status,
                c.popularity_score, c.is_hot,
                cl.location_id, cl.node_id, cl.physical_path, cl.location_type,
                cl.is_primary, cl.last_seen,
                sn.host, sn.port, sn.status AS node_status, sn.shared_space_enabled
            FROM file_aliases fa
            JOIN contents c ON fa.content_hash = c.content_hash
            LEFT JOIN content_locations cl ON c.content_hash = cl.content_hash
            LEFT JOIN storage_nodes sn ON cl.node_id = sn.node_id
            WHERE fa.file_id = :file_id
            ORDER BY cl.last_seen DESC
        """, file_id=file_id) or []

        columns = [
            'file_id', 'file_name', 'owner', 'original_path',
            'created_at', 'file_status', 'deleted_at', 'deleted_by',
            'content_hash', 'size_bytes', 'mime_type', 'media_type', 'risk_status', 'popularity_score', 'is_hot',
            'location_id', 'node_id', 'physical_path',
            'location_type', 'is_primary', 'last_seen', 'host', 'port',
            'node_status', 'shared_space_enabled'
        ]

        return [dict(zip(columns, row)) for row in rows]

    def restore_file(self, file_id):
        """
        Mark a previously DELETED file alias as ACTIVE. Returns True if transitioned,
        False if the file wasn't in DELETED state or didn't exist.
        """
        with self._transaction() as conn:
            rows = conn.run("""
                SELECT file_id
                FROM file_aliases
                WHERE file_id = :file_id
                  AND COALESCE(file_status, 'ACTIVE') = 'DELETED'
                LIMIT 1
            """, file_id=file_id) or []

            if not rows:
                return False

            conn.run("""
                UPDATE file_aliases
                SET file_status = 'ACTIVE', deleted_at = NULL, deleted_by = NULL
                WHERE file_id = :file_id
            """, file_id=file_id)

        return True

    def list_media_drafts(self, review_status="pending"):
        rows = self._fetch_all("""
            SELECT
                md.draft_id, md.file_id, md.content_hash, md.review_status,
                md.suggested_media_kind, md.user_media_kind, md.final_media_kind,
                md.suggested_title, md.user_title, md.final_title,
                md.year, md.season, md.episode,
                md.collection_id, md.collection_title, md.collection_type,
                md.season_number, md.episode_number,
                md.language, md.notes,
                md.created_at, md.reviewed_at, md.reviewed_by,
                fa.file_name, fa.owner, fa.file_status,
                c.size_bytes, c.mime_type, c.media_type,
                mc.title AS saved_collection_title,
                mc.collection_type AS saved_collection_type
            FROM media_drafts md
            JOIN file_aliases fa ON md.file_id = fa.file_id
            JOIN contents c ON md.content_hash = c.content_hash
            LEFT JOIN media_collections mc ON md.collection_id = mc.collection_id
            WHERE md.review_status = :review_status
            ORDER BY md.created_at DESC
            LIMIT 100
        """, review_status=review_status)
        return self._media_draft_rows_to_dicts(rows)

    def get_media_draft(self, draft_id):
        rows = self._fetch_all("""
            SELECT
                md.draft_id, md.file_id, md.content_hash, md.review_status,
                md.suggested_media_kind, md.user_media_kind, md.final_media_kind,
                md.suggested_title, md.user_title, md.final_title,
                md.year, md.season, md.episode,
                md.collection_id, md.collection_title, md.collection_type,
                md.season_number, md.episode_number,
                md.language, md.notes,
                md.created_at, md.reviewed_at, md.reviewed_by,
                fa.file_name, fa.owner, fa.file_status,
                c.size_bytes, c.mime_type, c.media_type,
                mc.title AS saved_collection_title,
                mc.collection_type AS saved_collection_type
            FROM media_drafts md
            JOIN file_aliases fa ON md.file_id = fa.file_id
            JOIN contents c ON md.content_hash = c.content_hash
            LEFT JOIN media_collections mc ON md.collection_id = mc.collection_id
            WHERE md.draft_id = :draft_id
            LIMIT 1
        """, draft_id=draft_id)
        drafts = self._media_draft_rows_to_dicts(rows)
        return drafts[0] if drafts else None

    def update_media_draft(self, draft_id, user_media_kind=None, user_title=None,
                           collection_id=None, collection_title=None,
                           collection_type="unknown", season_number=None,
                           episode_number=None):
        if user_media_kind and user_media_kind not in MEDIA_KIND_VALUES:
            raise ValueError(f"Invalid media_kind: {user_media_kind}")

        collection_title = (collection_title or "").strip() or None
        collection_type = collection_type or "unknown"
        if collection_type not in COLLECTION_TYPE_VALUES:
            raise ValueError(f"Invalid collection_type: {collection_type}")

        with self._transaction() as conn:
            if collection_id is None and collection_title:
                collection_id = self._create_media_collection_in_tx(
                    conn,
                    collection_title,
                    collection_type=collection_type,
                )

            if collection_id is not None:
                collection_rows = conn.run("""
                    SELECT title, collection_type
                    FROM media_collections
                    WHERE collection_id = :collection_id
                    LIMIT 1
                """, collection_id=collection_id) or []
                if not collection_rows:
                    raise ValueError(f"Collection not found: {collection_id}")
                collection_title = collection_rows[0][0]
                collection_type = collection_rows[0][1]

            rows = conn.run("""
                UPDATE media_drafts
                SET user_media_kind = :user_media_kind,
                    user_title = :user_title,
                    collection_id = :collection_id,
                    collection_title = :collection_title,
                    collection_type = :collection_type,
                    season_number = :season_number,
                    episode_number = :episode_number
                WHERE draft_id = :draft_id
                  AND review_status = 'pending'
                RETURNING draft_id
            """, draft_id=draft_id, user_media_kind=user_media_kind,
                 user_title=user_title, collection_id=collection_id,
                 collection_title=collection_title, collection_type=collection_type,
                 season_number=season_number, episode_number=episode_number) or []

        return bool(rows)

    def get_media_for_file(self, file_id):
        draft_rows = self._fetch_all("""
            SELECT
                md.draft_id, md.file_id, md.content_hash, md.review_status,
                md.suggested_media_kind, md.user_media_kind, md.final_media_kind,
                md.suggested_title, md.user_title, md.final_title,
                md.year, md.season, md.episode,
                md.collection_id, md.collection_title, md.collection_type,
                md.season_number, md.episode_number,
                md.language, md.notes,
                md.created_at, md.reviewed_at, md.reviewed_by,
                fa.file_name, fa.owner, fa.file_status,
                c.size_bytes, c.mime_type, c.media_type,
                mc.title AS saved_collection_title,
                mc.collection_type AS saved_collection_type
            FROM media_drafts md
            JOIN file_aliases fa ON md.file_id = fa.file_id
            JOIN contents c ON md.content_hash = c.content_hash
            LEFT JOIN media_collections mc ON md.collection_id = mc.collection_id
            WHERE md.file_id = :file_id
            ORDER BY md.created_at DESC
            LIMIT 1
        """, file_id=file_id)
        drafts = self._media_draft_rows_to_dicts(draft_rows)

        item_rows = self._fetch_all("""
            SELECT
                mi.media_id, mi.file_id, mi.content_hash, mi.media_kind,
                mi.title, mi.year, mi.season, mi.episode, mi.language,
                mi.collection_id, mc.title AS collection_title, mc.collection_type,
                mi.season_number, mi.episode_number, mi.display_order,
                mi.created_at, mi.updated_at,
                fa.file_name, fa.owner, fa.file_status,
                c.size_bytes, c.mime_type, c.media_type,
                COALESCE(bool_or(sn.status = 'ONLINE'), FALSE) AS is_available
            FROM media_items mi
            JOIN file_aliases fa ON mi.file_id = fa.file_id
            JOIN contents c ON mi.content_hash = c.content_hash
            LEFT JOIN content_locations cl ON mi.content_hash = cl.content_hash
            LEFT JOIN storage_nodes sn ON cl.node_id = sn.node_id
            LEFT JOIN media_collections mc ON mi.collection_id = mc.collection_id
            WHERE mi.file_id = :file_id
            GROUP BY mi.media_id, fa.file_id, c.content_hash, mc.collection_id
            LIMIT 1
        """, file_id=file_id)
        items = self._media_item_rows_to_dicts(item_rows)

        return {
            "draft": drafts[0] if drafts else None,
            "item": items[0] if items else None,
            "collections": self.list_media_collections(),
        }

    def get_media_neighbors(self, file_id):
        current_rows = self._fetch_all("""
            SELECT
                mi.collection_id,
                COALESCE(mi.season_number, mi.season, 1) AS season_number,
                mi.episode_number
            FROM media_items mi
            JOIN file_aliases fa ON mi.file_id = fa.file_id
            WHERE mi.file_id = :file_id
              AND COALESCE(fa.file_status, 'ACTIVE') = 'ACTIVE'
            LIMIT 1
        """, file_id=file_id)
        if not current_rows:
            return {"previous": None, "next": None}

        collection_id, season_number, episode_number = current_rows[0]
        if not collection_id or episode_number is None:
            return {"previous": None, "next": None}

        def fetch_neighbor(target_episode):
            rows = self._fetch_all("""
                SELECT
                    mi.media_id, mi.file_id, mi.content_hash, mi.media_kind,
                    mi.title, mi.year, mi.season, mi.episode, mi.language,
                    mi.collection_id, mc.title AS collection_title, mc.collection_type,
                    mi.season_number, mi.episode_number, mi.display_order,
                    mi.created_at, mi.updated_at,
                    fa.file_name, fa.owner, fa.file_status,
                    c.size_bytes, c.mime_type, c.media_type,
                    COALESCE(bool_or(sn.status = 'ONLINE'), FALSE) AS is_available
                FROM media_items mi
                JOIN file_aliases fa ON mi.file_id = fa.file_id
                JOIN contents c ON mi.content_hash = c.content_hash
                LEFT JOIN content_locations cl ON mi.content_hash = cl.content_hash
                LEFT JOIN storage_nodes sn ON cl.node_id = sn.node_id
                LEFT JOIN media_collections mc ON mi.collection_id = mc.collection_id
                WHERE mi.collection_id = :collection_id
                  AND COALESCE(mi.season_number, mi.season, 1) = :season_number
                  AND mi.episode_number = :episode_number
                  AND COALESCE(fa.file_status, 'ACTIVE') = 'ACTIVE'
                GROUP BY mi.media_id, fa.file_id, c.content_hash, mc.collection_id
                LIMIT 1
            """, collection_id=collection_id, season_number=season_number,
                 episode_number=target_episode)
            items = self._media_item_rows_to_dicts(rows)
            return items[0] if items else None

        return {
            "previous": fetch_neighbor(int(episode_number) - 1),
            "next": fetch_neighbor(int(episode_number) + 1),
        }

    def update_media_item_for_file(self, file_id, media_kind=None, title=None,
                                   collection_id=None, collection_title=None,
                                   collection_type="unknown", season_number=None,
                                   episode_number=None, year=None, language=None,
                                   display_order=None):
        if media_kind and media_kind not in MEDIA_KIND_VALUES:
            raise ValueError(f"Invalid media_kind: {media_kind}")
        if not title:
            raise ValueError("title is required")

        collection_title = (collection_title or "").strip() or None
        collection_type = collection_type or "unknown"
        if collection_type not in COLLECTION_TYPE_VALUES:
            raise ValueError(f"Invalid collection_type: {collection_type}")

        season = season_number
        episode = episode_number

        with self._transaction() as conn:
            if collection_id is None and collection_title:
                collection_id = self._create_media_collection_in_tx(conn, collection_title, collection_type)

            rows = conn.run("""
                UPDATE media_items
                SET media_kind = :media_kind,
                    title = :title,
                    year = :year,
                    season = :season,
                    episode = :episode,
                    language = :language,
                    collection_id = :collection_id,
                    season_number = :season_number,
                    episode_number = :episode_number,
                    display_order = :display_order,
                    updated_at = CURRENT_TIMESTAMP
                WHERE file_id = :file_id
                RETURNING media_id
            """, file_id=file_id, media_kind=media_kind, title=title,
                 year=year, season=season, episode=episode, language=language,
                 collection_id=collection_id, season_number=season_number,
                 episode_number=episode_number, display_order=display_order) or []

        return bool(rows)

    def list_media_collections(self):
        rows = self._fetch_all("""
            SELECT
                mc.collection_id,
                mc.title,
                mc.collection_type,
                mc.created_at,
                mc.updated_at,
                COUNT(mi.media_id) AS item_count
            FROM media_collections mc
            LEFT JOIN media_items mi ON mc.collection_id = mi.collection_id
            GROUP BY mc.collection_id
            ORDER BY mc.collection_type, mc.title
        """)
        columns = ['collection_id', 'title', 'collection_type', 'created_at', 'updated_at', 'item_count']
        return [dict(zip(columns, row)) for row in rows]

    def delete_media_collection(self, collection_id):
        with self._transaction() as conn:
            rows = conn.run("""
                SELECT collection_id, title, collection_type
                FROM media_collections
                WHERE collection_id = :collection_id
                LIMIT 1
            """, collection_id=collection_id) or []
            if not rows:
                return {"deleted": False, "status": "not_found", "message": "Collection not found"}

            item_rows = conn.run("""
                SELECT COUNT(*)
                FROM media_items
                WHERE collection_id = :collection_id
            """, collection_id=collection_id) or [(0,)]
            item_count = int(item_rows[0][0])
            if item_count > 0:
                return {
                    "deleted": False,
                    "status": "not_empty",
                    "item_count": item_count,
                    "message": f"Collection has {item_count} media item(s). Remove or move them before deleting.",
                }

            conn.run("""
                UPDATE media_drafts
                SET collection_id = NULL
                WHERE collection_id = :collection_id
            """, collection_id=collection_id)

            conn.run("""
                DELETE FROM media_collections
                WHERE collection_id = :collection_id
            """, collection_id=collection_id)

        collection = dict(zip(['collection_id', 'title', 'collection_type'], rows[0]))
        return {"deleted": True, "status": "deleted", "collection": collection}

    def create_media_collection(self, title, collection_type="unknown"):
        title = (title or "").strip()
        collection_type = collection_type or "unknown"
        if not title:
            raise ValueError("collection title is required")
        if collection_type not in COLLECTION_TYPE_VALUES:
            raise ValueError(f"Invalid collection_type: {collection_type}")

        with self._transaction() as conn:
            rows = self._get_or_create_media_collection_rows_in_tx(conn, title, collection_type)

        columns = ['collection_id', 'title', 'collection_type', 'created_at', 'updated_at']
        return dict(zip(columns, rows[0])) if rows else None

    def _create_media_collection_in_tx(self, conn, title, collection_type="unknown"):
        title = (title or "").strip()
        collection_type = collection_type or "unknown"
        if not title:
            return None
        if collection_type not in COLLECTION_TYPE_VALUES:
            raise ValueError(f"Invalid collection_type: {collection_type}")

        rows = self._get_or_create_media_collection_rows_in_tx(conn, title, collection_type)
        return rows[0][0] if rows else None

    def _get_or_create_media_collection_rows_in_tx(self, conn, title, collection_type):
        rows = conn.run("""
            SELECT collection_id, title, collection_type, created_at, updated_at
            FROM media_collections
            WHERE title = :title AND collection_type = :collection_type
            LIMIT 1
        """, title=title, collection_type=collection_type) or []
        if rows:
            return rows

        if collection_type != "unknown":
            rows = conn.run("""
                UPDATE media_collections
                SET collection_type = :collection_type,
                    updated_at = CURRENT_TIMESTAMP
                WHERE collection_id = (
                    SELECT collection_id
                    FROM media_collections
                    WHERE title = :title AND collection_type = 'unknown'
                    LIMIT 1
                )
                RETURNING collection_id, title, collection_type, created_at, updated_at
            """, title=title, collection_type=collection_type) or []
            if rows:
                return rows

        rows = conn.run("""
            INSERT INTO media_collections (title, collection_type, updated_at)
            VALUES (:title, :collection_type, CURRENT_TIMESTAMP)
            ON CONFLICT (title, collection_type)
            DO UPDATE SET updated_at = CURRENT_TIMESTAMP
            RETURNING collection_id, title, collection_type, created_at, updated_at
        """, title=title, collection_type=collection_type) or []
        return rows

    def approve_media_draft(self, draft_id, final_media_kind, final_title,
                            year=None, season=None, episode=None, language=None,
                            reviewed_by="dashboard-dev", collection_id=None,
                            collection_title=None, collection_type="unknown",
                            season_number=None, episode_number=None,
                            display_order=None):
        if final_media_kind not in MEDIA_KIND_VALUES:
            raise ValueError(f"Invalid final_media_kind: {final_media_kind}")
        if not final_title:
            raise ValueError("final_title is required")

        season_number = season_number if season_number is not None else season
        episode_number = episode_number if episode_number is not None else episode
        season = season if season is not None else season_number
        episode = episode if episode is not None else episode_number

        with self._transaction() as conn:
            if collection_id is None and collection_title:
                collection_id = self._create_media_collection_in_tx(
                    conn,
                    collection_title,
                    collection_type=collection_type,
                )

            rows = conn.run("""
                UPDATE media_drafts
                SET review_status = 'approved',
                    final_media_kind = :final_media_kind,
                    final_title = :final_title,
                    year = :year,
                    season = :season,
                    episode = :episode,
                    language = :language,
                    reviewed_by = :reviewed_by,
                    reviewed_at = CURRENT_TIMESTAMP
                WHERE draft_id = :draft_id
                  AND review_status = 'pending'
                RETURNING draft_id, file_id, content_hash
            """, draft_id=draft_id, final_media_kind=final_media_kind,
                 final_title=final_title, year=year, season=season,
                 episode=episode, language=language, reviewed_by=reviewed_by) or []

            if not rows:
                return False

            _, file_id, content_hash = rows[0]
            conn.run("""
                INSERT INTO media_items (
                    file_id, content_hash, media_kind, title,
                    year, season, episode, language,
                    collection_id, season_number, episode_number, display_order,
                    updated_at
                )
                VALUES (
                    :file_id, :content_hash, :media_kind, :title,
                    :year, :season, :episode, :language,
                    :collection_id, :season_number, :episode_number, :display_order,
                    CURRENT_TIMESTAMP
                )
                ON CONFLICT (file_id)
                DO UPDATE SET
                    content_hash = EXCLUDED.content_hash,
                    media_kind = EXCLUDED.media_kind,
                    title = EXCLUDED.title,
                    year = EXCLUDED.year,
                    season = EXCLUDED.season,
                    episode = EXCLUDED.episode,
                    language = EXCLUDED.language,
                    collection_id = EXCLUDED.collection_id,
                    season_number = EXCLUDED.season_number,
                    episode_number = EXCLUDED.episode_number,
                    display_order = EXCLUDED.display_order,
                    updated_at = CURRENT_TIMESTAMP
            """, file_id=file_id, content_hash=content_hash,
                 media_kind=final_media_kind, title=final_title,
                 year=year, season=season, episode=episode, language=language,
                 collection_id=collection_id, season_number=season_number,
                 episode_number=episode_number, display_order=display_order)

        return True

    def reject_media_draft(self, draft_id, reviewed_by="dashboard-dev", reason=None):
        with self._transaction() as conn:
            rows = conn.run("""
                UPDATE media_drafts
                SET review_status = 'rejected',
                    reviewed_by = :reviewed_by,
                    reviewed_at = CURRENT_TIMESTAMP,
                    notes = :reason
                WHERE draft_id = :draft_id
                  AND review_status = 'pending'
                RETURNING draft_id
            """, draft_id=draft_id, reviewed_by=reviewed_by, reason=reason) or []
        return bool(rows)

    def list_media_items(self, include_deleted=False):
        status_filter = "" if include_deleted else "WHERE COALESCE(fa.file_status, 'ACTIVE') = 'ACTIVE'"
        rows = self._fetch_all(f"""
            SELECT
                mi.media_id, mi.file_id, mi.content_hash, mi.media_kind,
                mi.title, mi.year, mi.season, mi.episode, mi.language,
                mi.collection_id, mc.title AS collection_title, mc.collection_type,
                mi.season_number, mi.episode_number, mi.display_order,
                mi.created_at, mi.updated_at,
                fa.file_name, fa.owner, fa.file_status,
                c.size_bytes, c.mime_type, c.media_type,
                COALESCE(bool_or(sn.status = 'ONLINE'), FALSE) AS is_available
            FROM media_items mi
            JOIN file_aliases fa ON mi.file_id = fa.file_id
            JOIN contents c ON mi.content_hash = c.content_hash
            LEFT JOIN content_locations cl ON mi.content_hash = cl.content_hash
            LEFT JOIN storage_nodes sn ON cl.node_id = sn.node_id
            LEFT JOIN media_collections mc ON mi.collection_id = mc.collection_id
            {status_filter}
            GROUP BY mi.media_id, fa.file_id, c.content_hash, mc.collection_id
            ORDER BY mi.media_kind, COALESCE(mc.title, mi.title),
                     mi.season_number NULLS LAST, mi.episode_number NULLS LAST,
                     mi.display_order NULLS LAST, mi.year NULLS LAST
        """)
        return self._media_item_rows_to_dicts(rows)

    def get_media_library_grouped(self):
        items = self.list_media_items(include_deleted=False)
        grouped = {
            "movies": [],
            "series": {},
            "anime": {},
            "youtube": [],
            "shorts": [],
            "courses": [],
            "clips": [],
            "other": [],
        }

        for item in items:
            kind = item.get("media_kind")
            if kind == "movie":
                grouped["movies"].append(item)
            elif kind == "series_episode":
                self._add_item_to_collection_group(grouped["series"], item)
            elif kind == "anime_episode":
                self._add_item_to_collection_group(grouped["anime"], item)
            elif kind == "youtube_video":
                grouped["youtube"].append(item)
            elif kind == "short":
                grouped["shorts"].append(item)
            elif kind == "course":
                grouped["courses"].append(item)
            elif kind == "clip":
                grouped["clips"].append(item)
            else:
                grouped["other"].append(item)

        grouped["series"] = list(grouped["series"].values())
        grouped["anime"] = list(grouped["anime"].values())
        return grouped

    def _add_item_to_collection_group(self, groups, item):
        collection_id = item.get("collection_id")
        title = item.get("collection_title") or item.get("title") or "Untitled"
        key = f"id:{collection_id}" if collection_id else f"title:{title}"
        season = item.get("season_number")
        if season is None:
            season = item.get("season")
        season_key = str(season if season is not None else 1)
        if key not in groups:
            groups[key] = {
                "collection_id": collection_id,
                "title": title,
                "collection_type": item.get("collection_type"),
                "seasons": {},
            }
        groups[key]["seasons"].setdefault(season_key, []).append(item)

    def _media_draft_rows_to_dicts(self, rows):
        columns = [
            'draft_id', 'file_id', 'content_hash', 'review_status',
            'suggested_media_kind', 'user_media_kind', 'final_media_kind',
            'suggested_title', 'user_title', 'final_title',
            'year', 'season', 'episode',
            'collection_id', 'collection_title', 'collection_type',
            'season_number', 'episode_number',
            'language', 'notes',
            'created_at', 'reviewed_at', 'reviewed_by',
            'file_name', 'owner', 'file_status',
            'file_size', 'mime_type', 'media_type',
            'saved_collection_title', 'saved_collection_type'
        ]
        return [dict(zip(columns, row)) for row in rows]

    def _media_item_rows_to_dicts(self, rows):
        columns = [
            'media_id', 'file_id', 'content_hash', 'media_kind',
            'title', 'year', 'season', 'episode', 'language',
            'collection_id', 'collection_title', 'collection_type',
            'season_number', 'episode_number', 'display_order',
            'created_at', 'updated_at',
            'file_name', 'owner', 'file_status',
            'file_size', 'mime_type', 'media_type', 'is_available'
        ]
        return [dict(zip(columns, row)) for row in rows]

    def log_access(self, file_id, content_hash, client_ip, access_type):
        self._execute("""
            INSERT INTO access_logs (file_id, content_hash, client_ip, access_type)
            VALUES (:file_id, :content_hash, :client_ip, :access_type)
        """, file_id=file_id, content_hash=content_hash,
             client_ip=client_ip, access_type=access_type)
