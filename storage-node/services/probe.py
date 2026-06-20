import json
import subprocess


TECHNICAL_METADATA_KEYS = (
    "duration_seconds",
    "width",
    "height",
    "video_codec",
    "audio_codec",
    "audio_channels",
    "bitrate",
    "fps",
    "format_name",
)


def _empty_metadata(probe_status="unknown", probe_error=None):
    metadata = {key: None for key in TECHNICAL_METADATA_KEYS}
    metadata["probe_status"] = probe_status
    metadata["probe_error"] = probe_error
    return metadata


def _float_or_none(value):
    try:
        if value in (None, "", "N/A"):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value):
    try:
        if value in (None, "", "N/A"):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _fps_from_rate(value):
    if not value or value == "0/0":
        return None
    try:
        if "/" in value:
            numerator, denominator = value.split("/", 1)
            numerator = float(numerator)
            denominator = float(denominator)
            if denominator == 0:
                return None
            return round(numerator / denominator, 3)
        return round(float(value), 3)
    except (TypeError, ValueError):
        return None


def probe_media_file(path):
    command = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except FileNotFoundError:
        return _empty_metadata("unavailable", "ffprobe executable was not found")
    except subprocess.TimeoutExpired:
        return _empty_metadata("failed", "ffprobe timed out")
    except Exception as exc:
        return _empty_metadata("failed", str(exc))

    if result.returncode != 0:
        error = (result.stderr or result.stdout or f"ffprobe exited with {result.returncode}").strip()
        return _empty_metadata("failed", error[:1000])

    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        return _empty_metadata("failed", f"Invalid ffprobe JSON: {exc}")

    streams = payload.get("streams") or []
    format_info = payload.get("format") or {}
    video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
    audio_stream = next((stream for stream in streams if stream.get("codec_type") == "audio"), {})

    metadata = _empty_metadata("success", None)
    metadata.update({
        "duration_seconds": _float_or_none(format_info.get("duration")),
        "width": _int_or_none(video_stream.get("width")),
        "height": _int_or_none(video_stream.get("height")),
        "video_codec": video_stream.get("codec_name"),
        "audio_codec": audio_stream.get("codec_name"),
        "audio_channels": _int_or_none(audio_stream.get("channels")),
        "bitrate": _int_or_none(format_info.get("bit_rate")),
        "fps": _fps_from_rate(video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate")),
        "format_name": format_info.get("format_name"),
    })
    return metadata
