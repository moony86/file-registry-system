# FSYS Project Map

## فكرة النظام
FSYS نظام لإدارة ملفات محلي/شبكي. الماستر هو مصدر الحقيقة، والنودز تخزن الملفات فعلياً.

## master-node
مسؤول عن:
- تسجيل الملفات والميتا داتا.
- حالة النودز.
- API المركزي.
- Dashboard.
- دورة حياة الملف.

أهم الملفات:
- `master-node/app.py`: تشغيل Flask وتسجيل blueprints.
- `master-node/database.py`: الجداول والاستعلامات.
- `master-node/routes/files.py`: API الملفات.
- `master-node/routes/nodes.py`: تسجيل النود والـ heartbeat.
- `master-node/routes/status.py`: حالة النظام.
- `master-node/services/auth.py`: التحقق من التوكن.
- `master-node/static/js/dashboard.js`: منطق الواجهة.
- `master-node/templates/dashboard.html`: صفحة الداشبورد.

## storage-node
مسؤول عن:
- استقبال الرفع.
- حساب الهاش.
- dedup داخل shared_space.
- trash.
- heartbeat.

أهم الملفات:
- `storage-node/app.py`: تشغيل النود.
- `storage-node/routes/files.py`: upload/register/download/trash.
- `storage-node/services/hashing.py`: hash ومسارات التخزين.
- `storage-node/services/media.py`: تحديد media_type.
- `storage-node/services/master_client.py`: تواصل النود مع الماستر.
- `storage-node/services/space_cache.py`: عداد المساحة في الذاكرة.
- `storage-node/services/heartbeat.py`: إرسال heartbeat.

## قواعد هندسية
- قاعدة البيانات هي مصدر الحقيقة.
- لا نحذف ملفات المستخدم الأصلية LOCAL.
- نحذف فقط نسخ shared_space.
- الحذف الآمن ينقل إلى trash.
- التصنيف الذكي لاحقاً يكون مساعداً وليس صاحب قرار.
