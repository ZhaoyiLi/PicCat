from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool, QTimer, QUrl
from PySide6.QtGui import QAction, QKeySequence, QPixmap, QShortcut
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSlider,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from .file_ops import execute_file_action, undo_file_action
from .media_probe import file_size_label, probe_video
from .models import (
    ActionRecord,
    AppConfig,
    ConflictStrategy,
    ExecutionMode,
    ItemStatus,
    MediaItem,
    MediaType,
    RuleAction,
    SortOrder,
    SortRule,
)
from .preview_cache import PreviewCache
from .scan_worker import ScanSignals, ScanTask
from .storage import merge_catalog, save_catalog, load_session, save_session
from .video_thumbnail import VideoThumbnailCache


class RuleDialog(QDialog):
    def __init__(self, parent: QWidget, rule: SortRule | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Rule")
        self.key_edit = QLineEdit(rule.key if rule else "")
        self.label_edit = QLineEdit(rule.label if rule else "")
        self.target_edit = QLineEdit(rule.target_dir if rule and rule.target_dir else "")
        self.action_combo = QComboBox()
        self.action_combo.addItems([RuleAction.COPY.value, RuleAction.MOVE.value, RuleAction.SKIP.value])
        self.action_combo.setCurrentText((rule.action if rule else RuleAction.COPY).value)

        browse = QPushButton("Browse")
        browse.clicked.connect(self._browse_target)

        target_row = QHBoxLayout()
        target_row.addWidget(self.target_edit)
        target_row.addWidget(browse)

        form = QFormLayout()
        form.addRow("Shortcut", self.key_edit)
        form.addRow("Label", self.label_edit)
        form.addRow("Target folder", target_row)
        form.addRow("Action", self.action_combo)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _browse_target(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Target folder")
        if folder:
            self.target_edit.setText(folder)

    def rule(self, processed_count: int = 0) -> SortRule:
        action = RuleAction(self.action_combo.currentText())
        return SortRule(
            key=self.key_edit.text().strip().upper(),
            label=self.label_edit.text().strip(),
            target_dir=self.target_edit.text().strip() or None,
            action=action,
            processed_count=processed_count,
        )


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PicCat")
        self.state = load_session()
        self.shortcuts: list[QShortcut] = []
        self.preview_cache = PreviewCache(self.state.config.image_preview_cache_limit)
        self.preview_cache.loaded.connect(self._on_preview_loaded)
        self.preview_cache.failed.connect(self._on_preview_failed)
        self.video_thumbnail_cache = VideoThumbnailCache(self.state.config.video_thumbnail_cache_limit)
        self.video_thumbnail_cache.loaded.connect(self._on_video_thumbnail_loaded)
        self.video_thumbnail_cache.failed.connect(self._on_video_thumbnail_failed)

        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.video_widget = QVideoWidget()
        self.player.setVideoOutput(self.video_widget)
        self.player.durationChanged.connect(self._sync_duration)
        self.player.positionChanged.connect(self._sync_position)
        self.media_filter = "all"
        self.view_positions: dict[str, str] = {}
        self.scan_pool = QThreadPool.globalInstance()
        self.scan_signals = ScanSignals()
        self.scan_signals.finished.connect(self._on_scan_finished)
        self.scan_signals.failed.connect(self._on_scan_failed)
        self.is_scanning = False

        self._build_ui()
        self._bind_actions()
        self._install_shortcuts()
        self._restore_if_possible()

        self.autosave_timer = QTimer(self)
        self.autosave_timer.setInterval(5000)
        self.autosave_timer.timeout.connect(self._save_session)
        self.autosave_timer.start()

        self.feedback_timer = QTimer(self)
        self.feedback_timer.setSingleShot(True)
        self.feedback_timer.timeout.connect(self._hide_action_feedback)

    def _build_ui(self) -> None:
        toolbar = QToolBar("Main")
        self.addToolBar(toolbar)

        self.open_action = QAction("Open Folder", self)
        self.commit_action = QAction("Commit Batch", self)
        self.undo_action = QAction("Undo", self)
        toolbar.addAction(self.open_action)
        toolbar.addAction(self.undo_action)
        toolbar.addAction(self.commit_action)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems([ExecutionMode.IMMEDIATE.value, ExecutionMode.BATCH.value])
        self.mode_combo.setCurrentText(self.state.config.execution_mode.value)
        toolbar.addWidget(QLabel(" Mode "))
        toolbar.addWidget(self.mode_combo)

        self.filter_combo = QComboBox()
        self._refresh_filter_combo()
        toolbar.addWidget(QLabel(" View "))
        toolbar.addWidget(self.filter_combo)

        self.sort_combo = QComboBox()
        self.sort_combo.addItem("Name", SortOrder.NAME.value)
        self.sort_combo.addItem("Newest", SortOrder.NEWEST.value)
        self.sort_combo.addItem("Oldest", SortOrder.OLDEST.value)
        sort_index = self.sort_combo.findData(self.state.config.sort_order.value)
        self.sort_combo.setCurrentIndex(max(0, sort_index))
        toolbar.addWidget(QLabel(" Sort "))
        toolbar.addWidget(self.sort_combo)

        self.image_label = QLabel("Open a source folder to begin")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumSize(640, 420)
        self.image_label.setStyleSheet("background: #15171a; color: #e8eaed;")
        self.image_label.setScaledContents(False)

        self.video_widget.hide()
        self.play_button = QPushButton("Play")
        self.position_slider = QSlider(Qt.Orientation.Horizontal)
        self.position_slider.setRange(0, 0)
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(60)
        self.audio.setVolume(0.6)
        self.duration_label = QLabel("00:00 / 00:00")

        controls = QHBoxLayout()
        controls.addWidget(self.play_button)
        controls.addWidget(self.position_slider, 1)
        controls.addWidget(QLabel("Volume"))
        controls.addWidget(self.volume_slider)
        controls.addWidget(self.duration_label)

        self.file_name_label = QLabel("")
        self.file_path_label = QLabel("")
        self.file_path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.progress_label = QLabel("0 / 0")
        self.pending_label = QLabel("Pending actions: 0")
        self.action_feedback_label = QLabel("")
        self.action_feedback_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.action_feedback_label.setMinimumHeight(56)
        self.action_feedback_label.setStyleSheet(
            "font-size: 32px; font-weight: 800; color: #ffffff; "
            "background: #2f6f5e; border-radius: 6px; padding: 8px;"
        )
        self.action_feedback_label.hide()

        preview_layout = QVBoxLayout()
        preview_layout.addWidget(self.image_label, 1)
        preview_layout.addWidget(self.video_widget, 1)
        preview_layout.addLayout(controls)
        preview_layout.addWidget(self.file_name_label)
        preview_layout.addWidget(self.file_path_label)
        preview_layout.addWidget(self.progress_label)
        preview_layout.addWidget(self.pending_label)
        preview_layout.addWidget(self.action_feedback_label)
        preview_pane = QWidget()
        preview_pane.setLayout(preview_layout)

        self.rules_table = QTableWidget(0, 5)
        self.rules_table.setHorizontalHeaderLabels(["Key", "Category", "Target", "Action", "Count"])
        self.rules_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.rules_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.rules_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.rules_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.rules_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        add_rule = QPushButton("Add")
        edit_rule = QPushButton("Edit")
        delete_rule = QPushButton("Delete")
        add_rule.clicked.connect(self._add_rule)
        edit_rule.clicked.connect(self._edit_rule)
        delete_rule.clicked.connect(self._delete_rule)

        sidebar = QWidget()
        side_layout = QVBoxLayout(sidebar)
        side_layout.addWidget(QLabel("Classification Rules"))
        side_layout.addWidget(self.rules_table)
        side_buttons = QHBoxLayout()
        side_buttons.addWidget(add_rule)
        side_buttons.addWidget(edit_rule)
        side_buttons.addWidget(delete_rule)
        side_layout.addLayout(side_buttons)

        splitter = QSplitter()
        splitter.addWidget(preview_pane)
        splitter.addWidget(sidebar)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)
        self.setStatusBar(QStatusBar())
        self._refresh_rules_table()

    def _bind_actions(self) -> None:
        self.open_action.triggered.connect(self._choose_source_folder)
        self.commit_action.triggered.connect(self._commit_batch)
        self.undo_action.triggered.connect(self._undo)
        self.mode_combo.currentTextChanged.connect(self._set_mode)
        self.filter_combo.currentTextChanged.connect(self._set_filter)
        self.sort_combo.currentIndexChanged.connect(self._set_sort_order)
        self.play_button.clicked.connect(self._toggle_playback)
        self.position_slider.sliderMoved.connect(self.player.setPosition)
        self.volume_slider.valueChanged.connect(lambda value: self.audio.setVolume(value / 100))

    def _install_shortcuts(self) -> None:
        for shortcut in self.shortcuts:
            shortcut.setParent(None)
        self.shortcuts = []
        fixed = {
            QKeySequence("Right"): self._next_item,
            QKeySequence("Left"): self._previous_item,
            QKeySequence("Ctrl+Z"): self._undo,
            QKeySequence("Space"): self._toggle_playback,
            QKeySequence("Ctrl+Return"): self._commit_batch,
            QKeySequence("Ctrl+Enter"): self._commit_batch,
        }
        for sequence, handler in fixed.items():
            shortcut = QShortcut(sequence, self)
            shortcut.activated.connect(handler)
            self.shortcuts.append(shortcut)
        for rule in self.state.config.rules:
            if not rule.key:
                continue
            shortcut = QShortcut(QKeySequence(rule.key), self)
            shortcut.activated.connect(lambda checked=False, key=rule.key: self._apply_rule(key))
            self.shortcuts.append(shortcut)

    def _restore_if_possible(self) -> None:
        source_dir = self.state.config.source_dir
        if source_dir and Path(source_dir).exists():
            restored = load_session(source_dir)
            self.state = restored
            if self.state.media_items:
                self.state.media_items = self._sorted_items(self.state.media_items)
                self.state.media_items = merge_catalog(source_dir, self.state.media_items)
            self.mode_combo.setCurrentText(self.state.config.execution_mode.value)
            sort_index = self.sort_combo.findData(self.state.config.sort_order.value)
            self.sort_combo.setCurrentIndex(max(0, sort_index))
            self.preview_cache.limit = self.state.config.image_preview_cache_limit
            self.video_thumbnail_cache.limit = self.state.config.video_thumbnail_cache_limit
            self._refresh_rules_table()
            self._install_shortcuts()
            self._show_current_item()

    def _choose_source_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose source folder")
        if not folder:
            return
        self.state = load_session(folder)
        self.state.config.source_dir = folder
        self._start_scan(folder)

    def _start_scan(self, folder: str) -> None:
        self.is_scanning = True
        self.open_action.setEnabled(False)
        self.image_label.show()
        self.video_widget.hide()
        self.image_label.setText("Scanning media files...")
        self.file_name_label.setText("")
        self.file_path_label.setText(folder)
        self.progress_label.setText("Loading...")
        self.pending_label.setText("")
        self.statusBar().showMessage("Scanning media files in background...")
        self.scan_pool.start(ScanTask(folder, self.state.config.sort_order, self.scan_signals))

    def _on_scan_finished(self, folder: str, scanned_items: list[MediaItem]) -> None:
        if folder != self.state.config.source_dir:
            return
        saved_by_path = {item.file_path: item for item in self.state.media_items}
        for index, item in enumerate(scanned_items):
            saved = saved_by_path.get(item.file_path)
            if saved:
                scanned_items[index] = MediaItem.from_dict({**item.to_dict(), **saved.to_dict(), "file_path": item.file_path})
        self.state.media_items = self._sorted_items(scanned_items)
        self.state.current_index = min(self.state.current_index, max(0, len(self.state.media_items) - 1))
        self.preview_cache.clear()
        self.video_thumbnail_cache.clear()
        self.preview_cache.limit = self.state.config.image_preview_cache_limit
        self.video_thumbnail_cache.limit = self.state.config.video_thumbnail_cache_limit
        self.mode_combo.setCurrentText(self.state.config.execution_mode.value)
        self._refresh_rules_table()
        self._install_shortcuts()
        self._show_current_item()
        self._save_session()
        self.is_scanning = False
        self.open_action.setEnabled(True)
        self.statusBar().showMessage(f"Loaded {len(self.state.media_items)} media files", 3500)

    def _on_scan_failed(self, folder: str, error: str) -> None:
        if folder != self.state.config.source_dir:
            return
        self.is_scanning = False
        self.open_action.setEnabled(True)
        self.image_label.setText("Scan failed")
        QMessageBox.critical(self, "Scan failed", error)

    def _current_item(self) -> MediaItem | None:
        if not self.state.media_items:
            return None
        self.state.current_index = max(0, min(self.state.current_index, len(self.state.media_items) - 1))
        if not self._is_visible_in_filter(self.state.media_items[self.state.current_index]):
            next_index = self._find_visible_index(self.state.current_index, 1)
            if next_index is None:
                next_index = self._find_visible_index(self.state.current_index, -1)
            if next_index is None:
                return None
            self.state.current_index = next_index
        self.view_positions[self.media_filter] = self.state.media_items[self.state.current_index].file_path
        return self.state.media_items[self.state.current_index]

    def _is_visible_in_filter(self, item: MediaItem) -> bool:
        if self.media_filter == "all":
            return True
        if self.media_filter == "uncategorized":
            return item.status in {ItemStatus.UNPROCESSED, ItemStatus.SKIPPED}
        if self.media_filter.startswith("rule:"):
            return item.assigned_rule == self.media_filter.removeprefix("rule:")
        return True

    def _filter_label(self) -> str:
        if self.media_filter == "all":
            return "all"
        if self.media_filter == "uncategorized":
            return "uncategorized"
        if self.media_filter.startswith("rule:"):
            key = self.media_filter.removeprefix("rule:")
            rule = next((candidate for candidate in self.state.config.rules if candidate.key == key), None)
            return rule.label if rule else key
        return self.media_filter

    def _find_visible_index(self, start: int, direction: int) -> int | None:
        index = start
        while 0 <= index < len(self.state.media_items):
            if self._is_visible_in_filter(self.state.media_items[index]):
                return index
            index += direction
        return None

    def _show_current_item(self) -> None:
        item = self._current_item()
        self.player.stop()
        if not item:
            self.image_label.show()
            self.video_widget.hide()
            message = "No uncategorized media in this view" if self.state.media_items else "No supported media found"
            self.image_label.setText(message)
            self.file_name_label.setText("")
            self.file_path_label.setText("")
            self.progress_label.setText("0 / 0")
            self._update_pending_label()
            return

        self.file_name_label.setText(item.file_name)
        self.file_path_label.setText(item.file_path)
        self.progress_label.setText(self._progress_text())
        self._update_pending_label()

        if item.file_type == MediaType.IMAGE:
            self.video_widget.hide()
            self.image_label.show()
            pixmap = self.preview_cache.get(item.file_path)
            if pixmap:
                self._set_image_pixmap(pixmap)
            else:
                self.image_label.setText("Loading preview...")
                self.preview_cache.request(item.file_path, self.image_label.size())
        else:
            self.video_widget.hide()
            self.image_label.show()
            thumbnail = self.video_thumbnail_cache.get(item.file_path)
            if thumbnail:
                self._set_image_pixmap(thumbnail)
            else:
                self.image_label.setText("Loading video thumbnail...")
                self.video_thumbnail_cache.request(item.file_path, self.image_label.size())
            self.player.setSource(QUrl.fromLocalFile(item.file_path))
            if item.duration is None or item.video_width is None:
                metadata = probe_video(item.file_path)
                item.duration = metadata["duration"]
                item.video_width = metadata["width"]
                item.video_height = metadata["height"]
            self.duration_label.setText(self._duration_text(0, int((item.duration or 0) * 1000)))

        self._maybe_preload()
        self._save_session()

    def _set_image_pixmap(self, pixmap: QPixmap) -> None:
        scaled = pixmap.scaled(
            self.image_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.image_label.setPixmap(scaled)

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().resizeEvent(event)
        item = self._current_item()
        if item and item.file_type == MediaType.IMAGE:
            pixmap = self.preview_cache.get(item.file_path)
            if pixmap:
                self._set_image_pixmap(pixmap)
        elif item and item.file_type == MediaType.VIDEO and self.image_label.isVisible():
            pixmap = self.video_thumbnail_cache.get(item.file_path)
            if pixmap:
                self._set_image_pixmap(pixmap)

    def _maybe_preload(self) -> None:
        cfg = self.state.config
        start = self.state.current_index
        self.preview_cache.preload_window(self.state.media_items, start, cfg.batch_size, self.image_label.size())
        if cfg.batch_size and start % cfg.batch_size >= cfg.preload_threshold:
            self.preview_cache.preload_window(
                self.state.media_items,
                start + cfg.batch_size,
                cfg.batch_size,
                self.image_label.size(),
            )
        self.preview_cache.prune_around(self.state.media_items, start, cfg.cache_back_count, cfg.max_cache_count)

    def _on_preview_loaded(self, path: str, pixmap: QPixmap, width: int, height: int) -> None:
        for item in self.state.media_items:
            if item.file_path == path:
                item.image_width = width
                item.image_height = height
                break
        current = self._current_item()
        if current and current.file_path == path:
            self._set_image_pixmap(pixmap)

    def _on_preview_failed(self, path: str, error: str) -> None:
        current = self._current_item()
        if current and current.file_path == path:
            self.image_label.setText(f"Preview failed: {error}")

    def _on_video_thumbnail_loaded(self, path: str, pixmap: QPixmap) -> None:
        current = self._current_item()
        if current and current.file_path == path and current.file_type == MediaType.VIDEO:
            if self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
                self.video_widget.hide()
                self.image_label.show()
                self._set_image_pixmap(pixmap)

    def _on_video_thumbnail_failed(self, path: str, error: str) -> None:
        current = self._current_item()
        if current and current.file_path == path and current.file_type == MediaType.VIDEO:
            self.image_label.setText("Video thumbnail unavailable. Press Play to preview.")

    def _apply_rule(self, key: str) -> None:
        item = self._current_item()
        rule = next((candidate for candidate in self.state.config.rules if candidate.key == key), None)
        if not item or not rule:
            return
        if rule.action != RuleAction.SKIP and not rule.target_dir:
            QMessageBox.warning(self, "Missing target", f"Rule '{rule.label}' needs a target folder.")
            return

        record = ActionRecord(
            source_path=item.file_path,
            rule_key=rule.key,
            action=rule.action,
            previous_index=self.state.current_index,
            item_index=self.state.current_index,
            previous_status=item.status,
        )
        if self.state.config.execution_mode == ExecutionMode.IMMEDIATE:
            try:
                record.dest_path = execute_file_action(
                    item.file_path,
                    rule.target_dir,
                    rule.action,
                    self.state.config.conflict_strategy,
                )
            except Exception as exc:
                QMessageBox.critical(self, "Action failed", str(exc))
                return
            item.status = self._status_for_action(rule.action)
            self.state.undo_history.append(record)
            self.statusBar().showMessage(self._action_message(item, rule, record, planned=False), 3500)
            self._show_action_feedback(rule, planned=False)
        else:
            item.status = ItemStatus.PENDING if rule.action != RuleAction.SKIP else ItemStatus.SKIPPED
            self._replace_pending(record)
            self.state.undo_history.append(record)
            self.statusBar().showMessage(self._action_message(item, rule, record, planned=True), 3500)
            self._show_action_feedback(rule, planned=True)

        item.assigned_rule = rule.key
        rule.processed_count += 1
        self._next_item(save=False)
        self._refresh_rules_table()
        self._save_session()

    def _action_message(
        self,
        item: MediaItem,
        rule: SortRule,
        record: ActionRecord,
        planned: bool,
    ) -> str:
        if rule.action == RuleAction.SKIP:
            verb = "Planned skip" if planned else "Skipped"
            return f"{verb}: {item.file_name}"
        if planned:
            return f"Planned {rule.action.value}: {item.file_name} -> {rule.label}"
        if record.dest_path:
            return f"{rule.action.value.title()}: {item.file_name} -> {rule.label}"
        return f"{rule.action.value.title()} skipped existing file: {item.file_name}"

    def _show_action_feedback(self, rule: SortRule, planned: bool) -> None:
        if rule.action == RuleAction.SKIP:
            text = "SKIPPED"
            color = "#6d7178"
        else:
            text = rule.label.upper()
            color = "#2f6f5e" if rule.action == RuleAction.COPY else "#7c5c2e"
        self.action_feedback_label.setText(text)
        self.action_feedback_label.setStyleSheet(
            f"font-size: 32px; font-weight: 800; color: #ffffff; "
            f"background: {color}; border-radius: 6px; padding: 8px;"
        )
        self.action_feedback_label.show()
        self.feedback_timer.start(1800)

    def _hide_action_feedback(self) -> None:
        self.action_feedback_label.hide()

    def _replace_pending(self, record: ActionRecord) -> None:
        self.state.pending_actions = [
            pending for pending in self.state.pending_actions if pending.item_index != record.item_index
        ]
        self.state.pending_actions.append(record)

    def _status_for_action(self, action: RuleAction) -> ItemStatus:
        if action == RuleAction.COPY:
            return ItemStatus.COPIED
        if action == RuleAction.MOVE:
            return ItemStatus.MOVED
        return ItemStatus.SKIPPED

    def _next_item(self, save: bool = True) -> None:
        next_index = self._find_visible_index(self.state.current_index + 1, 1)
        if next_index is not None:
            self.state.current_index = next_index
            self._show_current_item()
        if save:
            self._save_session()

    def _previous_item(self) -> None:
        previous_index = self._find_visible_index(self.state.current_index - 1, -1)
        if previous_index is not None:
            self.state.current_index = previous_index
            self._show_current_item()

    def _undo(self) -> None:
        if not self.state.undo_history:
            return
        record = self.state.undo_history.pop()
        if self.state.config.execution_mode == ExecutionMode.IMMEDIATE:
            undo_file_action(record)
        else:
            self.state.pending_actions = [
                pending for pending in self.state.pending_actions if pending.item_index != record.item_index
            ]
        if 0 <= record.item_index < len(self.state.media_items):
            item = self.state.media_items[record.item_index]
            item.status = record.previous_status
            item.assigned_rule = None
        rule = next((candidate for candidate in self.state.config.rules if candidate.key == record.rule_key), None)
        if rule and rule.processed_count > 0:
            rule.processed_count -= 1
        self.state.current_index = record.previous_index
        self._refresh_rules_table()
        self._show_current_item()
        self._save_session()

    def _commit_batch(self) -> None:
        if not self.state.pending_actions:
            return
        failures: list[str] = []
        skipped_existing = 0
        actions = list(self.state.pending_actions)
        progress = QProgressDialog("Committing batch actions...", "Cancel", 0, len(actions), self)
        progress.setWindowTitle("Commit Batch")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        completed_records: list[ActionRecord] = []
        for index, record in enumerate(actions, start=1):
            progress.setLabelText(f"Processing {index} / {len(actions)}\n{Path(record.source_path).name}")
            progress.setValue(index - 1)
            if progress.wasCanceled():
                break
            rule = next((candidate for candidate in self.state.config.rules if candidate.key == record.rule_key), None)
            if not rule:
                failures.append(f"{Path(record.source_path).name}: missing rule")
                continue
            try:
                strategy = (
                    ConflictStrategy.SKIP_EXISTING
                    if record.action == RuleAction.COPY
                    else self.state.config.conflict_strategy
                )
                record.dest_path = execute_file_action(
                    record.source_path,
                    rule.target_dir,
                    record.action,
                    strategy,
                )
                if record.action == RuleAction.COPY and record.dest_path is None:
                    skipped_existing += 1
                if 0 <= record.item_index < len(self.state.media_items):
                    self.state.media_items[record.item_index].status = self._status_for_action(record.action)
                completed_records.append(record)
            except Exception as exc:
                failures.append(f"{Path(record.source_path).name}: {exc}")
        progress.setValue(len(actions))
        completed_ids = {record.item_index for record in completed_records}
        self.state.pending_actions = [
            record for record in self.state.pending_actions if record.item_index not in completed_ids
        ]
        self._update_pending_label()
        self._save_session()
        if failures:
            QMessageBox.warning(self, "Batch completed with errors", "\n".join(failures[:20]))
        elif self.state.pending_actions:
            QMessageBox.information(self, "Batch paused", "Commit was canceled. Remaining actions are still pending.")
        elif skipped_existing:
            QMessageBox.information(
                self,
                "Batch committed",
                f"Batch complete. Skipped {skipped_existing} copy action(s) because the destination file already exists.",
            )
        else:
            QMessageBox.information(self, "Batch committed", "All pending actions were applied.")

    def _set_mode(self, text: str) -> None:
        self.state.config.execution_mode = ExecutionMode(text)
        self._update_pending_label()
        self._save_session()

    def _set_filter(self, text: str) -> None:
        current = self._current_item()
        if current:
            self.view_positions[self.media_filter] = current.file_path
        selected = self.filter_combo.currentData()
        self.media_filter = selected if selected else "all"
        saved_path = self.view_positions.get(self.media_filter)
        if saved_path:
            for index, item in enumerate(self.state.media_items):
                if item.file_path == saved_path and self._is_visible_in_filter(item):
                    self.state.current_index = index
                    break
            else:
                first_index = self._find_visible_index(0, 1)
                if first_index is not None:
                    self.state.current_index = first_index
        else:
            first_index = self._find_visible_index(self.state.current_index, 1)
            if first_index is None:
                first_index = self._find_visible_index(0, 1)
            if first_index is not None:
                self.state.current_index = first_index
        self._show_current_item()

    def _refresh_filter_combo(self) -> None:
        if not hasattr(self, "filter_combo"):
            return
        current_filter = self.media_filter
        valid_filters = {"all", "uncategorized"}
        self.filter_combo.blockSignals(True)
        self.filter_combo.clear()
        self.filter_combo.addItem("All", "all")
        self.filter_combo.addItem("Uncategorized", "uncategorized")
        for rule in self.state.config.rules:
            value = f"rule:{rule.key}"
            valid_filters.add(value)
            self.filter_combo.addItem(rule.label, value)
        if current_filter not in valid_filters:
            current_filter = "all"
            self.media_filter = "all"
        index = self.filter_combo.findData(current_filter)
        self.filter_combo.setCurrentIndex(max(0, index))
        self.filter_combo.blockSignals(False)

    def _set_sort_order(self) -> None:
        selected = self.sort_combo.currentData()
        if not selected:
            return
        current = self._current_item()
        current_path = current.file_path if current else None
        self.state.config.sort_order = SortOrder(selected)
        self.state.media_items = self._sorted_items(self.state.media_items)
        if current_path:
            for index, item in enumerate(self.state.media_items):
                if item.file_path == current_path:
                    self.state.current_index = index
                    break
        self._show_current_item()
        self._save_session()

    def _sorted_items(self, items: list[MediaItem]) -> list[MediaItem]:
        if self.state.config.sort_order == SortOrder.NEWEST:
            sorted_items = sorted(items, key=lambda item: (item.modified_time, item.file_path.lower()), reverse=True)
        elif self.state.config.sort_order == SortOrder.OLDEST:
            sorted_items = sorted(items, key=lambda item: (item.modified_time, item.file_path.lower()))
        else:
            sorted_items = sorted(items, key=lambda item: item.file_path.lower())
        for index, item in enumerate(sorted_items):
            item.current_index = index
        return sorted_items

    def _add_rule(self) -> None:
        dialog = RuleDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            rule = dialog.rule()
            if self._valid_rule(rule):
                self.state.config.rules.append(rule)
                self._refresh_rules_table()
                self._install_shortcuts()
                self._save_session()

    def _edit_rule(self) -> None:
        row = self.rules_table.currentRow()
        if row < 0 or row >= len(self.state.config.rules):
            return
        existing = self.state.config.rules[row]
        dialog = RuleDialog(self, existing)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            updated = dialog.rule(processed_count=existing.processed_count)
            if self._valid_rule(updated, ignore_row=row):
                self.state.config.rules[row] = updated
                self._refresh_rules_table()
                self._install_shortcuts()
                self._save_session()

    def _delete_rule(self) -> None:
        row = self.rules_table.currentRow()
        if row < 0 or row >= len(self.state.config.rules):
            return
        del self.state.config.rules[row]
        self._refresh_rules_table()
        self._install_shortcuts()
        self._save_session()

    def _valid_rule(self, rule: SortRule, ignore_row: int | None = None) -> bool:
        if not rule.key or not rule.label:
            QMessageBox.warning(self, "Invalid rule", "Shortcut and category are required.")
            return False
        if rule.action != RuleAction.SKIP and not rule.target_dir:
            QMessageBox.warning(self, "Invalid rule", "Copy/Move rules need a target folder.")
            return False
        for index, existing in enumerate(self.state.config.rules):
            if ignore_row == index:
                continue
            if existing.key == rule.key:
                QMessageBox.warning(self, "Invalid rule", f"Shortcut '{rule.key}' is already used.")
                return False
        return True

    def _refresh_rules_table(self) -> None:
        self.rules_table.setRowCount(len(self.state.config.rules))
        for row, rule in enumerate(self.state.config.rules):
            values = [
                rule.key,
                rule.label,
                rule.target_dir or "N/A",
                rule.action.value,
                str(rule.processed_count),
            ]
            for col, value in enumerate(values):
                self.rules_table.setItem(row, col, QTableWidgetItem(value))
        self._refresh_filter_combo()
        self._update_pending_label()

    def _update_pending_label(self) -> None:
        pending = len(self.state.pending_actions)
        skipped = sum(1 for action in self.state.pending_actions if action.action == RuleAction.SKIP)
        copied = sum(1 for action in self.state.pending_actions if action.action == RuleAction.COPY)
        moved = sum(1 for action in self.state.pending_actions if action.action == RuleAction.MOVE)
        current = self._current_item()
        detail = file_size_label(current.file_path) if current else ""
        self.pending_label.setText(
            f"Pending actions: {pending} | Skipped: {skipped} | Copy planned: {copied} | Move planned: {moved} | {detail}"
        )

    def _progress_text(self) -> str:
        if self.media_filter == "all":
            return f"{self.state.current_index + 1} / {len(self.state.media_items)}"
        visible = [
            index
            for index, item in enumerate(self.state.media_items)
            if self._is_visible_in_filter(item)
        ]
        if not visible:
            return f"0 / 0 {self._filter_label()} ({len(self.state.media_items)} total)"
        position = visible.index(self.state.current_index) + 1 if self.state.current_index in visible else 0
        return f"{position} / {len(visible)} {self._filter_label()} ({len(self.state.media_items)} total)"

    def _toggle_playback(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            self.play_button.setText("Play")
        else:
            current = self._current_item()
            if current and current.file_type == MediaType.VIDEO:
                self.image_label.hide()
                self.video_widget.show()
            self.player.play()
            self.play_button.setText("Pause")

    def _sync_duration(self, duration: int) -> None:
        self.position_slider.setRange(0, duration)
        self.duration_label.setText(self._duration_text(self.player.position(), duration))

    def _sync_position(self, position: int) -> None:
        self.position_slider.setValue(position)
        self.duration_label.setText(self._duration_text(position, self.player.duration()))

    def _duration_text(self, position_ms: int, duration_ms: int) -> str:
        return f"{self._mmss(position_ms)} / {self._mmss(duration_ms)}"

    def _mmss(self, value_ms: int) -> str:
        seconds = max(0, value_ms // 1000)
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    def _save_session(self) -> None:
        save_session(self.state)
        save_catalog(self.state.config.source_dir, self.state.media_items)

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self._save_session()
        super().closeEvent(event)
