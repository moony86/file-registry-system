# FSYS API Reference

## Master API
Base:
`http://localhost:5000`

### POST /api/nodes/register
يسجل النود أو يحدث بياناته.

Header:
`X-FSYS-Token: dev-token`

Body:
```json
{
  "node_id": "node-1",
  "host": "localhost",
  "port": 5001,
  "shared_space_enabled": true,
  "shared_space_limit_bytes": 1073741824,
  "shared_space_used_bytes": 12345
}
```

### POST /api/nodes/heartbeat
يرسل نبضة حياة من النود.

### GET /api/nodes
يعرض النودز.

### GET /api/status
يعرض حالة النظام.

---

## Files

### POST /api/files/register
تسجيل ملف في الماستر. لا يرفع الملف نفسه.

Body:
```json
{
  "content_hash": "sha256...",
  "file_name": "movie.mp4",
  "owner": "Web_UI_User",
  "size_bytes": 123456,
  "mime_type": "video/mp4",
  "media_type": "video",
  "node_id": "node-1",
  "physical_path": "/path/to/shared_space/...",
  "location_type": "CACHED"
}
```

### GET /api/files
يعرض الملفات النشطة.

يرجع غالباً:
- file_id
- file_name
- owner
- file_size
- mime_type
- media_type
- content_hash
- popularity_score
- is_hot
- created_at
- locations_count
- is_available
- in_shared_space

### GET /api/files/search?q=...
بحث.

### GET /api/files/<file_id>
تفاصيل ملف.

### GET /api/files/<file_id>/location
أفضل موقع للملف.

### POST /api/files/<file_id>/hot
تثبيت HOT.

### DELETE /api/files/<file_id>
حذف آمن:
- يخفي الملف من القائمة.
- يطلب نقل النسخ المدارة إلى trash.
- لا يلمس LOCAL.

---

## Storage Node API
Base:
`http://localhost:5001`

### GET /
معلومات النود.

### GET /api/status
حالة النود والمساحة.

### POST /api/files/cache
رفع ملف إلى shared_space.

Form:
- file
- owner
- location_type

### POST /api/files/register
تسجيل ملف محلي بدون نسخه.

### GET /api/files/<file_id>/download
تحميل الملف من النود.

### GET /api/files/<file_id>/stream
Streams video files directly from the selected Storage Node.

Behavior:
- Resolves the active file location through Master.
- Refuses non-video files.
- Does not accept a filesystem path from the client.
- Supports HTTP Range requests for seek.

Responses:
- `200 OK` without a Range header.
- `206 Partial Content` with a valid Range header.
- `416 Range Not Satisfiable` for invalid ranges.

### POST /api/files/<file_id>/trash
ينقل نسخة managed إلى trash.

### POST /api/debug/resync
يعيد حساب المساحة من القرص.
