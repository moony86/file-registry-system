import subprocess
from pathlib import Path


def _result(status, thumbnail_path=None, error=None, width=None, height=None):
    return {
        "thumbnail_status": status,
        "thumbnail_path": str(thumbnail_path) if thumbnail_path else None,
        "width": width,
        "height": height,
        "error_message": error,
    }


def _capture_second(duration_seconds):
    try:
        duration = float(duration_seconds or 0)
    except (TypeError, ValueError):
        duration = 0

    if duration <= 0:
        return 30
    if duration < 30:
        return max(duration / 2, 0.1)
    return min(30, max(duration * 0.10, 1))


def generate_thumbnail(video_path, content_hash, thumbnails_dir, duration_seconds=None):
    if not video_path or not content_hash:
        return _result("skipped", error="missing video path or content hash")

    video_path = Path(video_path)
    if not video_path.exists() or not video_path.is_file():
        return _result("failed", error="video file does not exist")

    thumbnails_dir = Path(thumbnails_dir)
    shard = str(content_hash)[:2]
    thumbnail_path = thumbnails_dir / shard / f"{content_hash}.jpg"
    thumbnail_path.parent.mkdir(parents=True, exist_ok=True)

    if thumbnail_path.exists() and thumbnail_path.is_file():
        return _result("success", thumbnail_path=thumbnail_path)

    command = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{_capture_second(duration_seconds):.3f}",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-q:v",
        "3",
        str(thumbnail_path),
    ]

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except FileNotFoundError:
        return _result("unavailable", error="ffmpeg executable was not found")
    except subprocess.TimeoutExpired:
        thumbnail_path.unlink(missing_ok=True)
        return _result("failed", error="ffmpeg timed out")
    except Exception as exc:
        thumbnail_path.unlink(missing_ok=True)
        return _result("failed", error=str(exc))

    if completed.returncode != 0 or not thumbnail_path.exists():
        thumbnail_path.unlink(missing_ok=True)
        error = (completed.stderr or completed.stdout or f"ffmpeg exited with {completed.returncode}").strip()
        return _result("failed", error=error[:1000])

    return _result("success", thumbnail_path=thumbnail_path)
