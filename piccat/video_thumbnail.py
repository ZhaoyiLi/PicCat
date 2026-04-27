from __future__ import annotations

from collections import OrderedDict
import subprocess

from PySide6.QtCore import QObject, QRunnable, QSize, Signal, Slot
from PySide6.QtGui import QPixmap

from .ffmpeg_locator import find_executable


class VideoThumbnailSignals(QObject):
    loaded = Signal(str, QPixmap)
    failed = Signal(str, str)


class VideoThumbnailTask(QRunnable):
    def __init__(self, path: str, target_size: QSize, signals: VideoThumbnailSignals) -> None:
        super().__init__()
        self.path = path
        self.target_size = target_size
        self.signals = signals

    @Slot()
    def run(self) -> None:
        ffmpeg = find_executable("ffmpeg")
        if not ffmpeg:
            self.signals.failed.emit(self.path, "ffmpeg not found")
            return
        width = max(320, self.target_size.width())
        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            "00:00:01",
            "-i",
            self.path,
            "-frames:v",
            "1",
            "-vf",
            f"scale={width}:-1",
            "-f",
            "image2pipe",
            "-vcodec",
            "png",
            "pipe:1",
        ]
        try:
            completed = subprocess.run(command, capture_output=True, timeout=12, check=False)
        except (FileNotFoundError, subprocess.SubprocessError) as exc:
            self.signals.failed.emit(self.path, str(exc))
            return
        if completed.returncode != 0 or not completed.stdout:
            self.signals.failed.emit(self.path, completed.stderr.decode("utf-8", errors="ignore"))
            return
        pixmap = QPixmap()
        if pixmap.loadFromData(completed.stdout, "PNG"):
            self.signals.loaded.emit(self.path, pixmap)
        else:
            self.signals.failed.emit(self.path, "Could not decode thumbnail")


class VideoThumbnailCache(QObject):
    loaded = Signal(str, QPixmap)
    failed = Signal(str, str)

    def __init__(self, limit: int = 100) -> None:
        super().__init__()
        self.limit = limit
        self._cache: OrderedDict[str, QPixmap] = OrderedDict()
        self._loading: set[str] = set()
        self._signals = VideoThumbnailSignals()
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
        if path in self._cache or path in self._loading:
            return
        self._loading.add(path)
        from PySide6.QtCore import QThreadPool

        QThreadPool.globalInstance().start(VideoThumbnailTask(path, target_size, self._signals))

    @Slot(str, QPixmap)
    def _on_loaded(self, path: str, pixmap: QPixmap) -> None:
        self._loading.discard(path)
        self._cache[path] = pixmap
        self._cache.move_to_end(path)
        while len(self._cache) > self.limit:
            self._cache.popitem(last=False)
        self.loaded.emit(path, pixmap)

    @Slot(str, str)
    def _on_failed(self, path: str, error: str) -> None:
        self._loading.discard(path)
        self.failed.emit(path, error)
