from pathlib import Path

def detect_media_type(mime_type, filename):
    mime_type = (mime_type or "").lower()
    ext = Path(filename).suffix.lower()

    if mime_type.startswith("video/"):
        return "video"
    if mime_type.startswith("audio/"):
        return "audio"
    if mime_type.startswith("image/"):
        return "image"
    if ext in {".srt", ".ass", ".ssa", ".vtt"}:
        return "subtitle"
    if ext in {".pdf", ".doc", ".docx", ".txt", ".md", ".xlsx", ".csv"}:
        return "document"
    return "other"
