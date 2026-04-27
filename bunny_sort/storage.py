from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import AppConfig, MediaItem, SessionState


SESSION_FILE_NAME = ".media_sorter_session.json"
CATALOG_FILE_NAME = ".media_sorter_catalog.json"


def session_path_for(source_dir: str | None) -> Path | None:
    if not source_dir:
        return None
    return Path(source_dir) / SESSION_FILE_NAME


def catalog_path_for(source_dir: str | None) -> Path | None:
    if not source_dir:
        return None
    return Path(source_dir) / CATALOG_FILE_NAME


def load_session(source_dir: str | None = None) -> SessionState:
    path = session_path_for(source_dir)
    if path and path.exists():
        return SessionState.from_dict(json.loads(path.read_text(encoding="utf-8")))
    return SessionState(config=AppConfig.default())


def save_session(state: SessionState) -> None:
    path = session_path_for(state.config.source_dir)
    if not path:
        return
    path.write_text(json.dumps(state.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")


def load_catalog(source_dir: str | None) -> dict[str, Any]:
    path = catalog_path_for(source_dir)
    if not path or not path.exists():
        return {"version": 1, "items": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if "items" not in data:
        return {"version": 1, "items": {}}
    return data


def save_catalog(source_dir: str | None, items: list[MediaItem]) -> None:
    path = catalog_path_for(source_dir)
    if not path or not source_dir:
        return
    root = Path(source_dir)
    catalog_items: dict[str, Any] = {}
    for item in items:
        file_path = Path(item.file_path)
        try:
            key = file_path.relative_to(root).as_posix()
        except ValueError:
            key = str(file_path)
        catalog_items[key] = {
            "file_path": item.file_path,
            "file_name": item.file_name,
            "file_type": item.file_type.value,
            "status": item.status.value,
            "assigned_rule": item.assigned_rule,
            "extension": item.extension,
            "file_size": item.file_size,
            "modified_time": item.modified_time,
        }
    payload = {
        "version": 1,
        "source_dir": source_dir,
        "categorized_count": sum(1 for item in items if item.status.value in {"copied", "moved", "pending"}),
        "skipped_count": sum(1 for item in items if item.status.value == "skipped"),
        "uncategorized_count": sum(1 for item in items if item.status.value in {"unprocessed", "skipped"}),
        "items": catalog_items,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def merge_catalog(source_dir: str, scanned_items: list[MediaItem]) -> list[MediaItem]:
    catalog = load_catalog(source_dir)
    root = Path(source_dir)
    catalog_items = catalog.get("items", {})
    for index, item in enumerate(scanned_items):
        item.current_index = index
        file_path = Path(item.file_path)
        try:
            key = file_path.relative_to(root).as_posix()
        except ValueError:
            key = str(file_path)
        saved = catalog_items.get(key)
        if not saved:
            continue
        if saved.get("file_size") != item.file_size or saved.get("modified_time") != item.modified_time:
            continue
        merged = MediaItem.from_dict({**item.to_dict(), **saved, "file_path": item.file_path})
        scanned_items[index] = merged
    return scanned_items
