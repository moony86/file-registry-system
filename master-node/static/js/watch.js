const MASTER_URL = window.location.origin;
const FILE_ID = window.FSYS_WATCH_FILE_ID;

const STORAGE_KEYS = {
    volume: "fsys.player.volume",
    muted: "fsys.player.muted",
    rate: "fsys.player.rate",
    subtitle: "fsys.player.subtitle",
};

let currentNext = null;
let nextPromptShown = false;

async function fetchJson(url) {
    const response = await fetch(url);
    const contentType = response.headers.get("content-type") || "";
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    if (!contentType.includes("application/json")) throw new Error("Expected JSON");
    return response.json();
}

function formatDuration(seconds) {
    const value = Number(seconds || 0);
    if (!value) return "";
    const total = Math.round(value);
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    if (hours) return `${hours}h ${minutes}m`;
    return `${minutes}m`;
}

function titleFromMedia(file, media) {
    const item = media.item || {};
    if (item.collection_title) return item.collection_title;
    if (item.title) return item.title;
    return file.file_name || "Video";
}

function setAmbient(file) {
    const bg = document.getElementById("ambient-bg");
    if (!bg || file.media_type !== "video") return;
    bg.style.backgroundImage = `url('${MASTER_URL}/api/files/${encodeURIComponent(file.file_id)}/thumbnail')`;
}

function renderInfo(file, media) {
    const item = media.item || {};
    const technical = file.technical_metadata || {};
    const title = titleFromMedia(file, media);
    const episodeParts = [];
    if (item.season_number || item.season) episodeParts.push(`Season ${item.season_number || item.season}`);
    if (item.episode_number || item.episode) episodeParts.push(`Episode ${item.episode_number || item.episode}`);

    const techParts = [];
    if (technical.width && technical.height) techParts.push(`${technical.height}p`);
    const duration = formatDuration(technical.duration_seconds);
    if (duration) techParts.push(duration);
    if (technical.video_codec) techParts.push(technical.video_codec);

    document.getElementById("watch-kicker").innerText = item.collection_title || item.media_kind || file.media_type || "";
    document.getElementById("watch-title").innerText = title;
    document.title = `${title} - FSYS Watch`;
    document.getElementById("watch-meta").innerText = [...episodeParts, ...techParts].join(" | ");
}

function applyStoredSettings(player) {
    const storedVolume = Number(localStorage.getItem(STORAGE_KEYS.volume));
    if (Number.isFinite(storedVolume)) player.volume = Math.min(Math.max(storedVolume, 0), 1);
    player.muted = localStorage.getItem(STORAGE_KEYS.muted) === "true";

    const storedRate = Number(localStorage.getItem(STORAGE_KEYS.rate) || "1");
    const rate = [0.5, 1, 1.25, 1.5, 2].includes(storedRate) ? storedRate : 1;
    player.playbackRate = rate;
    document.getElementById("speed-select").value = String(rate);
}

function bindPlayerSettings(player) {
    const speedSelect = document.getElementById("speed-select");
    speedSelect.addEventListener("change", () => {
        const rate = Number(speedSelect.value || "1");
        player.playbackRate = rate;
        localStorage.setItem(STORAGE_KEYS.rate, String(rate));
    });
    player.addEventListener("volumechange", () => {
        localStorage.setItem(STORAGE_KEYS.volume, String(player.volume));
        localStorage.setItem(STORAGE_KEYS.muted, String(player.muted));
    });
}

function languageLabel(subtitle) {
    return subtitle.label || subtitle.language || "Subtitle";
}

function setTextTrackMode(player, selectedSubtitleId) {
    const trackElements = Array.from(player.querySelectorAll("track"));
    trackElements.forEach((trackElement, index) => {
        const textTrack = player.textTracks[index];
        if (!textTrack) return;
        textTrack.mode = trackElement.dataset.subtitleId === selectedSubtitleId ? "showing" : "disabled";
    });
}

