const MASTER_URL = window.location.origin;
const NODE_URL = "http://localhost:5001";
const ADMIN_TOKEN = "dev-token";

function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;").replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;").replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function formatBytes(bytes) {
    bytes = Number(bytes || 0);
    if (bytes === 0) return "0 B";
    const k = 1024;
    const sizes = ["B", "KB", "MB", "GB", "TB"];
    const i = Math.min(Math.floor(Math.log(bytes) / Math.log(k)), sizes.length - 1);
    const value = bytes / Math.pow(k, i);
    return `${value.toFixed(i === 0 ? 0 : 1)} ${sizes[i]}`;
}

function mediaTypeBadge(mediaType) {
    const type = (mediaType || "other").toLowerCase();
    const map = {
        video: ["🎬", "video", "badge-video"],
        audio: ["🎵", "audio", "badge-audio"],
        image: ["🖼️", "image", "badge-image"],
        document: ["📄", "document", "badge-document"],
        subtitle: ["💬", "subtitle", "badge-subtitle"],
        other: ["📦", "other", "badge-other"],
    };
    const [icon, label, cls] = map[type] || map.other;
    return `<span class="badge ${cls}">${icon} ${label}</span>`;
}

async function fetchSystemStatus() {
    try {
        const response = await fetch(`${MASTER_URL}/api/status`);
        const data = await response.json();
        document.getElementById("active-nodes-count").innerText = data.online_nodes || 0;
        const nodesTable = document.getElementById("nodes-table-body");
        nodesTable.innerHTML = "";
        for (const node of data.nodes || []) {
            nodesTable.innerHTML += `
                <tr class="text-gray-300">
                    <td class="py-4 font-mono text-cyan-400 text-xs">${escapeHtml(node.node_id)}</td>
                    <td class="py-4">${escapeHtml(node.host)}:${escapeHtml(node.port)}</td>
                    <td class="py-4 text-xs text-gray-400">${formatBytes(node.shared_space_used_bytes)} / ${formatBytes(node.shared_space_limit_bytes)}</td>
                    <td class="py-4"><span class="bg-green-500/10 text-green-400 px-2 py-0.5 rounded text-xs">ONLINE</span></td>
                </tr>`;
        }
    } catch (error) {
        console.error("فشل جلب حالة النودز:", error);
    }
}

async function fetchFilesList() {
    try {
        const response = await fetch(`${MASTER_URL}/api/files`);
        const data = await response.json();
        document.getElementById("total-files-count").innerText = data.count || 0;
        const filesTable = document.getElementById("files-table-body");
        filesTable.innerHTML = "";
        for (const file of data.files || []) {
            const isHot = file.is_hot === 1;
            const nameDisplay = isHot
                ? `<span class="font-bold text-red-400 flex items-center gap-1">🔥 ${escapeHtml(file.file_name)} <span class="bg-red-500/10 text-red-400 px-1 rounded text-[10px]">HOT</span></span>`
                : `<span class="text-gray-200">${escapeHtml(file.file_name)}</span>`;
            const pinButton = isHot
                ? `<button onclick="togglePin('${file.file_id}', true)" class="bg-gray-700 text-gray-300 px-3 py-1 rounded-lg text-xs font-semibold hover:bg-gray-600 transition">إلغاء التثبيت</button>`
                : `<button onclick="togglePin('${file.file_id}', false)" class="bg-red-500/10 text-red-400 border border-red-500/20 px-3 py-1 rounded-lg text-xs font-semibold hover:bg-red-500 hover:text-white transition">HOT 🔥</button>`;
            filesTable.innerHTML += `
                <tr class="hover:bg-gray-700/30 transition">
                    <td class="py-4 pr-2">${nameDisplay}</td>
                    <td class="py-4">${mediaTypeBadge(file.media_type)}</td>
                    <td class="py-4 text-gray-400">${escapeHtml(file.owner)}</td>
                    <td class="py-4 text-gray-400 text-xs">${formatBytes(file.file_size)}</td>
                    <td class="py-4">${file.is_available ? "✅ نعم" : "❌ لا"}</td>
                    <td class="py-4">${file.in_shared_space ? "📦 نعم" : "🔗 لا"}</td>
                    <td class="py-4 font-mono text-xs text-yellow-500">${file.popularity_score || 0}</td>
                    <td class="py-4 text-center"><div class="flex justify-center gap-2">
                        <button onclick="showDetails('${file.file_id}')" class="action-btn action-btn-details">Details</button>
                        ${pinButton}
                        <button onclick="deleteFile('${file.file_id}')" class="bg-red-900/30 text-red-300 border border-red-700/40 px-3 py-1 rounded-lg text-xs font-semibold hover:bg-red-700 hover:text-white transition">Delete</button>
                    </div></td>
                </tr>`;
        }
    } catch (error) {
        console.error("فشل جلب قائمة الملفات:", error);
    }
}

async function togglePin(fileId, isCurrentlyPinned) {
    const shouldBeHot = isCurrentlyPinned ? 0 : 1;
    try {
        const response = await fetch(`${MASTER_URL}/api/files/${fileId}/hot`, {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-FSYS-Token": ADMIN_TOKEN },
            body: JSON.stringify({ is_hot: shouldBeHot }),
        });
        if (response.ok) await fetchFilesList();
        else alert("فشلت العملية: تأكد من صلاحيات التوكن الخاص بالأدمن");
    } catch (error) {
        console.error("خطأ أثناء تعديل حالة التثبيت:", error);
    }
}

