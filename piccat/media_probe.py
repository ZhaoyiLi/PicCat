from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .ffmpeg_locator import find_executable


def probe_video(path: str) -> dict[str, float | int | None]:
    ffprobe = find_executable("ffprobe")
    if not ffprobe:
        return {"duration": None, "width": None, "height": None}
    command = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,duration",
        "-of",
        "json",
        path,
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=8, check=False)
    except (FileNotFoundError, subprocess.SubprocessError):
        return {"duration": None, "width": None, "height": None}
    if completed.returncode != 0:
        return {"duration": None, "width": None, "height": None}
    try:
        stream = (json.loads(completed.stdout).get("streams") or [{}])[0]
    except (json.JSONDecodeError, IndexError):
        return {"duration": None, "width": None, "height": None}
    duration = stream.get("duration")
    return {
        "duration": float(duration) if duration not in (None, "N/A") else None,
        "width": int(stream["width"]) if stream.get("width") else None,
        "height": int(stream["height"]) if stream.get("height") else None,
    }


def file_size_label(path: str) -> str:
    size = Path(path).stat().st_size
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} {unit}"
        value /= 1024
    return f"{size} B"
