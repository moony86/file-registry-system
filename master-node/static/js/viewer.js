const MASTER_URL = window.location.origin;

let mediaLibrary = null;
let currentSection = "home";

function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function escapeJsArg(value) {
    return String(value ?? "")
        .replaceAll("\\", "\\\\")
        .replaceAll("'", "\\'")
        .replaceAll("\n", " ");
}

function formatDate(value) {
    if (!value) return "";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "";
    return date.toLocaleDateString();
}

async function fetchJson(url) {
    const response = await fetch(url);
    const contentType = response.headers.get("content-type") || "";
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    if (!contentType.includes("application/json")) throw new Error("Expected JSON");
    return response.json();
}

function allPlayableItems(library) {
    const flat = [];
    const simpleGroups = ["movies", "youtube", "shorts", "courses", "clips", "other"];
    for (const group of simpleGroups) {
        for (const item of library[group] || []) flat.push(item);
    }
    for (const groupName of ["series", "anime"]) {
        for (const collection of library[groupName] || []) {
            const seasons = collection.seasons || {};
            for (const [seasonNumber, episodes] of Object.entries(seasons)) {
                for (const item of episodes || []) {
                    flat.push({
                        ...item,
                        collection_title: collection.title,
                        collection_id: collection.collection_id,
                        season_number: item.season_number || item.season || Number(seasonNumber),
                    });
                }
            }
        }
    }
    return flat.filter((item) => item.file_status === "ACTIVE" && item.is_available);
}

function cardTitle(item) {
    return item.collection_title || item.title || item.file_name || "Untitled";
}

function mediaCard(item) {
    const subtitleParts = [item.media_kind || "video"];
    const season = item.season_number || item.season;
    const episode = item.episode_number || item.episode;
    if (season || episode) subtitleParts.push(`S${season || ""} E${episode || ""}`);
    const canPlay = item.file_status === "ACTIVE" && item.is_available;
    return `
        <article class="bg-gray-900 border border-gray-800 overflow-hidden hover:border-cyan-700 transition">
            <div class="aspect-[2/3] bg-gradient-to-br from-gray-800 to-gray-950 flex items-center justify-center">
                <span class="text-5xl text-gray-600">PLAY</span>
            </div>
            <div class="p-4 space-y-3">
                <div>
                    <h3 class="font-bold text-gray-100 line-clamp-2">${escapeHtml(cardTitle(item))}</h3>
                    <p class="text-xs text-gray-500 mt-1">${escapeHtml(subtitleParts.join(" | "))}</p>
                </div>
                <button ${canPlay ? `onclick="playVideo('${escapeJsArg(item.file_id)}', '${escapeJsArg(cardTitle(item))}')"` : "disabled"}
                    class="${canPlay ? "bg-cyan-600 hover:bg-cyan-500 text-white" : "bg-gray-800 text-gray-500"} w-full py-2 text-sm font-semibold transition">
                    Play
                </button>
            </div>
        </article>`;
}

function collectionCard(collection, type) {
    const seasons = collection.seasons || {};
    const episodeCount = Object.values(seasons).reduce((total, episodes) => total + (episodes || []).length, 0);
    const collectionKey = String(collection.collection_id || collection.title);
    return `
        <button onclick="renderCollection('${escapeJsArg(type)}', '${escapeJsArg(collectionKey)}')"
            class="text-left bg-gray-900 border border-gray-800 hover:border-cyan-700 transition overflow-hidden">
            <div class="aspect-video bg-gradient-to-br from-cyan-950 to-gray-950 flex items-center justify-center">
                <span class="text-4xl text-cyan-800">FSYS</span>
            </div>
            <div class="p-4">
                <h3 class="font-bold text-gray-100">${escapeHtml(collection.title || "Untitled")}</h3>
                <p class="text-xs text-gray-500 mt-1">${Object.keys(seasons).length} seasons | ${episodeCount} episodes</p>
            </div>
        </button>`;
}

function renderGrid(items, emptyMessage = "No media yet.") {
    if (!items.length) {
        return `<div class="text-gray-500 border border-gray-800 p-8">${emptyMessage}</div>`;
    }
    return `<div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">${items.map(mediaCard).join("")}</div>`;
}

function renderCollectionGrid(collections, type) {
    if (!collections.length) {
        return `<div class="text-gray-500 border border-gray-800 p-8">No ${type} collections yet.</div>`;
    }
    return `<div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">${collections.map((collection) => collectionCard(collection, type)).join("")}</div>`;
}

function setHeader(kicker, title, subtitle) {
    document.getElementById("viewer-kicker").innerText = kicker;
    document.getElementById("viewer-title").innerText = title;
    document.getElementById("viewer-subtitle").innerText = subtitle;
}

