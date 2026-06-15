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
from contextlib import contextmanager
from dotenv import load_dotenv
import pg8000.native

load_dotenv()

NODE_TIMEOUT_SECONDS = int(os.getenv("NODE_TIMEOUT_SECONDS", "30"))


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

            # Lightweight indexes for common dashboard and lookup paths.
            conn.run("CREATE INDEX IF NOT EXISTS idx_storage_nodes_status_heartbeat ON storage_nodes(status, last_heartbeat)")
            conn.run("CREATE INDEX IF NOT EXISTS idx_file_aliases_content_hash ON file_aliases(content_hash)")
            conn.run("CREATE INDEX IF NOT EXISTS idx_file_aliases_status_created ON file_aliases(file_status, created_at)")
            conn.run("CREATE INDEX IF NOT EXISTS idx_content_locations_content_hash ON content_locations(content_hash)")
            conn.run("CREATE INDEX IF NOT EXISTS idx_content_locations_node_id ON content_locations(node_id)")
            conn.run("CREATE INDEX IF NOT EXISTS idx_contents_hot_created ON contents(is_hot, created_at)")

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

        return file_id

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

    def get_best_location(self, file_id):
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

    def log_access(self, file_id, content_hash, client_ip, access_type):
        self._execute("""
            INSERT INTO access_logs (file_id, content_hash, client_ip, access_type)
            VALUES (:file_id, :content_hash, :client_ip, :access_type)
        """, file_id=file_id, content_hash=content_hash,
             client_ip=client_ip, access_type=access_type)
