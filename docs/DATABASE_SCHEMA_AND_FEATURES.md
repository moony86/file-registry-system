# FSYS Database Map

## storage_nodes
يمثل الأجهزة أو الخدمات التي تخزن الملفات أو تخدمها.

أعمدة مهمة:
- node_id
- host / port
- status
- shared_space_enabled
- shared_space_limit_bytes
- shared_space_used_bytes
- last_heartbeat
- registered_at

ميزات مبنية عليه:
- عرض النودز المتصلة.
- heartbeat.
- offline detection.
- اختيار أفضل نود للتحميل.

ميزات يمكن إضافتها:
- node_type: user/server/backup.
- priority.
- trusted.
- location_label.
- bandwidth_score.

---

## contents
يمثل المحتوى الحقيقي بناءً على content_hash.

أعمدة مهمة:
- content_hash
- size_bytes
- mime_type
- media_type
- risk_status
- popularity_score
- is_hot
- created_at
- last_requested_at

ميزات مبنية عليه:
- Deduplication.
- media_type.
- HOT/Pinned.
- popularity.
- تصنيف أولي.

ميزات يمكن إضافتها:
- duration_seconds.
- resolution.
- codec.
- scan_status.
- poster_path.
- content_status.

---

## file_aliases
يمثل ظهور الملف للمستخدم.

أعمدة مهمة:
- file_id
- content_hash
- file_name
- owner
- original_path
- created_at
- lifecycle_status أو is_deleted/deleted_at حسب التطبيق.

ميزات مبنية عليه:
- قائمة الملفات.
- البحث.
- Details.
- Soft delete.
- Restore.

ميزات يمكن إضافتها:
- display_title.
- tags.
- review_status.
- visibility.
- deleted_reason.

---

## content_locations
يمثل أين توجد نسخة من المحتوى.

أعمدة مهمة:
- location_id
- content_hash
- node_id
- physical_path
- location_type: LOCAL/CACHED/PINNED/REPLICATED
- is_primary
- last_seen
- added_at

ميزات مبنية عليه:
- معرفة مواقع النسخ.
- عدم لمس LOCAL عند الحذف.
- نقل CACHED/PINNED/REPLICATED إلى trash.
- اختيار أفضل مصدر للتحميل أو الستريم.

ميزات يمكن إضافتها:
- trash_path.
- restore_status.
- health_status.
- preferred_playback_source.

---

## access_logs
يسجل الوصول للملفات.

أعمدة مهمة:
- log_id
- file_id
- content_hash
- client_ip
- access_type
- accessed_at

ميزات مبنية عليه:
- popularity_score.
- history.
- watch progress لاحقاً.
- activity monitoring.

---

# كيف تضيف عموداً جديداً؟

مثال: إضافة review_status للملفات.

1. في `database.py` داخل `init_tables`:

```python
conn.run("""
    ALTER TABLE file_aliases
    ADD COLUMN IF NOT EXISTS review_status VARCHAR(30) DEFAULT 'approved'
""")
```

2. أضفه في SELECT.
3. أضفه في قائمة columns.
4. أرجعه في API.
5. اعرضه في Dashboard.

# كيف تضيف جدولاً جديداً؟

مثال: جدول media_drafts.

```python
conn.run("""
    CREATE TABLE IF NOT EXISTS media_drafts (
        draft_id SERIAL PRIMARY KEY,
        file_id UUID REFERENCES file_aliases(file_id) ON DELETE CASCADE,
        suggested_type VARCHAR(30),
        suggested_title VARCHAR(500),
        suggested_season INTEGER,
        suggested_episode INTEGER,
        status VARCHAR(30) DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")
```

ثم:
- أضف دوال في Database.
- أضف routes في master-node/routes.
- أضف UI في Dashboard.