function addSubtitles(player, subtitles) {
    const select = document.getElementById("subtitle-select");
    player.querySelectorAll("track").forEach((track) => track.remove());
    select.innerHTML = `<option value="off">Off</option>`;

    const playable = (subtitles || []).filter((subtitle) =>
        subtitle.status === "active"
        && subtitle.subtitle_format !== "ass"
        && (subtitle.vtt_path || subtitle.subtitle_format === "vtt")
    );

    const storedSubtitle = localStorage.getItem(STORAGE_KEYS.subtitle);
    const hasDefault = playable.some((subtitle) => subtitle.is_default);
    playable.forEach((subtitle, index) => {
        const value = String(subtitle.subtitle_id);
        const option = document.createElement("option");
        option.value = value;
        option.textContent = languageLabel(subtitle);
        select.appendChild(option);

        const track = document.createElement("track");
        track.kind = "subtitles";
        track.src = `${MASTER_URL}/api/media/subtitles/${subtitle.subtitle_id}/file`;
        track.srclang = subtitle.language || "unknown";
        track.label = languageLabel(subtitle);
        track.dataset.subtitleId = value;
        if (storedSubtitle === value || (!storedSubtitle && (subtitle.is_default || (!hasDefault && index === 0)))) {
            track.default = true;
            select.value = value;
        }
        player.appendChild(track);
    });

    select.addEventListener("change", () => {
        const selected = select.value;
        localStorage.setItem(STORAGE_KEYS.subtitle, selected);
        setTextTrackMode(player, selected);
    });

    player.addEventListener("loadedmetadata", () => {
        setTextTrackMode(player, select.value);
    }, { once: true });
}

function bindKeyboard(player) {
    document.addEventListener("keydown", (event) => {
        const tag = document.activeElement?.tagName?.toLowerCase();
        if (["input", "textarea", "select"].includes(tag)) return;

        if (event.code === "Space") {
            event.preventDefault();
            if (player.paused) player.play().catch(() => {});
            else player.pause();
        } else if (event.key === "ArrowRight") {
            player.currentTime = Math.min(player.duration || Infinity, player.currentTime + 10);
        } else if (event.key === "ArrowLeft") {
            player.currentTime = Math.max(0, player.currentTime - 10);
        } else if (event.key.toLowerCase() === "f") {
            if (!document.fullscreenElement) player.requestFullscreen?.();
            else document.exitFullscreen?.();
        } else if (event.key.toLowerCase() === "m") {
            player.muted = !player.muted;
        } else if (event.key === "Escape" && document.fullscreenElement) {
            document.exitFullscreen?.();
        }
    });
}

function openWatch(fileId) {
    window.location.href = `/watch/${encodeURIComponent(fileId)}`;
}

function setupNeighbors(neighbors) {
    const previous = neighbors.previous;
    currentNext = neighbors.next;
    const prevBtn = document.getElementById("previous-btn");
    const nextBtn = document.getElementById("next-btn");
    if (previous) {
        prevBtn.classList.remove("hidden");
        prevBtn.onclick = () => openWatch(previous.file_id);
    }
    if (currentNext) {
        nextBtn.classList.remove("hidden");
        nextBtn.onclick = () => openWatch(currentNext.file_id);
        document.getElementById("next-prompt-title").innerText = currentNext.title || "Next episode";
        document.getElementById("next-prompt-btn").onclick = () => openWatch(currentNext.file_id);
    }
}

function bindEndPrompt(player) {
    player.addEventListener("timeupdate", () => {
        if (!currentNext || nextPromptShown || !player.duration) return;
        if (player.duration - player.currentTime <= 30) {
            nextPromptShown = true;
            document.getElementById("next-prompt").classList.remove("hidden");
        }
    });
}

function showError(message) {
    const error = document.getElementById("watch-error");
    error.innerText = message;
    error.classList.remove("hidden");
}

async function loadWatchPage() {
    const player = document.getElementById("watch-player");
    try {
        const [file, media, subtitles, location, neighbors] = await Promise.all([
            fetchJson(`${MASTER_URL}/api/files/${FILE_ID}`),
            fetchJson(`${MASTER_URL}/api/media/files/${FILE_ID}`),
            fetchJson(`${MASTER_URL}/api/media/files/${FILE_ID}/subtitles`),
            fetchJson(`${MASTER_URL}/api/files/${FILE_ID}/location?access_type=stream_location`),
            fetchJson(`${MASTER_URL}/api/media/files/${FILE_ID}/neighbors`),
        ]);

        if (file.media_type !== "video") throw new Error("This file is not a video.");
        const host = location.node?.host;
        const port = location.node?.port;
        if (!host || !port) throw new Error("Storage node location is missing.");

        renderInfo(file, media);
        setAmbient(file);
        applyStoredSettings(player);
        bindPlayerSettings(player);
        addSubtitles(player, subtitles.subtitles || []);
        bindKeyboard(player);
        bindEndPrompt(player);
        setupNeighbors(neighbors);

        player.src = `http://${host}:${port}/api/files/${FILE_ID}/stream`;
        player.play().catch(() => {});
    } catch (error) {
        showError(`Cannot load watch page: ${error.message || error}`);
    }
}

loadWatchPage();
