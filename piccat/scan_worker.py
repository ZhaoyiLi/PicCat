from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from .models import MediaItem, SortOrder
from .scanner import scan_media
from .storage import merge_catalog


class ScanSignals(QObject):
    finished = Signal(str, list)
    failed = Signal(str, str)


class ScanTask(QRunnable):
    def __init__(self, source_dir: str, sort_order: SortOrder, signals: ScanSignals) -> None:
        super().__init__()
        self.source_dir = source_dir
        self.sort_order = sort_order
        self.signals = signals

    @Slot()
    def run(self) -> None:
        try:
            items: list[MediaItem] = scan_media(self.source_dir, self.sort_order)
            items = merge_catalog(self.source_dir, items)
            self.signals.finished.emit(self.source_dir, items)
        except Exception as exc:
            self.signals.failed.emit(self.source_dir, str(exc))
