# FSYS v2 Patch - Hybrid Registry + Shared Space

## What changed

- Files are now identified by `content_hash = SHA256(bytes)`.
- Same content with different names becomes multiple aliases pointing to one content row.
- Storage nodes can either:
  - register a local file path as `LOCAL`, no copy, or
  - upload into managed `Shared Space` as `CACHED` or `PINNED`.
- Master stores `contents`, `file_aliases`, and `content_locations`.
- Basic shared token added between master and storage node via `FSYS_NODE_TOKEN`.
- Download verifies checksum before serving and after receiving.

## Minimal env

Master:

```bash
export FSYS_NODE_TOKEN=dev-token
export MASTER_PORT=5000
python master-node/app.py
```

Storage:

```bash
export FSYS_NODE_TOKEN=dev-token
export NODE_ID=node-a
export NODE_HOST=localhost
export NODE_PORT=5001
export MASTER_URL=http://localhost:5000
export SHARED_SPACE_ENABLED=true
export SHARED_SPACE_DIR=./shared_space
export SHARED_SPACE_LIMIT_BYTES=1073741824
python storage-node/app.py
```

CLI:

```bash
export FSYS_MASTER=http://localhost:5000
export FSYS_NODE=http://localhost:5001
python cli/fsys.py status
python cli/fsys.py register ./example.pdf
python cli/fsys.py cache ./example.pdf
python cli/fsys.py list
python cli/fsys.py download <file_id> -o ./downloads
```

## Important limitation

This patch is still a LAN prototype. It does not implement eviction, antivirus scanning, replication policy, or production auth. Those should come next.
