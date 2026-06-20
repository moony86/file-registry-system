const MASTER_URL = window.location.origin;
const NODE_URL = "http://localhost:5001";
const ADMIN_TOKEN = "dev-token";

function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;").replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;").replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function escapeJsArg(value) {
    return String(value ?? "")
        .replaceAll("\\", "\\\\")
        .replaceAll("'", "\\'")
        .replaceAll("\n", " ");
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

function formatDuration(seconds) {
    seconds = Number(seconds || 0);
    if (!seconds) return "";
    const total = Math.round(seconds);
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const remainingSeconds = total % 60;
    if (hours) return `${hours}h ${minutes}m ${remainingSeconds}s`;
    return `${minutes}m ${remainingSeconds}s`;
}

function formatBitrate(bitsPerSecond) {
    bitsPerSecond = Number(bitsPerSecond || 0);
    if (!bitsPerSecond) return "";
    if (bitsPerSecond >= 1000000) return `${(bitsPerSecond / 1000000).toFixed(1)} Mbps`;
    if (bitsPerSecond >= 1000) return `${(bitsPerSecond / 1000).toFixed(1)} Kbps`;
    return `${bitsPerSecond} bps`;
}

async function fetchJsonOrThrow(url) {
    const response = await fetch(url);
    const contentType = response.headers.get("content-type") || "";
    if (!response.ok) {
        throw new Error(`HTTP ${response.status} for ${url}`);
    }
    if (!contentType.includes("application/json")) {
        throw new Error(`Expected JSON from ${url}, got ${contentType || "unknown content type"}`);
    }
    return response.json();
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

let currentView = 'active'; // 'active', 'deleted', 'media_review', or 'media_library'
let currentLibraryKind = 'movies';
let mediaCollections = [];
const draftSaveTimers = {};
let currentInspector = null;
let currentInspectorTab = "overview";

const MEDIA_KIND_OPTIONS = [
    "movie",
    "series_episode",
    "anime_episode",
    "youtube_video",
    "short",
    "course",
    "clip",
    "other_video",
    "unknown",
];

const COLLECTION_TYPE_OPTIONS = [
    "anime",
    "series",
    "movie_collection",
    "youtube_channel",
    "course",
    "clips",
    "unknown",
];

function optionList(options, selectedValue) {
    return options.map((value) => (
        `<option value="${escapeHtml(value)}" ${value === selectedValue ? "selected" : ""}>${escapeHtml(value)}</option>`
    )).join("");
}

function collectionOptions(selectedId = "") {
    const normalizedSelected = String(selectedId || "");
    const rows = [`<option value="" ${normalizedSelected === "" ? "selected" : ""}>No collection</option>`];
    for (const collection of mediaCollections) {
        const id = String(collection.collection_id);
        rows.push(`<option value="${escapeHtml(id)}" ${id === normalizedSelected ? "selected" : ""}>${escapeHtml(collection.title)} (${escapeHtml(collection.collection_type)})</option>`);
    }
    rows.push(`<option value="__new__" ${normalizedSelected === "__new__" ? "selected" : ""}>Create New</option>`);
    return rows.join("");
}

function draftFieldId(prefix, draftId) {
    return `${prefix}-${draftId}`;
}

function isEditingMediaDraft() {
    const active = document.activeElement;
    return Boolean(active && active.id && active.id.startsWith("draft-"));
}

async function fetchMediaCollections() {
    const data = await fetchJsonOrThrow(`${MASTER_URL}/api/media/collections`);
    mediaCollections = data.collections || [];
    return mediaCollections;
}

function renderViewControls() {
    const filesTable = document.getElementById("files-table-body");
    const table = filesTable ? filesTable.parentElement : null;
    if (!table) return;
    if (document.getElementById('view-controls')) return;
    const controlsHtml = `
        <div id="view-controls" class="mb-4 flex gap-2">
            <button id="btn-active" class="bg-gray-800 text-gray-200 px-3 py-1 rounded">الملفات النشطة</button>
            <button id="btn-deleted" class="bg-transparent text-gray-400 px-3 py-1 rounded border border-gray-700">سلة المحذوفات</button>
            <button id="btn-media-review" class="bg-transparent text-gray-400 px-3 py-1 rounded border border-gray-700">Media Review</button>
            <button id="btn-media-library" class="bg-transparent text-gray-400 px-3 py-1 rounded border border-gray-700">Media Library</button>
        </div>`;
    table.insertAdjacentHTML('beforebegin', controlsHtml);
    document.getElementById('btn-active').addEventListener('click', () => { currentView = 'active'; updateViewButtons(); refreshDashboard(); });
    document.getElementById('btn-deleted').addEventListener('click', () => { currentView = 'deleted'; updateViewButtons(); refreshDashboard(); });
    document.getElementById('btn-media-review').addEventListener('click', () => { currentView = 'media_review'; updateViewButtons(); refreshDashboard(); });
    document.getElementById('btn-media-library').addEventListener('click', () => { currentView = 'media_library'; updateViewButtons(); refreshDashboard(); });
}

function updateViewButtons() {
    const buttons = {
        active: document.getElementById('btn-active'),
        deleted: document.getElementById('btn-deleted'),
        media_review: document.getElementById('btn-media-review'),
        media_library: document.getElementById('btn-media-library'),
    };
    for (const [view, button] of Object.entries(buttons)) {
        if (!button) continue;
        button.className = view === currentView
            ? 'bg-gray-800 text-gray-200 px-3 py-1 rounded'
            : 'bg-transparent text-gray-400 px-3 py-1 rounded border border-gray-700';
    }
}

async function fetchDeletedFiles() {
    try {
        const response = await fetch(`${MASTER_URL}/api/files/deleted`);
        const data = await response.json();
        document.getElementById("total-files-count").innerText = data.count || 0;
        const filesTable = document.getElementById("files-table-body");
        filesTable.innerHTML = "";
        for (const file of data.files || []) {
            const nameDisplay = `<span class="text-gray-400">${escapeHtml(file.file_name)}</span>`;
            filesTable.innerHTML += `
                <tr class="hover:bg-gray-700/20 transition">
                    <td class="py-4 pr-2">${nameDisplay}</td>
                    <td class="py-4">${mediaTypeBadge(file.media_type)}</td>
                    <td class="py-4 text-gray-400">DELETED</td>
                    <td class="py-4 text-gray-400">unavailable</td>
                    <td class="py-4 text-gray-400 text-xs">${file.deleted_at ? escapeHtml(file.deleted_at) : ''}</td>
                    <td class="py-4 text-gray-400 text-xs">${file.deleted_by ? escapeHtml(file.deleted_by) : ''}</td>
                    <td class="py-4 font-mono text-xs text-yellow-500">${file.popularity_score || 0}</td>
                    <td class="py-4 text-center"><div class="flex justify-center gap-2">
                        <button onclick="showDetails('${file.file_id}')" class="action-btn action-btn-details">Details</button>
                    </div></td>
                </tr>`;
        }
    } catch (error) {
        console.error("فشل جلب المحذوفات:", error);
    }
}

async function fetchMediaDrafts() {
    const filesTable = document.getElementById("files-table-body");
    try {
        await fetchMediaCollections();
        const data = await fetchJsonOrThrow(`${MASTER_URL}/api/media/drafts`);
        document.getElementById("total-files-count").innerText = data.count || 0;
        filesTable.innerHTML = "";
        for (const draft of data.drafts || []) {
            const title = draft.user_title || draft.final_title || draft.suggested_title || draft.file_name;
            const kind = draft.user_media_kind || draft.final_media_kind || draft.suggested_media_kind || "unknown";
            filesTable.innerHTML += `
                <tr class="hover:bg-gray-700/20 transition">
                    <td class="py-4 pr-2">
                        <span class="text-gray-200">${escapeHtml(draft.file_name)}</span>
                    </td>
                    <td class="py-4">${mediaTypeBadge(draft.media_type)}</td>
                    <td class="py-4 text-gray-300">${escapeHtml(kind)}</td>
                    <td class="py-4 text-gray-400">pending review</td>
                    <td class="py-4 text-gray-400 text-xs">${escapeHtml(title)}</td>
                    <td class="py-4 text-gray-400 text-xs">${escapeHtml(draft.review_status)}</td>
                    <td class="py-4 font-mono text-xs text-yellow-500">${escapeHtml(draft.season_number || draft.season || "")}${draft.episode_number || draft.episode ? ` / E${escapeHtml(draft.episode_number || draft.episode)}` : ""}</td>
                    <td class="py-4 text-center"><div class="flex justify-center gap-2">
                        <button onclick="showDetails('${draft.file_id}')" class="action-btn action-btn-details">Details</button>
                    </div></td>
                </tr>`;
        }
    } catch (error) {
        console.error("Failed to fetch media drafts:", error);
        if (filesTable) {
            filesTable.innerHTML = `<tr><td colspan="8" class="py-4 text-red-400">Media Review API is not available. Restart Master Node and refresh.</td></tr>`;
        }
    }
}

function flattenLibraryItems(library, kind) {
    if (kind === "series" || kind === "anime") {
        return (library[kind] || []).flatMap((group) => {
            const seasons = group.seasons || {};
            return Object.entries(seasons).flatMap(([seasonNumber, episodes]) =>
                (episodes || []).map((episode) => ({
                    ...episode,
                    group_title: group.title,
                    group_season: seasonNumber,
                }))
            );
        });
    }
    return library[kind] || [];
}

async function fetchMediaLibrary() {
    const filesTable = document.getElementById("files-table-body");
    try {
        const library = await fetchJsonOrThrow(`${MASTER_URL}/api/media/library`);
        const kinds = ["movies", "series", "anime", "youtube", "shorts", "courses", "clips", "other"];
        const items = flattenLibraryItems(library, currentLibraryKind);
        document.getElementById("total-files-count").innerText = items.length || 0;

        const tabs = kinds.map((kind) => `
            <button onclick="setLibraryKind('${kind}')" class="${kind === currentLibraryKind ? 'bg-gray-700 text-white' : 'bg-transparent text-gray-400 border border-gray-700'} px-2 py-1 rounded text-xs">${kind}</button>
        `).join("");

        const rows = items.map((item) => {
            const seasonValue = item.season_number || item.season || item.group_season;
            const episodeValue = item.episode_number || item.episode;
            const seasonEpisode = seasonValue || episodeValue
                ? `S${seasonValue || ""}E${episodeValue || ""}`
                : "";
            const title = item.group_title || item.title;
            const availability = item.is_available ? "available" : "unavailable";
            const playButton = item.file_status === "ACTIVE" && item.is_available
                ? `<button onclick="playVideo('${item.file_id}')" class="bg-cyan-600 text-white px-3 py-1 rounded-lg text-xs font-semibold hover:bg-cyan-500 transition">Play</button>`
                : "";
            return `
                <tr class="hover:bg-gray-700/20 transition">
                    <td class="py-4 pr-2"><span class="text-gray-200">${escapeHtml(title)}</span></td>
                    <td class="py-4">${escapeHtml(item.media_kind)}</td>
                    <td class="py-4 text-gray-400">${escapeHtml(item.year || "")}</td>
                    <td class="py-4 text-gray-400">${escapeHtml(seasonEpisode)}</td>
                    <td class="py-4 text-gray-400 text-xs">${escapeHtml(item.file_name)}</td>
                    <td class="py-4">${escapeHtml(availability)}</td>
                    <td class="py-4 font-mono text-xs text-yellow-500">${escapeHtml(item.language || "")}</td>
                    <td class="py-4 text-center"><div class="flex justify-center gap-2">
                        ${playButton}
                        <button onclick="showDetails('${item.file_id}')" class="action-btn action-btn-details">Details</button>
                    </div></td>
                </tr>`;
        }).join("");

        filesTable.innerHTML = `
            <tr><td colspan="8" class="py-3"><div class="flex flex-wrap gap-2">${tabs}</div></td></tr>
            ${rows || '<tr><td colspan="8" class="py-4 text-gray-500">No approved media in this group.</td></tr>'}`;
    } catch (error) {
        console.error("Failed to fetch media library:", error);
        if (filesTable) {
            filesTable.innerHTML = `<tr><td colspan="8" class="py-4 text-red-400">Media Library API is not available. Restart Master Node and refresh.</td></tr>`;
        }
    }
}

function setLibraryKind(kind) {
    currentLibraryKind = kind;
    fetchMediaLibrary();
}

async function fetchFilesList() {
    try {
        const response = await fetch(`${MASTER_URL}/api/files`);
        const data = await response.json();
        document.getElementById("total-files-count").innerText = data.count || 0;
        const filesTable = document.getElementById("files-table-body");
        filesTable.innerHTML = "";
        for (const file of data.files || []) {
            const nameDisplay = `<span class="text-gray-200">${escapeHtml(file.file_name)}</span>`;
            const playButton = file.media_type === "video"
                ? `<button onclick="playVideo('${file.file_id}')" class="bg-cyan-600 text-white px-3 py-1 rounded-lg text-xs font-semibold hover:bg-cyan-500 transition">Play</button>`
                : "";
            filesTable.innerHTML += `
                <tr class="hover:bg-gray-700/30 transition">
                    <td class="py-4 pr-2">${nameDisplay}</td>
                    <td class="py-4">${mediaTypeBadge(file.media_type)}</td>
                    <td class="py-4 text-gray-400">${escapeHtml(file.file_status || "ACTIVE")}</td>
                    <td class="py-4">${file.is_available ? "available" : "unavailable"}</td>
                    <td class="py-4">${file.in_shared_space ? "shared" : "local/other"}</td>
                    <td class="py-4 text-gray-400 text-xs">${formatBytes(file.file_size)}</td>
                    <td class="py-4 font-mono text-xs text-yellow-500">${file.popularity_score || 0}</td>
                    <td class="py-4 text-center"><div class="flex justify-center gap-2">
                        ${playButton}
                        <button onclick="showDetails('${file.file_id}')" class="action-btn action-btn-details">Details</button>
                    </div></td>
                </tr>`;
        }
    } catch (error) {
        console.error("Failed to fetch files:", error);
    }
}
async function togglePin(fileId, isCurrentlyPinned, options = {}) {
    const shouldBeHot = isCurrentlyPinned ? 0 : 1;
    try {
        const response = await fetch(`${MASTER_URL}/api/files/${fileId}/hot`, {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-FSYS-Token": ADMIN_TOKEN },
            body: JSON.stringify({ is_hot: shouldBeHot }),
        });
        if (response.ok) {
            if (options.refresh !== false) await fetchFilesList();
            return true;
        }
        const data = await response.json().catch(() => ({}));
        alert(`HOT update failed: ${data.error || "check admin token"}`);
        return false;
    } catch (error) {
        console.error("HOT update failed:", error);
        return false;
    }
}
async function playVideo(fileId) {
    try {
        const response = await fetch(`${MASTER_URL}/api/files/${fileId}/location?access_type=stream_location`);
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            alert(`Cannot play video: ${data.error || "file is not available"}`);
            return;
        }
        if (data.media_type !== "video") {
            alert("Only video files can be played.");
            return;
        }

        const host = data.node && data.node.host;
        const port = data.node && data.node.port;
        if (!host || !port) {
            alert("Cannot play video: storage node location is missing.");
            return;
        }

        ensureVideoModal();
        const modal = document.getElementById("video-modal");
        const player = document.getElementById("video-player");
        const title = document.getElementById("video-title");
        title.innerText = data.file_name || "Video";
        await loadSubtitleTracks(player, fileId);
        player.src = `http://${host}:${port}/api/files/${fileId}/stream`;
        modal.classList.remove("hidden");
        player.play().catch(() => {});
    } catch (error) {
        alert(`Cannot play video: ${error}`);
    }
}

async function loadSubtitleTracks(player, fileId) {
    if (!player) return;
    player.querySelectorAll("track").forEach((track) => track.remove());
    try {
        const response = await fetch(`${MASTER_URL}/api/media/files/${fileId}/subtitles`);
        if (!response.ok) return;
        const data = await response.json().catch(() => ({}));
        const playable = (data.subtitles || []).filter((subtitle) =>
            subtitle.status === "active"
            && subtitle.subtitle_format !== "ass"
            && (subtitle.vtt_path || subtitle.subtitle_format === "vtt")
        );
        const hasDefault = playable.some((subtitle) => subtitle.is_default);
        playable.forEach((subtitle, index) => {
            const track = document.createElement("track");
            track.kind = "subtitles";
            track.src = `${MASTER_URL}/api/media/subtitles/${subtitle.subtitle_id}/file`;
            track.srclang = subtitle.language || "unknown";
            track.label = subtitle.label || subtitle.language || "Subtitle";
            if (subtitle.is_default || (!hasDefault && index === 0)) {
                track.default = true;
            }
            player.appendChild(track);
        });
    } catch (error) {
        console.warn("Failed to load subtitles:", error);
    }
}

function ensureVideoModal() {
    if (document.getElementById("video-modal")) return;

    document.body.insertAdjacentHTML("beforeend", `
        <div id="video-modal" class="hidden fixed inset-0 z-50 bg-black/80 p-4">
            <div class="max-w-5xl mx-auto mt-10 bg-gray-950 border border-gray-700 rounded-xl shadow-2xl overflow-hidden">
                <div class="flex items-center justify-between px-5 py-4 border-b border-gray-700 bg-gray-900">
                    <h3 id="video-title" class="font-bold text-gray-100">Video</h3>
                    <button id="video-close-btn" class="text-gray-400 hover:text-white text-xl">x</button>
                </div>
                <video id="video-player" class="w-full bg-black max-h-[75vh]" controls autoplay></video>
            </div>
        </div>
    `);
    bindVideoModalEvents();
}

function bindVideoModalEvents() {
    const closeButton = document.getElementById("video-close-btn");
    const modal = document.getElementById("video-modal");
    if (closeButton && !closeButton.dataset.bound) {
        closeButton.addEventListener("click", closeVideoModal);
        closeButton.dataset.bound = "true";
    }
    if (modal && !modal.dataset.bound) {
        modal.addEventListener("click", (event) => { if (event.target.id === "video-modal") closeVideoModal(); });
        modal.dataset.bound = "true";
    }
}

function closeVideoModal() {
    const modal = document.getElementById("video-modal");
    const player = document.getElementById("video-player");
    if (!modal || !player) return;
    player.pause();
    player.querySelectorAll("track").forEach((track) => track.remove());
    player.removeAttribute("src");
    player.load();
    modal.classList.add("hidden");
}

function readOptionalInt(elementId) {
    const element = document.getElementById(elementId);
    if (!element || element.value === "") return null;
    const value = Number(element.value);
    return Number.isFinite(value) ? value : null;
}

function collectMediaDraftPayload(draftId) {
    const collectionId = readOptionalInt(`draft-collection-${draftId}`);
    const collectionTitle = document.getElementById(`draft-new-collection-${draftId}`)?.value.trim();
    const episodeNumber = readOptionalInt(`draft-episode-${draftId}`);
    return {
        media_kind: document.getElementById(`draft-kind-${draftId}`)?.value || "unknown",
        final_media_kind: document.getElementById(`draft-kind-${draftId}`)?.value || "unknown",
        final_title: document.getElementById(`draft-title-${draftId}`)?.value.trim(),
        collection_id: collectionId,
        collection_title: collectionId ? "" : collectionTitle,
        collection_type: document.getElementById(`draft-collection-type-${draftId}`)?.value || "unknown",
        season_number: readOptionalInt(`draft-season-${draftId}`),
        episode_number: episodeNumber,
        display_order: episodeNumber,
        language: "",
        reviewed_by: "dashboard-dev",
    };
}

function setDraftSaveStatus(draftId, message, isError = false) {
    const status = document.getElementById(`draft-save-status-${draftId}`);
    if (!status) return;
    status.innerText = message;
    status.className = isError ? "text-[11px] text-red-400 mt-1" : "text-[11px] text-green-400 mt-1";
}

function saveMediaDraftDebounced(draftId) {
    setDraftSaveStatus(draftId, "Saving...");
    clearTimeout(draftSaveTimers[draftId]);
    draftSaveTimers[draftId] = setTimeout(() => saveMediaDraft(draftId, { silent: true }), 600);
}

async function saveMediaDraft(draftId, options = {}) {
    const payload = collectMediaDraftPayload(draftId);
    if (!payload.final_title) {
        setDraftSaveStatus(draftId, "Title is required", true);
        return null;
    }

    try {
        const response = await fetch(`${MASTER_URL}/api/media/drafts/${draftId}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            const message = data.error || "unknown error";
            setDraftSaveStatus(draftId, `Save failed: ${message}`, true);
            if (!options.silent) alert(`Save failed: ${message}`);
            return null;
        }
        if (data.draft && data.draft.collection_id) {
            const collectionSelect = document.getElementById(`draft-collection-${draftId}`);
            await fetchMediaCollections();
            if (collectionSelect && !collectionSelect.value) {
                collectionSelect.innerHTML = collectionOptions(data.draft.collection_id);
                document.getElementById(`draft-new-collection-${draftId}`).value = "";
            }
        }
        setDraftSaveStatus(draftId, "Changes Saved");
        return data.draft || {};
    } catch (error) {
        setDraftSaveStatus(draftId, `Save failed: ${error.message || error}`, true);
        if (!options.silent) alert(`Save failed: ${error.message || error}`);
        return null;
    }
}

async function approveMediaDraft(draftId) {
    const savedDraft = await saveMediaDraft(draftId);
    if (!savedDraft) return;
    const payload = collectMediaDraftPayload(draftId);

    try {
        const response = await fetch(`${MASTER_URL}/api/media/drafts/${draftId}/approve`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            alert(`Approve failed: ${data.error || "unknown error"}`);
            return;
        }
        await fetchMediaDrafts();
    } catch (error) {
        alert(`Approve failed: ${error}`);
    }
}

async function rejectMediaDraft(draftId, options = {}) {
    const reason = options.reason !== undefined ? options.reason : prompt("Reject reason", "");
    if (reason === null) return false;

    try {
        const response = await fetch(`${MASTER_URL}/api/media/drafts/${draftId}/reject`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ reviewed_by: "dashboard-dev", reason }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            alert(`Reject failed: ${data.error || "unknown error"}`);
            return false;
        }
        if (options.refresh !== false) await fetchMediaDrafts();
        return true;
    } catch (error) {
        alert(`Reject failed: ${error}`);
        return false;
    }
}
async function deleteFile(fileId, options = {}) {
    const confirmed = options.confirmed === true || confirm("Delete this file from the active library and move managed shared-space copies to trash when possible?");
    if (!confirmed) return false;

    try {
        const response = await fetch(`${MASTER_URL}/api/files/${fileId}`, {
            method: "DELETE",
            headers: { "Content-Type": "application/json", "X-FSYS-Token": ADMIN_TOKEN },
            body: JSON.stringify({ deleted_by: "dashboard-dev" }),
        });
        const data = await response.json().catch(() => ({}));
        if (response.ok) {
            if (options.refresh !== false) {
                closeDetailsModal();
                await refreshDashboard();
                alert("File deleted from active library. Managed copies were moved to trash where possible.");
            }
            return true;
        }
        alert(`Delete failed: ${data.error || "unknown error"}`);
        return false;
    } catch (error) {
        alert(`Delete failed: ${error}`);
        return false;
    }
}
async function restoreFile(fileId, options = {}) {
    const confirmed = options.confirmed === true || confirm("Restore this file to ACTIVE and restore managed copies from trash when possible?");
    if (!confirmed) return false;

    try {
        const response = await fetch(`${MASTER_URL}/api/files/${fileId}/restore`, {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-FSYS-Token": ADMIN_TOKEN },
        });
        const data = await response.json().catch(() => ({}));
        if (response.ok && !data.reactivated) {
            const reason = data.error || `reactivated=${Boolean(data.reactivated)}, successful_nodes=${data.successful_nodes || 0}`;
            alert(`Restore did not complete: ${reason}`);
            if (options.refresh !== false) await refreshDashboard();
            return false;
        }
        if (response.ok) {
            if (options.refresh !== false) {
                closeDetailsModal();
                await refreshDashboard();
                alert("File restored to ACTIVE.");
            }
            return true;
        }
        alert(`Restore failed: ${data.error || "unknown error"}`);
        return false;
    } catch (error) {
        alert(`Restore failed: ${error}`);
        return false;
    }
}
async function showDetails(fileId) {
    const modal = document.getElementById("details-modal");
    const content = document.getElementById("details-content");
    content.innerHTML = `<p class="text-gray-400">Loading file inspector...</p>`;
    modal.classList.remove("hidden");
    try {
        const [fileResponse, mediaResponse, subtitlesResponse] = await Promise.all([
            fetch(`${MASTER_URL}/api/files/${fileId}`),
            fetch(`${MASTER_URL}/api/media/files/${fileId}`),
            fetch(`${MASTER_URL}/api/media/files/${fileId}/subtitles`),
        ]);
        const file = await fileResponse.json().catch(() => ({}));
        const media = await mediaResponse.json().catch(() => ({}));
        const subtitles = await subtitlesResponse.json().catch(() => ({ subtitles: [] }));
        if (!fileResponse.ok) {
            content.innerHTML = `<p class="text-red-400">${escapeHtml(file.error || "Failed to load file details")}</p>`;
            return;
        }
        if (!mediaResponse.ok) {
            media.error = media.error || "Failed to load media details";
        }
        currentInspector = { file, media, subtitles: subtitles.subtitles || [] };
        currentInspectorTab = "overview";
        renderFileInspector();
    } catch (error) {
        content.innerHTML = `<p class="text-red-400">Failed to load file inspector: ${escapeHtml(error.message || error)}</p>`;
    }
}

function inspectorTabButton(id, label) {
    const active = currentInspectorTab === id;
    return `<button onclick="setInspectorTab('${id}')" class="${active ? "bg-cyan-700 text-white" : "bg-gray-800 text-gray-300 border border-gray-700"} px-3 py-1 rounded text-xs font-semibold">${label}</button>`;
}

function setInspectorTab(tab) {
    currentInspectorTab = tab;
    renderFileInspector();
}

function renderFileInspector() {
    if (!currentInspector) return;
    const content = document.getElementById("details-content");
    const file = currentInspector.file;
    const body = {
        overview: renderOverviewTab,
        media: renderMediaTab,
        actions: renderActionsTab,
        locations: renderLocationsTab,
        subtitles: renderSubtitlesTab,
        debug: renderDebugTab,
    }[currentInspectorTab]();

    content.innerHTML = `
        <div class="space-y-4">
            <div class="flex flex-wrap gap-2 border-b border-gray-800 pb-3">
                ${inspectorTabButton("overview", "Overview")}
                ${inspectorTabButton("media", "Media")}
                ${file.media_type === "video" ? inspectorTabButton("subtitles", "Subtitles") : ""}
                ${inspectorTabButton("actions", "Actions")}
                ${inspectorTabButton("locations", "Locations")}
                ${inspectorTabButton("debug", "Debug")}
            </div>
            <div class="flex items-start justify-between gap-4">
                <div>
                    <h4 class="text-lg font-bold text-gray-100">${escapeHtml(file.file_name)}</h4>
                    <p class="text-xs text-gray-500 font-mono">${escapeHtml(file.file_id)}</p>
                </div>
                <span class="text-xs px-2 py-1 rounded bg-gray-800 text-gray-300">${escapeHtml(file.file_status || "ACTIVE")}</span>
            </div>
            ${body}
        </div>`;
}

function renderOverviewTab() {
    const file = currentInspector.file;
    const hash = file.content_hash || "";
    const technical = file.technical_metadata;
    const thumbnail = file.thumbnail;
    const thumbnailPreview = file.media_type === "video" ? `
            <div class="pt-3 border-t border-gray-800">
                <div class="text-sm font-semibold text-gray-200 mb-2">Thumbnail Preview</div>
                <div class="max-w-sm bg-gray-950 border border-gray-800 overflow-hidden">
                    <img src="${MASTER_URL}/api/files/${encodeURIComponent(file.file_id)}/thumbnail" alt="" class="w-full aspect-video object-cover">
                </div>
                <div class="mt-2 text-xs text-gray-500">Status: ${escapeHtml(thumbnail?.thumbnail_status || "placeholder")}</div>
                <button disabled class="mt-2 bg-gray-900 text-gray-600 border border-gray-800 px-3 py-1 rounded text-xs font-semibold">Regenerate Thumbnail planned</button>
            </div>
        ` : "";
    const technicalRows = technical ? `
            <div class="pt-3 border-t border-gray-800 text-sm font-semibold text-gray-200">Technical Metadata</div>
            ${detailRow("Probe status", technical.probe_status || "unknown")}
            ${detailRow("Duration", formatDuration(technical.duration_seconds) || "")}
            ${detailRow("Resolution", technical.width && technical.height ? `${technical.width}x${technical.height}` : "")}
            ${detailRow("Video", technical.video_codec || "")}
            ${detailRow("Audio", [technical.audio_codec, technical.audio_channels ? `${technical.audio_channels} ch` : ""].filter(Boolean).join(" "))}
            ${detailRow("FPS", technical.fps ? Number(technical.fps).toFixed(3) : "")}
            ${detailRow("Bitrate", formatBitrate(technical.bitrate))}
            ${detailRow("Format", technical.format_name || "")}
            ${technical.probe_error ? detailRow("Probe error", technical.probe_error) : ""}
        ` : "";
    return `
        <section class="space-y-3">
            ${detailRow("File name", file.file_name)}
            ${detailRow("File ID", file.file_id)}
            ${detailRow("Owner", file.owner)}
            ${detailRow("Size", formatBytes(file.file_size))}
            ${detailRow("MIME type", file.mime_type)}
            ${detailRow("Media type", file.media_type)}
            ${detailRow("Status", file.file_status || "ACTIVE")}
            ${detailRow("Created at", file.created_at || "")}
            ${detailRow("Content hash", hash)}
            ${detailRow("Popularity", file.popularity_score || 0)}
            ${thumbnailPreview}
            ${technicalRows}
        </section>`;
}

function mediaContextValues() {
    const media = currentInspector.media || {};
    const draft = media.draft;
    const item = media.item;
    if (item) {
        return {
            mode: "item",
            id: item.media_id,
            kind: item.media_kind || "unknown",
            title: item.title || "",
            collectionId: item.collection_id || "",
            collectionTitle: item.collection_title || "",
            collectionType: item.collection_type || "unknown",
            season: item.season_number || item.season || "",
            episode: item.episode_number || item.episode || "",
            year: item.year || "",
            language: item.language || "",
            reviewStatus: "approved",
        };
    }
    if (draft) {
        const kind = draft.user_media_kind || draft.final_media_kind || draft.suggested_media_kind || "unknown";
        const hasDraftCollectionTitle = !draft.collection_id && (draft.collection_title || draft.saved_collection_title);
        return {
            mode: "draft",
            id: draft.draft_id,
            kind,
            title: draft.user_title || draft.final_title || draft.suggested_title || currentInspector.file.file_name || "",
            collectionId: draft.collection_id || (hasDraftCollectionTitle ? "__new__" : ""),
            collectionTitle: draft.collection_title || draft.saved_collection_title || "",
            collectionType: draft.collection_type || draft.saved_collection_type || (kind === "anime_episode" ? "anime" : kind === "series_episode" ? "series" : "unknown"),
            season: draft.season_number || draft.season || 1,
            episode: draft.episode_number || draft.episode || "",
            year: draft.year || "",
            language: draft.language || "",
            reviewStatus: draft.review_status || "pending",
        };
    }
    return null;
}

function renderMediaTab() {
    const file = currentInspector.file;
    const media = currentInspector.media || {};
    if (file.media_type !== "video") {
        return `<p class="text-gray-500 border border-gray-800 rounded p-4">No media metadata for this file.</p>`;
    }
    const values = mediaContextValues();
    if (!values) {
        return `<p class="text-gray-500 border border-gray-800 rounded p-4">No media draft or approved item found for this video.</p>`;
    }
    mediaCollections = media.collections || mediaCollections;
    const currentCollectionText = values.collectionId && values.collectionId !== "__new__"
        ? `${values.collectionTitle || "Selected collection"} (${values.collectionType || "unknown"})`
        : values.collectionTitle
            ? `${values.collectionTitle} (${values.collectionType || "unknown"})`
            : "None";
    const showNewCollection = values.collectionId === "__new__";
    const canReviewDraft = values.mode === "draft" && values.reviewStatus === "pending";
    const saveLabel = canReviewDraft ? "Save Draft" : "Save Changes";
    const canDeleteCollection = values.collectionId && values.collectionId !== "__new__";
    return `
        <section class="space-y-4">
            <div class="text-xs text-gray-400">Mode: <span class="text-cyan-300">${escapeHtml(values.mode)}</span> | Review status: ${escapeHtml(values.reviewStatus)}</div>
            <div class="text-xs text-gray-400">Current Collection: <span class="text-cyan-300">${escapeHtml(currentCollectionText)}</span></div>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
                ${fieldSelect("inspector-media-kind", "Media Kind", MEDIA_KIND_OPTIONS, values.kind)}
                ${fieldInput("inspector-title", "Title", values.title)}
                ${fieldSelectHtml("inspector-collection", "Collection", collectionOptions(values.collectionId), "handleInspectorCollectionChange()")}
                <div id="inspector-new-collection-wrap" class="${showNewCollection ? "" : "hidden"}">
                    ${fieldInput("inspector-new-collection", "New Collection Title", values.collectionTitle)}
                </div>
                ${fieldSelect("inspector-collection-type", "Collection Type", COLLECTION_TYPE_OPTIONS, values.collectionType)}
                ${fieldInput("inspector-season", "Season", values.season, "number")}
                ${fieldInput("inspector-episode", "Episode", values.episode, "number")}
                ${fieldInput("inspector-year", "Year", values.year, "number")}
                ${fieldInput("inspector-language", "Language", values.language)}
            </div>
            <div id="inspector-media-status" class="text-xs text-gray-500"></div>
            <div class="flex flex-wrap gap-2">
                <button onclick="saveMediaChanges()" class="bg-cyan-700 text-white px-3 py-1 rounded text-xs font-semibold">${saveLabel}</button>
                ${canReviewDraft ? `<button onclick="approveDraftFromInspector()" class="bg-green-700 text-white px-3 py-1 rounded text-xs font-semibold">Approve</button><button onclick="rejectDraftFromInspector()" class="bg-red-900/40 text-red-200 border border-red-700/50 px-3 py-1 rounded text-xs font-semibold">Reject</button>` : ""}
                ${canDeleteCollection ? `<button onclick="deleteSelectedCollection()" class="bg-gray-800 text-red-200 border border-red-800 px-3 py-1 rounded text-xs font-semibold">Delete Collection</button>` : ""}
            </div>
        </section>`;
}

function renderSubtitlesTab() {
    const file = currentInspector.file;
    if (file.media_type !== "video") {
        return `<p class="text-gray-500 border border-gray-800 rounded p-4">Subtitles are available for video files only.</p>`;
    }

    const subtitles = currentInspector.subtitles || [];
    const rows = subtitles.length ? subtitles.map((subtitle) => {
        const playable = subtitle.subtitle_format !== "ass" && (subtitle.vtt_path || subtitle.subtitle_format === "vtt");
        return `
            <tr class="border-b border-gray-800 text-sm">
                <td class="py-2 text-gray-200">${escapeHtml(subtitle.label || "Subtitle")}</td>
                <td class="py-2 text-gray-400">${escapeHtml(subtitle.language || "unknown")}</td>
                <td class="py-2 text-gray-400">${escapeHtml(subtitle.subtitle_format || "unknown")}</td>
                <td class="py-2 text-gray-400">${subtitle.is_default ? "yes" : ""}</td>
                <td class="py-2 text-gray-400">${playable ? "player" : "stored only"}</td>
                <td class="py-2">
                    <div class="flex flex-wrap gap-2">
                        ${subtitle.is_default ? "" : `<button onclick="setDefaultSubtitle(${subtitle.subtitle_id})" class="bg-cyan-900/40 text-cyan-200 border border-cyan-800 px-2 py-1 rounded text-xs">Set Default</button>`}
                        <button onclick="deleteSubtitle(${subtitle.subtitle_id})" class="bg-red-900/40 text-red-200 border border-red-800 px-2 py-1 rounded text-xs">Delete</button>
                    </div>
                </td>
            </tr>`;
    }).join("") : `<tr><td colspan="6" class="py-4 text-gray-500">No subtitles yet.</td></tr>`;

    return `
        <section class="space-y-4">
            <div class="overflow-x-auto">
                <table class="w-full text-left">
                    <thead class="text-xs text-gray-500">
                        <tr>
                            <th class="py-2">Label</th>
                            <th class="py-2">Language</th>
                            <th class="py-2">Format</th>
                            <th class="py-2">Default</th>
                            <th class="py-2">Playback</th>
                            <th class="py-2">Actions</th>
                        </tr>
                    </thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>
            <div class="border border-gray-800 rounded p-3 space-y-3">
                <div class="text-sm font-semibold text-gray-200">Upload Subtitle</div>
                <input id="subtitle-file-input" type="file" accept=".srt,.vtt,.ass" class="block w-full text-xs text-gray-400 file:mr-4 file:py-2 file:px-4 file:rounded file:border-0 file:text-xs file:font-semibold file:bg-cyan-700 file:text-white">
                <div class="grid grid-cols-1 md:grid-cols-3 gap-3">
                    <label class="block text-xs text-gray-400">Language
                        <select id="subtitle-language" class="mt-1 w-full bg-gray-950 border border-gray-700 rounded px-2 py-1 text-gray-100">
                            <option value="ar">Arabic</option>
                            <option value="en">English</option>
                            <option value="ja">Japanese</option>
                            <option value="unknown">Unknown</option>
                        </select>
                    </label>
                    ${fieldInput("subtitle-label", "Label", "Arabic")}
                    <label class="flex items-end gap-2 text-xs text-gray-400 pb-2">
                        <input id="subtitle-default" type="checkbox" class="accent-cyan-600">
                        Default
                    </label>
                </div>
                <div id="subtitle-status" class="text-xs text-gray-500"></div>
                <button onclick="uploadSubtitle()" class="bg-cyan-700 text-white px-3 py-1 rounded text-xs font-semibold">Upload Subtitle</button>
            </div>
        </section>`;
}

function renderActionsTab() {
    const file = currentInspector.file;
    const isActive = (file.file_status || "ACTIVE") === "ACTIVE";
    const isDeleted = file.file_status === "DELETED";
    const isHot = file.is_hot === 1;
    return `
        <section class="space-y-3">
            <div class="flex flex-wrap gap-2">
                ${file.media_type === "video" && isActive ? `<button onclick="playVideo('${file.file_id}')" class="bg-cyan-700 text-white px-3 py-1 rounded text-xs font-semibold">Play</button>` : ""}
                <button onclick="toggleHotFromInspector()" class="bg-gray-700 text-white px-3 py-1 rounded text-xs font-semibold">${isHot ? "Unset HOT" : "Set HOT"}</button>
                ${isActive ? `<button onclick="deleteFromInspector()" class="bg-red-900/50 text-red-200 border border-red-700/50 px-3 py-1 rounded text-xs font-semibold">Delete</button>` : ""}
                ${isDeleted ? `<button onclick="restoreFromInspector()" class="bg-green-700 text-white px-3 py-1 rounded text-xs font-semibold">Restore</button>` : ""}
                <button disabled class="bg-gray-900 text-gray-600 border border-gray-800 px-3 py-1 rounded text-xs font-semibold">Purge planned</button>
            </div>
            <p class="text-xs text-gray-500">Dangerous actions require confirmation and refresh the current view after completion.</p>
        </section>`;
}

function renderLocationsTab() {
    const locations = currentInspector.file.locations || [];
    if (!locations.length) return `<p class="text-gray-500">No locations available.</p>`;
    return `<section class="space-y-2">${locations.map((loc) => `
        <div class="bg-gray-900 border border-gray-800 rounded p-3 text-sm space-y-1">
            <div><span class="text-gray-500">Node:</span> <span class="text-cyan-300">${escapeHtml(loc.node_id)}</span></div>
            <div><span class="text-gray-500">Host:</span> ${escapeHtml(loc.host)}:${escapeHtml(loc.port)}</div>
            <div><span class="text-gray-500">Type:</span> ${escapeHtml(loc.location_type)} | <span class="text-gray-500">Status:</span> ${escapeHtml(loc.node_status)}</div>
            <div><span class="text-gray-500">Primary:</span> ${escapeHtml(loc.is_primary)}</div>
            <div><span class="text-gray-500">Last seen:</span> ${escapeHtml(loc.last_seen || "")}</div>
            <div class="text-xs text-gray-500 break-all">${escapeHtml(loc.path)}</div>
        </div>`).join("")}</section>`;
}

function renderDebugTab() {
    const endpoints = [
        `/api/files/${currentInspector.file.file_id}`,
        `/api/media/files/${currentInspector.file.file_id}`,
        `/api/files/${currentInspector.file.file_id}/location`,
    ];
    return `
        <section class="space-y-3">
            <div class="text-xs text-gray-400">Endpoints used: ${endpoints.map(escapeHtml).join(" | ")}</div>
            <pre class="bg-black/40 border border-gray-800 rounded p-3 text-xs overflow-auto max-h-96">${escapeHtml(JSON.stringify(currentInspector, null, 2))}</pre>
        </section>`;
}

function detailRow(label, value) {
    return `<div class="detail-row"><div class="detail-label">${escapeHtml(label)}</div><div class="detail-value">${escapeHtml(value ?? "")}</div></div>`;
}

function fieldInput(id, label, value, type = "text") {
    return `<label class="block text-xs text-gray-400">${escapeHtml(label)}<input id="${id}" type="${type}" value="${escapeHtml(value ?? "")}" class="mt-1 w-full bg-gray-950 border border-gray-700 rounded px-2 py-1 text-gray-100"></label>`;
}

function fieldSelect(id, label, options, selectedValue) {
    return fieldSelectHtml(id, label, optionList(options, selectedValue));
}

function fieldSelectHtml(id, label, optionsHtml, onchange = "") {
    const changeAttr = onchange ? ` onchange="${escapeHtml(onchange)}"` : "";
    return `<label class="block text-xs text-gray-400">${escapeHtml(label)}<select id="${id}"${changeAttr} class="mt-1 w-full bg-gray-950 border border-gray-700 rounded px-2 py-1 text-gray-100">${optionsHtml}</select></label>`;
}

function handleInspectorCollectionChange() {
    const select = document.getElementById("inspector-collection");
    const wrap = document.getElementById("inspector-new-collection-wrap");
    const input = document.getElementById("inspector-new-collection");
    if (!select || !wrap) return;
    const isNew = select.value === "__new__";
    wrap.classList.toggle("hidden", !isNew);
    if (!isNew && input) input.value = "";
}
window.handleInspectorCollectionChange = handleInspectorCollectionChange;

function collectInspectorMediaPayload() {
    const collectionValue = document.getElementById("inspector-collection")?.value || "";
    const createNewCollection = collectionValue === "__new__";
    const collectionId = createNewCollection ? null : readOptionalInt("inspector-collection");
    const episodeNumber = readOptionalInt("inspector-episode");
    return {
        media_kind: document.getElementById("inspector-media-kind")?.value || "unknown",
        final_media_kind: document.getElementById("inspector-media-kind")?.value || "unknown",
        title: document.getElementById("inspector-title")?.value.trim(),
        final_title: document.getElementById("inspector-title")?.value.trim(),
        collection_id: collectionId,
        collection_title: createNewCollection ? document.getElementById("inspector-new-collection")?.value.trim() : "",
        collection_type: document.getElementById("inspector-collection-type")?.value || "unknown",
        season_number: readOptionalInt("inspector-season"),
        episode_number: episodeNumber,
        display_order: episodeNumber,
        year: readOptionalInt("inspector-year"),
        language: document.getElementById("inspector-language")?.value.trim(),
        reviewed_by: "dashboard-dev",
    };
}

function setInspectorMediaStatus(message, isError = false) {
    const el = document.getElementById("inspector-media-status");
    if (!el) return;
    el.innerText = message;
    el.className = isError ? "text-xs text-red-400" : "text-xs text-green-400";
}

function setSubtitleStatus(message, isError = false) {
    const el = document.getElementById("subtitle-status");
    if (!el) return;
    el.innerText = message;
    el.className = isError ? "text-xs text-red-400" : "text-xs text-green-400";
}

async function saveMediaChanges() {
    const values = mediaContextValues();
    if (!values) return;
    const payload = collectInspectorMediaPayload();
    if (!payload.title) {
        setInspectorMediaStatus("Title is required", true);
        return;
    }
    try {
        const url = values.mode === "draft"
            ? `${MASTER_URL}/api/media/drafts/${values.id}`
            : `${MASTER_URL}/api/media/files/${currentInspector.file.file_id}`;
        const response = await fetch(url, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            setInspectorMediaStatus(`Save failed: ${data.error || "unknown error"}`, true);
            return;
        }
        await refreshInspectorData();
        setInspectorMediaStatus("Changes Saved");
    } catch (error) {
        setInspectorMediaStatus(`Save failed: ${error.message || error}`, true);
    }
}

async function uploadSubtitle() {
    if (!currentInspector?.file?.file_id) return;
    const input = document.getElementById("subtitle-file-input");
    if (!input?.files?.length) {
        setSubtitleStatus("Choose a subtitle file first.", true);
        return;
    }

    const formData = new FormData();
    formData.append("file", input.files[0]);
    formData.append("language", document.getElementById("subtitle-language")?.value || "unknown");
    formData.append("label", document.getElementById("subtitle-label")?.value.trim() || "Subtitle");
    formData.append("is_default", document.getElementById("subtitle-default")?.checked ? "true" : "false");

    try {
        setSubtitleStatus("Uploading subtitle...");
        const response = await fetch(`${MASTER_URL}/api/media/files/${currentInspector.file.file_id}/subtitles`, {
            method: "POST",
            body: formData,
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            setSubtitleStatus(data.error || "Subtitle upload failed.", true);
            return;
        }
        await refreshInspectorData();
        currentInspectorTab = "subtitles";
        renderFileInspector();
        setSubtitleStatus(data.warning || "Subtitle uploaded.");
    } catch (error) {
        setSubtitleStatus(`Subtitle upload failed: ${error.message || error}`, true);
    }
}

async function setDefaultSubtitle(subtitleId) {
    try {
        const response = await fetch(`${MASTER_URL}/api/media/subtitles/${subtitleId}/default`, {
            method: "PATCH",
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            setSubtitleStatus(data.error || "Could not set default subtitle.", true);
            return;
        }
        await refreshInspectorData();
        currentInspectorTab = "subtitles";
        renderFileInspector();
    } catch (error) {
        setSubtitleStatus(`Could not set default subtitle: ${error.message || error}`, true);
    }
}

async function deleteSubtitle(subtitleId) {
    if (!confirm("Delete this subtitle from the player? The file is kept on disk for now.")) return;
    try {
        const response = await fetch(`${MASTER_URL}/api/media/subtitles/${subtitleId}`, {
            method: "DELETE",
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            setSubtitleStatus(data.error || "Could not delete subtitle.", true);
            return;
        }
        await refreshInspectorData();
        currentInspectorTab = "subtitles";
        renderFileInspector();
    } catch (error) {
        setSubtitleStatus(`Could not delete subtitle: ${error.message || error}`, true);
    }
}

async function deleteSelectedCollection() {
    const select = document.getElementById("inspector-collection");
    const collectionId = readOptionalInt("inspector-collection");
    if (!select || !collectionId) {
        setInspectorMediaStatus("Select an existing collection first.", true);
        return;
    }

    const label = select.selectedOptions?.[0]?.textContent || `collection ${collectionId}`;
    if (!confirm(`Delete collection "${label}"? Only empty collections can be deleted.`)) return;

    try {
        const response = await fetch(`${MASTER_URL}/api/media/collections/${collectionId}`, {
            method: "DELETE",
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            setInspectorMediaStatus(data.message || data.error || "Collection could not be deleted.", true);
            return;
        }

        mediaCollections = (mediaCollections || []).filter((collection) => Number(collection.collection_id) !== collectionId);
        setInspectorMediaStatus("Collection deleted.");
        await refreshInspectorData();
        await refreshDashboard();
    } catch (error) {
        setInspectorMediaStatus(`Delete collection failed: ${error.message || error}`, true);
    }
}

async function approveDraftFromInspector() {
    const values = mediaContextValues();
    if (!values || values.mode !== "draft") return;
    await saveMediaChanges();
    const payload = collectInspectorMediaPayload();
    try {
        const response = await fetch(`${MASTER_URL}/api/media/drafts/${values.id}/approve`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            setInspectorMediaStatus(`Approve failed: ${data.error || "unknown error"}`, true);
            return;
        }
        setInspectorMediaStatus("Approved");
        await refreshInspectorData();
        await refreshDashboard();
    } catch (error) {
        setInspectorMediaStatus(`Approve failed: ${error.message || error}`, true);
    }
}

async function rejectDraftFromInspector() {
    const values = mediaContextValues();
    if (!values || values.mode !== "draft") return;
    const reason = prompt("Reject reason", "");
    if (reason === null) return;
    await rejectMediaDraft(values.id, { reason, refresh: false });
    await refreshInspectorData();
    await refreshDashboard();
}

async function refreshInspectorData() {
    if (!currentInspector?.file?.file_id) return;
    const [file, media, subtitles] = await Promise.all([
        fetchJsonOrThrow(`${MASTER_URL}/api/files/${currentInspector.file.file_id}`),
        fetchJsonOrThrow(`${MASTER_URL}/api/media/files/${currentInspector.file.file_id}`),
        fetchJsonOrThrow(`${MASTER_URL}/api/media/files/${currentInspector.file.file_id}/subtitles`),
    ]);
    currentInspector = { file, media, subtitles: subtitles.subtitles || [] };
    renderFileInspector();
}

async function toggleHotFromInspector() {
    await togglePin(currentInspector.file.file_id, currentInspector.file.is_hot === 1, { refresh: false });
    await refreshInspectorData();
    await refreshDashboard();
}

async function deleteFromInspector() {
    await deleteFile(currentInspector.file.file_id, { refresh: false });
    closeDetailsModal();
    await refreshDashboard();
}

async function restoreFromInspector() {
    await restoreFile(currentInspector.file.file_id, { refresh: false });
    closeDetailsModal();
    await refreshDashboard();
}

function closeDetailsModal() { document.getElementById("details-modal").classList.add("hidden"); }
document.getElementById("details-close-btn").addEventListener("click", closeDetailsModal);
document.getElementById("details-modal").addEventListener("click", (event) => { if (event.target.id === "details-modal") closeDetailsModal(); });
bindVideoModalEvents();

function setUploadState(message, busy = false) {
    const status = document.getElementById("upload-status");
    const fileInput = document.getElementById("file-input");
    const submitButton = document.querySelector("#upload-form button[type='submit']");
    if (status && message !== null) status.innerText = message || "";
    if (fileInput) fileInput.disabled = busy;
    if (submitButton) submitButton.disabled = busy;
    if (submitButton) submitButton.classList.toggle("opacity-60", busy);
}

async function getStorageNodeStatus() {
    const response = await fetch(`${NODE_URL}/api/status`);
    if (!response.ok) return null;
    return response.json();
}

function renderUploadQueue(files) {
    const status = document.getElementById("upload-status");
    if (!status) return;
    status.innerHTML = files.map((file, index) => `
        <div id="upload-file-${index}" class="py-1 text-xs text-gray-400">
            ${escapeHtml(file.name)} - queued
        </div>
    `).join("");
}

function setUploadFileStatus(index, message, isError = false) {
    const row = document.getElementById(`upload-file-${index}`);
    if (!row) return;
    row.innerText = message;
    row.className = isError ? "py-1 text-xs text-red-400" : "py-1 text-xs text-gray-300";
}

function appendUploadSummary(message) {
    const status = document.getElementById("upload-status");
    if (!status) return;
    status.insertAdjacentHTML("beforeend", `<div class="pt-2 text-xs text-cyan-300">${escapeHtml(message)}</div>`);
}

function uploadWithProgress(formData, file, onProgress) {
    return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open("POST", `${NODE_URL}/api/files/cache`);
        xhr.timeout = 30 * 60 * 1000;

        xhr.upload.addEventListener("progress", (event) => {
            if (!event.lengthComputable) {
                onProgress(`Uploading ${file.name}...`);
                return;
            }
            const percent = Math.round((event.loaded / event.total) * 100);
            onProgress(`Uploading ${file.name}: ${percent}% (${formatBytes(event.loaded)} / ${formatBytes(event.total)})`);
        });

        xhr.upload.addEventListener("load", () => {
            onProgress(`Upload sent. Hashing and registering ${file.name}...`);
        });

        xhr.addEventListener("load", () => {
            let data = {};
            try {
                data = JSON.parse(xhr.responseText || "{}");
            } catch (error) {
                data = { error: xhr.responseText || String(error) };
            }
            resolve({ ok: xhr.status >= 200 && xhr.status < 300, status: xhr.status, data });
        });

        xhr.addEventListener("error", () => reject(new Error("network error while uploading")));
        xhr.addEventListener("timeout", () => reject(new Error("upload timed out")));
        xhr.addEventListener("abort", () => reject(new Error("upload aborted")));
        xhr.send(formData);
    });
}

document.getElementById("upload-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    event.stopImmediatePropagation();

    const fileInput = document.getElementById("file-input");
    if (!fileInput.files.length) return;

    const files = Array.from(fileInput.files);
    setUploadState(null, true);
    renderUploadQueue(files);

    let uploaded = 0;
    let failed = 0;

    for (const [index, file] of files.entries()) {
        setUploadFileStatus(index, `Checking storage space for ${file.name}...`);

        try {
            const nodeStatus = await getStorageNodeStatus();
            if (nodeStatus && file.size > Number(nodeStatus.shared_space_free_bytes || 0)) {
                failed += 1;
                setUploadFileStatus(
                    index,
                    `Skipped ${file.name}: not enough Shared Space. File: ${formatBytes(file.size)}, free: ${formatBytes(nodeStatus.shared_space_free_bytes)}.`,
                    true,
                );
                continue;
            }
        } catch (error) {
            setUploadFileStatus(index, `Could not check storage space for ${file.name}. Uploading anyway...`);
        }

        const formData = new FormData();
        formData.append("file", file);
        formData.append("owner", "Web_UI_User");
        formData.append("location_type", "CACHED");

        try {
            const result = await uploadWithProgress(formData, file, (message) => setUploadFileStatus(index, message));
            if (result.ok) {
                uploaded += 1;
                setUploadFileStatus(index, `Uploaded ${file.name}. Type: ${result.data.media_type || "unknown"}.`);
            } else {
                failed += 1;
                const details = result.data.free_bytes !== undefined
                    ? ` Free: ${formatBytes(result.data.free_bytes)}, incoming: ${formatBytes(result.data.incoming_bytes)}.`
                    : "";
                setUploadFileStatus(index, `Failed ${file.name} (${result.status}): ${result.data.error || "unknown error"}.${details}`, true);
            }
        } catch (error) {
            failed += 1;
            setUploadFileStatus(index, `Failed ${file.name}: ${error.message || error}`, true);
        }
    }

    fileInput.value = "";
    appendUploadSummary(`Batch upload finished. Uploaded: ${uploaded}, failed: ${failed}.`);
    setUploadState(null, false);
    refreshDashboard();
});

if (false) document.getElementById("upload-form").addEventListener("submit", async (event) => {
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

function refreshDashboard() {
    fetchSystemStatus();
    renderViewControls();
    updateViewButtons();
    if (currentView === 'media_review' && isEditingMediaDraft()) return;
    if (currentView === 'deleted') fetchDeletedFiles();
    else if (currentView === 'media_review') fetchMediaDrafts();
    else if (currentView === 'media_library') fetchMediaLibrary();
    else fetchFilesList();
}
renderViewControls();
refreshDashboard();
setInterval(refreshDashboard, 4000);
