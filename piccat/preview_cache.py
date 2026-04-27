from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

from PIL import Image, ImageOps
from PySide6.QtCore import QObject, QRunnable, QSize, QThreadPool, Signal, Slot
from PySide6.QtGui import QImage, QPixmap

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except Exception:
    pass

from .models import MediaItem, MediaType


class PreviewSignals(QObject):
    loaded = Signal(str, QPixmap, int, int)
    failed = Signal(str, str)


class PreviewTask(QRunnable):
    def __init__(self, path: str, target_size: QSize, signals: PreviewSignals) -> None:
        super().__init__()
        self.path = path
        self.target_size = target_size
        self.signals = signals

    @Slot()
    def run(self) -> None:
        try:
            with Image.open(self.path) as image:
                image = ImageOps.exif_transpose(image)
                width, height = image.size
                max_size = (
                    max(64, self.target_size.width()),
                    max(64, self.target_size.height()),
                )
                image.thumbnail(max_size, Image.Resampling.LANCZOS)
                rgba = image.convert("RGBA")
                data = rgba.tobytes("raw", "RGBA")
                qimage = QImage(data, rgba.width, rgba.height, QImage.Format.Format_RGBA8888).copy()
                self.signals.loaded.emit(self.path, QPixmap.fromImage(qimage), width, height)
        except Exception as exc:
            self.signals.failed.emit(self.path, str(exc))


class PreviewCache(QObject):
    loaded = Signal(str, QPixmap, int, int)
    failed = Signal(str, str)

    def __init__(self, limit: int = 100) -> None:
        super().__init__()
        self.limit = limit
        self._cache: OrderedDict[str, QPixmap] = OrderedDict()
        self._loading: set[str] = set()
        self._pool = QThreadPool.globalInstance()
        self._signals = PreviewSignals()
        self._signals.loaded.connect(self._on_loaded)
        self._signals.failed.connect(self._on_failed)

    def clear(self) -> None:
        self._cache.clear()
        self._loading.clear()

    def get(self, path: str) -> QPixmap | None:
        pixmap = self._cache.get(path)
        if pixmap:
            self._cache.move_to_end(path)
        return pixmap

    def request(self, path: str, target_size: QSize) -> None:
        if path in self._cache or path in self._loading or not Path(path).exists():
            return
        self._loading.add(path)
        self._pool.start(PreviewTask(path, target_size, self._signals))

    def preload_window(self, items: list[MediaItem], start: int, count: int, target_size: QSize) -> None:
        end = min(len(items), start + count)
        for item in items[start:end]:
            if item.file_type == MediaType.IMAGE:
                self.request(item.file_path, target_size)

    def prune_around(self, items: list[MediaItem], index: int, back_count: int, forward_count: int) -> None:
        keep_paths = {
            item.file_path
            for item in items[max(0, index - back_count) : min(len(items), index + forward_count)]
            if item.file_type == MediaType.IMAGE
        }
        for path in list(self._cache.keys()):
            if len(self._cache) <= self.limit and path in keep_paths:
                continue
            if path not in keep_paths or len(self._cache) > self.limit:
                self._cache.pop(path, None)

    @Slot(str, QPixmap, int, int)
    def _on_loaded(self, path: str, pixmap: QPixmap, width: int, height: int) -> None:
        self._loading.discard(path)
        self._cache[path] = pixmap
        self._cache.move_to_end(path)
        while len(self._cache) > self.limit:
            self._cache.popitem(last=False)
        self.loaded.emit(path, pixmap, width, height)

    @Slot(str, str)
    def _on_failed(self, path: str, error: str) -> None:
        self._loading.discard(path)
        self.failed.emit(path, error)