async function deleteFile(fileId) {
    const confirmed = confirm(
        "سيتم إخفاء الملف من المكتبة ونقل النسخ المُدارة داخل shared_space إلى trash.\n" +
        "لن يتم حذف ملفات LOCAL الأصلية من جهاز المستخدم.\n\n" +
        "هل تريد المتابعة؟"
    );
    if (!confirmed) return;

    try {
        const response = await fetch(`${MASTER_URL}/api/files/${fileId}`, {
            method: "DELETE",
            headers: {
                "Content-Type": "application/json",
                "X-FSYS-Token": ADMIN_TOKEN,
            },
            body: JSON.stringify({ deleted_by: "dashboard-dev" }),
        });

        const data = await response.json().catch(() => ({}));
        if (response.ok) {
            closeDetailsModal();
            await refreshDashboard();
            alert("تم حذف الملف من المكتبة ونقل النسخ المُدارة إلى trash عند الإمكان.");
        } else {
            alert(`فشل الحذف: ${data.error || "خطأ غير معروف"}`);
        }
    } catch (error) {
        alert(`خطأ أثناء الحذف: ${error}`);
    }
}

async function showDetails(fileId) {
    const modal = document.getElementById("details-modal");
    const content = document.getElementById("details-content");
    content.innerHTML = `<p class="text-gray-400">جاري تحميل التفاصيل...</p>`;
    modal.classList.remove("hidden");
    try {
        const response = await fetch(`${MASTER_URL}/api/files/${fileId}`);
        const data = await response.json();
        if (!response.ok) {
            content.innerHTML = `<p class="text-red-400">${escapeHtml(data.error || "فشل جلب تفاصيل الملف")}</p>`;
            return;
        }
        const locations = (data.locations || []).map((loc) => `
            <div class="bg-gray-800 border border-gray-700 rounded-lg p-3 space-y-1">
                <div><span class="text-gray-400">Node:</span> <span class="text-cyan-400">${escapeHtml(loc.node_id)}</span></div>
                <div><span class="text-gray-400">Host:</span> ${escapeHtml(loc.host)}:${escapeHtml(loc.port)}</div>
                <div><span class="text-gray-400">Type:</span> ${escapeHtml(loc.location_type)}</div>
                <div><span class="text-gray-400">Status:</span> ${escapeHtml(loc.node_status)}</div>
                <div class="text-xs text-gray-500 break-all">${escapeHtml(loc.path)}</div>
            </div>`).join("");
        content.innerHTML = `
            <div class="detail-row"><div class="detail-label">الاسم</div><div class="detail-value">${escapeHtml(data.file_name)}</div></div>
            <div class="detail-row"><div class="detail-label">النوع</div><div class="detail-value">${mediaTypeBadge(data.media_type)} <span class="text-gray-500 mr-2">${escapeHtml(data.mime_type)}</span></div></div>
            <div class="detail-row"><div class="detail-label">الحجم</div><div class="detail-value">${formatBytes(data.file_size)}</div></div>
            <div class="detail-row"><div class="detail-label">المالك</div><div class="detail-value">${escapeHtml(data.owner)}</div></div>
            <div class="detail-row"><div class="detail-label">تاريخ الإضافة</div><div class="detail-value">${escapeHtml(data.created_at || "غير متاح")}</div></div>
            <div class="detail-row"><div class="detail-label">الهاش</div><div class="detail-value font-mono text-xs">${escapeHtml(data.content_hash)}</div></div>
            <div class="detail-row"><div class="detail-label">التحميلات</div><div class="detail-value">${data.popularity_score || 0}</div></div>
            <div><div class="detail-label mb-2">المواقع</div><div class="space-y-2">${locations || '<p class="text-gray-500">لا توجد مواقع متاحة.</p>'}</div></div>`;
    } catch (error) {
        content.innerHTML = `<p class="text-red-400">خطأ أثناء جلب التفاصيل: ${escapeHtml(error)}</p>`;
    }
}

function closeDetailsModal() { document.getElementById("details-modal").classList.add("hidden"); }
document.getElementById("details-close-btn").addEventListener("click", closeDetailsModal);
document.getElementById("details-modal").addEventListener("click", (event) => { if (event.target.id === "details-modal") closeDetailsModal(); });

document.getElementById("upload-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const fileInput = document.getElementById("file-input");
    if (!fileInput.files.length) return;
    const formData = new FormData();
    formData.append("file", fileInput.files[0]);
    formData.append("owner", "Web_UI_User");
    formData.append("location_type", "CACHED");
    try {
        const response = await fetch(`${NODE_URL}/api/files/cache`, { method: "POST", body: formData });
        const data = await response.json().catch(() => ({}));
        if (response.ok) {
            alert(`تم رفع الملف بنجاح. النوع: ${data.media_type || "unknown"}`);
            fileInput.value = "";
            refreshDashboard();
        } else {
            alert(`فشل الرفع: ${data.error || "خطأ غير معروف"}`);
        }
    } catch (error) {
        alert(`فشل الاتصال بنود التخزين: ${error}`);
    }
});

function refreshDashboard() { fetchSystemStatus(); fetchFilesList(); }
refreshDashboard();
setInterval(refreshDashboard, 4000);
