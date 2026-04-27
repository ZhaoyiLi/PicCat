from __future__ import annotations

from pathlib import Path

from .models import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, MediaItem, SortOrder


SUPPORTED_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS


def scan_media(source_dir: str, sort_order: SortOrder = SortOrder.NAME) -> list[MediaItem]:
    root = Path(source_dir)
    paths = [
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.name not in {".media_sorter_session.json", ".media_sorter_catalog.json"}
        and path.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    if sort_order == SortOrder.NEWEST:
        paths.sort(key=lambda item: (item.stat().st_mtime, str(item).lower()), reverse=True)
    elif sort_order == SortOrder.OLDEST:
        paths.sort(key=lambda item: (item.stat().st_mtime, str(item).lower()))
    else:
        paths.sort(key=lambda item: str(item).lower())
    return [MediaItem.from_path(path, index) for index, path in enumerate(paths)]