function setActiveNav(section) {
    document.querySelectorAll(".viewer-nav").forEach((button) => {
        const active = button.dataset.section === section;
        button.className = active
            ? "viewer-nav is-active px-3 py-1 rounded bg-cyan-600 text-white"
            : "viewer-nav px-3 py-1 rounded text-gray-300 hover:text-white hover:bg-gray-800";
    });
}

function renderSection(section) {
    currentSection = section;
    setActiveNav(section);
    const content = document.getElementById("viewer-content");
    if (!mediaLibrary) return;

    if (section === "home") {
        const items = allPlayableItems(mediaLibrary)
            .sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0))
            .slice(0, 20);
        setHeader("Home Media Server", "Recently Added", "Approved media from your FSYS library.");
        content.innerHTML = renderGrid(items, "No approved media yet.");
        return;
    }

    if (section === "movies") {
        setHeader("Movies", "Movies", "Approved movies only.");
        content.innerHTML = renderGrid(mediaLibrary.movies || [], "No approved movies yet.");
        return;
    }

    if (section === "anime" || section === "series") {
        const title = section === "anime" ? "Anime" : "Series";
        setHeader(title, title, "Collections, seasons, and episodes.");
        content.innerHTML = renderCollectionGrid(mediaLibrary[section] || [], section);
        return;
    }

    if (section === "clips") {
        const clips = [
            ...(mediaLibrary.youtube || []),
            ...(mediaLibrary.shorts || []),
            ...(mediaLibrary.clips || []),
        ];
        setHeader("Clips", "Clips", "YouTube videos, shorts, and clips.");
        content.innerHTML = renderGrid(clips, "No approved clips yet.");
        return;
    }

    if (section === "courses") {
        setHeader("Courses", "Courses", "Approved course videos.");
        content.innerHTML = renderGrid(mediaLibrary.courses || [], "No approved courses yet.");
    }
}

function renderCollection(type, collectionKey) {
    const collections = mediaLibrary[type] || [];
    const collection = collections.find((item) =>
        String(item.collection_id || item.title) === String(collectionKey)
    );
    if (!collection) return;

    setHeader(type === "anime" ? "Anime" : "Series", collection.title || "Collection", "Seasons and episodes.");
    setActiveNav(type);

    const seasons = collection.seasons || {};
    const seasonBlocks = Object.entries(seasons).map(([seasonNumber, episodes]) => `
        <section class="space-y-3">
            <h2 class="text-xl font-bold text-gray-200">Season ${escapeHtml(seasonNumber)}</h2>
            ${renderGrid((episodes || []).map((episode) => ({
                ...episode,
                collection_title: collection.title,
            })), "No episodes in this season.")}
        </section>
    `).join("");

    document.getElementById("viewer-content").innerHTML = `
        <button onclick="renderSection('${type}')" class="text-sm text-cyan-300 hover:text-cyan-200">Back to ${type}</button>
        ${seasonBlocks || '<div class="text-gray-500 border border-gray-800 p-8">No episodes yet.</div>'}
    `;
}

async function playVideo(fileId, title) {
    try {
        const data = await fetchJson(`${MASTER_URL}/api/files/${fileId}/location?access_type=stream_location`);
        const host = data.node && data.node.host;
        const port = data.node && data.node.port;
        if (!host || !port) throw new Error("Storage node is missing");

        const modal = document.getElementById("viewer-video-modal");
        const player = document.getElementById("viewer-video-player");
        document.getElementById("viewer-video-title").innerText = title || data.file_name || "Video";
        player.src = `http://${host}:${port}/api/files/${fileId}/stream`;
        modal.classList.remove("hidden");
        player.play().catch(() => {});
    } catch (error) {
        alert(`Cannot play video: ${error.message || error}`);
    }
}

function closeVideo() {
    const modal = document.getElementById("viewer-video-modal");
    const player = document.getElementById("viewer-video-player");
    player.pause();
    player.removeAttribute("src");
    player.load();
    modal.classList.add("hidden");
}

async function loadViewer() {
    const content = document.getElementById("viewer-content");
    try {
        mediaLibrary = await fetchJson(`${MASTER_URL}/api/media/library`);
        renderSection(currentSection);
    } catch (error) {
        content.innerHTML = `<div class="text-red-400 border border-red-900/60 p-8">Could not load media library. Restart Master Node if the media API was just added.</div>`;
        console.error("Failed to load viewer library:", error);
    }
}

document.querySelectorAll(".viewer-nav").forEach((button) => {
    button.addEventListener("click", () => renderSection(button.dataset.section));
});

document.getElementById("viewer-video-close").addEventListener("click", closeVideo);
document.getElementById("viewer-video-modal").addEventListener("click", (event) => {
    if (event.target.id === "viewer-video-modal") closeVideo();
});

loadViewer();
