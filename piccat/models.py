from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".bmp",
    ".gif",
    ".tif",
    ".tiff",
    ".heic",
    ".heif",
    ".raw",
    ".cr2",
    ".nef",
    ".arw",
}

VIDEO_EXTENSIONS = {
    ".mp4",
    ".mov",
    ".avi",
    ".mkv",
    ".m4v",
    ".webm",
    ".3gp",
    ".mts",
    ".m2ts",
    ".wmv",
}


class MediaType(str, Enum):
    IMAGE = "image"
    VIDEO = "video"


class ItemStatus(str, Enum):
    UNPROCESSED = "unprocessed"
    COPIED = "copied"
    MOVED = "moved"
    SKIPPED = "skipped"
    PENDING = "pending"


class RuleAction(str, Enum):
    COPY = "copy"
    MOVE = "move"
    SKIP = "skip"


class ExecutionMode(str, Enum):
    IMMEDIATE = "immediate"
    BATCH = "batch"


class ConflictStrategy(str, Enum):
    SKIP_EXISTING = "skip_existing"
    RENAME_NEW_FILE = "rename_new_file"
    OVERWRITE = "overwrite"
    ASK_USER = "ask_user"


class SortOrder(str, Enum):
    NAME = "name"
    NEWEST = "newest"
    OLDEST = "oldest"


