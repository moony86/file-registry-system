# FSYS Flows

## Upload Flow
```text
Browser Dashboard
  ↓ POST /api/files/cache
Storage Node
  ↓ save temp
  ↓ hash
  ↓ dedupe check
  ↓ move to shared_space if new
  ↓ detect media_type
  ↓ POST /api/files/register
Master
  ↓ upsert contents
  ↓ insert/reuse file_alias
  ↓ upsert content_location
Dashboard
  ↓ refresh /api/files
```

## Details Flow
```text
Dashboard
  ↓ GET /api/files/<file_id>
Master
  ↓ get_file_locations()
  ↓ join aliases + contents + locations + nodes
Dashboard
  ↓ show modal
```

## Delete Flow
```text
Dashboard
  ↓ DELETE /api/files/<file_id>
Master
  ↓ mark alias DELETED
  ↓ find managed locations
  ↓ POST node /api/files/<file_id>/trash
Node
  ↓ verify hash/path
  ↓ move shared_space file to trash
  ↓ update space_cache
Dashboard
  ↓ refresh list
```

## Restore Flow - planned
```text
Dashboard
  ↓ POST /api/files/<file_id>/restore
Master
  ↓ mark alias ACTIVE
  ↓ ask node to move from trash to shared_space
Node
  ↓ restore if trash exists
Dashboard
  ↓ file appears
```

## Streaming Flow - planned
```text
Dashboard
  ↓ Play
Master
  ↓ get best online location
Browser/Player
  ↓ request stream from Node
Node
  ↓ serve file with Range support
Browser
  ↓ seek/play video
```

## قاعدة مهمة
Database = Source of Truth.
Filesystem = Storage Layer.