@dataclass
class SortRule:
    key: str
    label: str
    target_dir: str | None
    action: RuleAction = RuleAction.COPY
    processed_count: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SortRule":
        return cls(
            key=str(data.get("key", "")).upper(),
            label=str(data.get("label", "")),
            target_dir=data.get("target_dir"),
            action=RuleAction(data.get("action", RuleAction.COPY.value)),
            processed_count=int(data.get("processed_count", 0)),
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["action"] = self.action.value
        return data


@dataclass
class MediaItem:
    file_path: str
    file_name: str
    file_type: MediaType
    extension: str
    file_size: int
    created_time: float
    modified_time: float
    status: ItemStatus = ItemStatus.UNPROCESSED
    assigned_rule: str | None = None
    current_index: int = 0
    image_width: int | None = None
    image_height: int | None = None
    duration: float | None = None
    video_width: int | None = None
    video_height: int | None = None

    @classmethod
    def from_path(cls, path: Path, index: int) -> "MediaItem":
        stat = path.stat()
        extension = path.suffix.lower()
        file_type = MediaType.IMAGE if extension in IMAGE_EXTENSIONS else MediaType.VIDEO
        return cls(
            file_path=str(path),
            file_name=path.name,
            file_type=file_type,
            extension=extension,
            file_size=stat.st_size,
            created_time=stat.st_ctime,
            modified_time=stat.st_mtime,
            current_index=index,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MediaItem":
        return cls(
            file_path=data["file_path"],
            file_name=data.get("file_name") or Path(data["file_path"]).name,
            file_type=MediaType(data["file_type"]),
            extension=data.get("extension") or Path(data["file_path"]).suffix.lower(),
            file_size=int(data.get("file_size", 0)),
            created_time=float(data.get("created_time", 0)),
            modified_time=float(data.get("modified_time", 0)),
            status=ItemStatus(data.get("status", ItemStatus.UNPROCESSED.value)),
            assigned_rule=data.get("assigned_rule"),
            current_index=int(data.get("current_index", 0)),
            image_width=data.get("image_width"),
            image_height=data.get("image_height"),
            duration=data.get("duration"),
            video_width=data.get("video_width"),
            video_height=data.get("video_height"),
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["file_type"] = self.file_type.value
        data["status"] = self.status.value
        return data


@dataclass
class ActionRecord:
    source_path: str
    rule_key: str
    action: RuleAction
    dest_path: str | None = None
    previous_index: int = 0
    item_index: int = 0
    previous_status: ItemStatus = ItemStatus.UNPROCESSED

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ActionRecord":
        return cls(
            source_path=data["source_path"],
            rule_key=data["rule_key"],
            action=RuleAction(data["action"]),
            dest_path=data.get("dest_path"),
            previous_index=int(data.get("previous_index", 0)),
            item_index=int(data.get("item_index", 0)),
            previous_status=ItemStatus(data.get("previous_status", ItemStatus.UNPROCESSED.value)),
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["action"] = self.action.value
        data["previous_status"] = self.previous_status.value
        return data


@dataclass
class AppConfig:
    source_dir: str | None = None
    execution_mode: ExecutionMode = ExecutionMode.IMMEDIATE
    batch_size: int = 50
    preload_threshold: int = 35
    cache_back_count: int = 10
    image_preview_cache_limit: int = 100
    video_thumbnail_cache_limit: int = 100
    max_cache_count: int = 150
    conflict_strategy: ConflictStrategy = ConflictStrategy.RENAME_NEW_FILE
    sort_order: SortOrder = SortOrder.NEWEST
    rules: list[SortRule] = field(default_factory=list)

    @classmethod
    def default(cls) -> "AppConfig":
        return cls(
            rules=[
                SortRule("1", "Family", None, RuleAction.COPY),
                SortRule("2", "Travel", None, RuleAction.COPY),
                SortRule("3", "Work", None, RuleAction.COPY),
                SortRule("4", "Documents", None, RuleAction.COPY),
                SortRule("S", "Skip", None, RuleAction.SKIP),
            ]
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppConfig":
        default = cls.default()
        return cls(
            source_dir=data.get("source_dir"),
            execution_mode=ExecutionMode(data.get("execution_mode", default.execution_mode.value)),
            batch_size=int(data.get("batch_size", default.batch_size)),
            preload_threshold=int(data.get("preload_threshold", default.preload_threshold)),
            cache_back_count=int(data.get("cache_back_count", default.cache_back_count)),
            image_preview_cache_limit=int(data.get("image_preview_cache_limit", default.image_preview_cache_limit)),
            video_thumbnail_cache_limit=int(data.get("video_thumbnail_cache_limit", default.video_thumbnail_cache_limit)),
            max_cache_count=int(data.get("max_cache_count", default.max_cache_count)),
            conflict_strategy=ConflictStrategy(data.get("conflict_strategy", default.conflict_strategy.value)),
            sort_order=SortOrder(data.get("sort_order", default.sort_order.value)),
            rules=[SortRule.from_dict(rule) for rule in data.get("rules", [])] or default.rules,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_dir": self.source_dir,
            "execution_mode": self.execution_mode.value,
            "batch_size": self.batch_size,
            "preload_threshold": self.preload_threshold,
            "cache_back_count": self.cache_back_count,
            "image_preview_cache_limit": self.image_preview_cache_limit,
            "video_thumbnail_cache_limit": self.video_thumbnail_cache_limit,
            "max_cache_count": self.max_cache_count,
            "conflict_strategy": self.conflict_strategy.value,
            "sort_order": self.sort_order.value,
            "rules": [rule.to_dict() for rule in self.rules],
        }


@dataclass
class SessionState:
    config: AppConfig
    current_index: int = 0
    media_items: list[MediaItem] = field(default_factory=list)
    undo_history: list[ActionRecord] = field(default_factory=list)
    pending_actions: list[ActionRecord] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionState":
        return cls(
            config=AppConfig.from_dict(data.get("config", data)),
            current_index=int(data.get("current_index", 0)),
            media_items=[MediaItem.from_dict(item) for item in data.get("media_items", [])],
            undo_history=[ActionRecord.from_dict(action) for action in data.get("undo_history", [])],
            pending_actions=[ActionRecord.from_dict(action) for action in data.get("pending_actions", [])],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "config": self.config.to_dict(),
            "current_index": self.current_index,
            "media_items": [item.to_dict() for item in self.media_items],
            "undo_history": [action.to_dict() for action in self.undo_history],
            "pending_actions": [action.to_dict() for action in self.pending_actions],
        }
