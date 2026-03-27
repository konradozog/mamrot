"""Mamrot – Cutter tab (Qt) with cut queue management & execution."""

import json
import os
from typing import Optional, List

from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, Signal, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
    QPushButton, QTableView, QHeaderView, QAbstractItemView,
    QFileDialog, QProgressBar, QComboBox, QSpinBox, QCheckBox,
)
from PySide6.QtCore import QEvent
from PySide6.QtGui import QColor

from ..core.models import CutJob, fmt_ts
from ..core.cutter import CutterEngine, OUTPUT_FORMATS, _apply_padding, _slugify
from .theme import (
    ACCENT, ACCENT_LIGHT, TEXT, TEXT2, TEXT3,
    SUCCESS, ERROR, ELEVATED, SELECTED_BG,
    SURFACE, SURFACE2, SURFACE3, BORDER, BORDER_HOVER,
    ACCENT_DIM, ACCENT_TEXT, SUCCESS_DIM,
    R_MD, R_LG, R_XL, SP_SM, SP_MD, SP_LG, SP_XL,
    FONT_FAMILY, MONO_FAMILY, BG,
)
# Legacy aliases
TEXT_PRIMARY = TEXT
TEXT_SECONDARY = TEXT2
TEXT_MUTED = TEXT3
BG_ELEVATED = ELEVATED
from .audio_preview import AudioPreview

_CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".mamrot", "cutter.json")


def _load_cutter_config() -> dict:
    try:
        with open(_CONFIG_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cutter_config(output_dir: str, output_fmt: str):
    try:
        os.makedirs(os.path.dirname(_CONFIG_PATH), exist_ok=True)
        with open(_CONFIG_PATH, "w") as f:
            json.dump({"output_dir": output_dir, "output_fmt": output_fmt}, f)
    except Exception:
        pass


# ── Queue table model ─────────────────────────────────────────

class QueueTableModel(QAbstractTableModel):
    COLUMNS = ["#", "Range", "Dur", "Label", "Status"]
    COL_IDX, COL_RANGE, COL_DUR, COL_LABEL, COL_STATUS = range(5)

    def __init__(self, engine: CutterEngine, parent=None):
        super().__init__(parent)
        self.engine = engine

    def rowCount(self, parent=QModelIndex()):
        return len(self.engine.queue)

    def columnCount(self, parent=QModelIndex()):
        return len(self.COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.COLUMNS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = index.row()
        col = index.column()
        if row >= len(self.engine.queue):
            return None
        job = self.engine.queue[row]

        if role == Qt.DisplayRole:
            if col == self.COL_IDX:
                return str(row + 1)
            elif col == self.COL_RANGE:
                return f"{fmt_ts(job.start)} -> {fmt_ts(job.end)}"
            elif col == self.COL_DUR:
                _, adj_s, adj_e = _apply_padding(job.label, job.start, job.end)
                return f"{adj_e - adj_s:.1f}s"
            elif col == self.COL_LABEL:
                return job.label[:80]
            elif col == self.COL_STATUS:
                return {"queued": "Queued", "cutting": "Cutting...",
                        "done": "Done", "error": "Error"}.get(job.status, job.status)

        elif role == Qt.ForegroundRole:
            if col == self.COL_RANGE:
                return QColor(ACCENT_LIGHT)
            elif col == self.COL_IDX:
                return QColor(TEXT_MUTED)
            elif col == self.COL_DUR:
                return QColor(TEXT_MUTED)
            elif col == self.COL_STATUS:
                color = {"queued": TEXT_MUTED, "cutting": ACCENT,
                         "done": SUCCESS, "error": ERROR}.get(job.status, TEXT_MUTED)
                return QColor(color)
            return QColor(TEXT_PRIMARY)

        elif role == Qt.ToolTipRole:
            if col == self.COL_LABEL:
                return f"{os.path.basename(job.source_path)}\n{job.label}"
            if col == self.COL_STATUS and job.status == "error":
                return job.error

        elif role == Qt.BackgroundRole:
            if job.status == "done":
                return QColor(SELECTED_BG)

        return None

    def refresh(self):
        self.beginResetModel()
        self.endResetModel()

    def refresh_row(self, row: int):
        if 0 <= row < len(self.engine.queue):
            tl = self.index(row, 0)
            br = self.index(row, self.columnCount() - 1)
            self.dataChanged.emit(tl, br)


# ── Cutter tab widget ────────────────────────────────────────

class CutterTab(QWidget):
    """Cut queue — shows queued jobs, lets user pick output dir, and execute."""

    # Signals for thread-safe callbacks from CutterEngine
    _sig_job_start = Signal(int, int)   # (job_index, total)
    _sig_job_done = Signal(int)         # (job_index,)
    _sig_job_error = Signal(int, str)   # (job_index, error)
    _sig_all_done = Signal(int, int)    # (done_count, error_count)

    def __init__(self, engine: CutterEngine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self._preview = AudioPreview()
        cfg = _load_cutter_config()
        self.output_dir = cfg.get("output_dir", "")
        self._output_fmt = cfg.get("output_fmt", "wav")

        self._queue_model = QueueTableModel(engine, self)
        self._setup_ui()
        self._connect_signals()
        self._check_ready()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)

        # ── Toolbar: Output folder + format ───────────
        toolbar = QWidget()
        toolbar.setObjectName("cutterToolbar")
        toolbar.setStyleSheet(f"#cutterToolbar {{ border-bottom: 1px solid {BORDER}; }}")
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(SP_XL, SP_MD, SP_XL, SP_MD)
        tb_layout.setSpacing(SP_MD)

        folder_icon = QLabel("📁")
        folder_icon.setStyleSheet("font-size: 14px;")
        dir_text = self.output_dir if self.output_dir else "No output folder"
        self.dir_label = QLabel(dir_text)
        self.dir_label.setStyleSheet(
            f"color: {TEXT2 if self.output_dir else TEXT3}; font-size: 12px;"
        )
        self.btn_pick_dir = QPushButton("Change...")
        self.btn_pick_dir.setProperty("ghost", True)

        self.fmt_combo = QComboBox()
        fmt_labels = {
            "wav": "WAV",
            "flac": "FLAC",
            "mp3": "MP3",
            "ogg": "OGG",
            "aac": "AAC",
            "opus": "Opus",
        }
        for key in OUTPUT_FORMATS:
            self.fmt_combo.addItem(fmt_labels.get(key, key.upper()), key)
        for i in range(self.fmt_combo.count()):
            if self.fmt_combo.itemData(i) == self._output_fmt:
                self.fmt_combo.setCurrentIndex(i)
                break
        self.fmt_combo.setFixedWidth(100)

        fmt_label = QLabel("Format")
        fmt_label.setStyleSheet(f"color: {TEXT3}; font-size: 11px;")

        tb_layout.addWidget(folder_icon)
        tb_layout.addWidget(self.dir_label, 1)
        tb_layout.addWidget(self.btn_pick_dir)
        tb_layout.addStretch()
        tb_layout.addWidget(fmt_label)
        tb_layout.addWidget(self.fmt_combo)
        layout.addWidget(toolbar)

        # ── Queue header ─────────────────────────────
        self.queue_count_label = QLabel("Queue is empty")
        self.queue_count_label.setStyleSheet(f"color: {TEXT3}; font-size: 11px;")

        # ── Queue table ──────────────────────────────
        self.table = QTableView()
        self.table.setModel(self._queue_model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(False)

        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(self._queue_model.COL_IDX, QHeaderView.Fixed)
        hdr.setSectionResizeMode(self._queue_model.COL_RANGE, QHeaderView.Fixed)
        hdr.setSectionResizeMode(self._queue_model.COL_DUR, QHeaderView.Fixed)
        hdr.setSectionResizeMode(self._queue_model.COL_LABEL, QHeaderView.Stretch)
        hdr.setSectionResizeMode(self._queue_model.COL_STATUS, QHeaderView.Fixed)
        self.table.setColumnWidth(self._queue_model.COL_IDX, 36)
        self.table.setColumnWidth(self._queue_model.COL_RANGE, 180)
        self.table.setColumnWidth(self._queue_model.COL_DUR, 55)
        self.table.setColumnWidth(self._queue_model.COL_STATUS, 80)

        layout.addWidget(self.table, 1)

        # ── Progress bar (shown during cutting) ──────
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        self.progress_bar.setFixedHeight(5)
        layout.addWidget(self.progress_bar)

        # ── Done banner ──────────────────────────────
        self.done_frame = QWidget()
        self.done_frame.setStyleSheet(f"""
            QWidget {{ background: {SUCCESS_DIM}; border-top: 1px solid rgba(125,211,160,0.15); }}
        """)
        df_layout = QHBoxLayout(self.done_frame)
        df_layout.setContentsMargins(SP_XL, SP_MD, SP_XL, SP_MD)
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet(f"color: {TEXT2}; font-size: 12px;")
        df_layout.addWidget(self.status_label)
        self.done_frame.setVisible(False)
        layout.addWidget(self.done_frame)

        # ── Footer: preview + actions ─────────────────
        footer = QWidget()
        footer.setObjectName("cutterFooter")
        footer.setStyleSheet(f"#cutterFooter {{ border-top: 1px solid {BORDER}; }}")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(SP_XL, SP_MD, SP_XL, SP_MD)
        footer_layout.setSpacing(10)

        # Preview
        self.btn_preview = QPushButton("▶ Preview")
        self.btn_preview.setFixedWidth(90)
        self.btn_preview.setStyleSheet(f"""
            QPushButton {{ background: {SURFACE3}; border: none; border-radius: 16px;
                           padding: 6px 14px; color: {TEXT2}; font-size: 12px; }}
            QPushButton:hover {{ background: {ELEVATED}; color: {TEXT}; }}
        """)
        self.btn_stop = QPushButton("■ Stop")
        self.btn_stop.setFixedWidth(60)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setStyleSheet(f"""
            QPushButton {{ background: transparent; border: none; color: {TEXT3};
                           font-size: 12px; padding: 6px 10px; }}
            QPushButton:hover {{ color: {TEXT2}; }}
        """)
        self.preview_label = QLabel("")
        self.preview_label.setFixedWidth(220)
        self.preview_label.setStyleSheet(f"color: {TEXT3}; font-size: 11px;")

        # Offsets
        start_lbl = QLabel("Start:")
        start_lbl.setStyleSheet(f"color: {TEXT3}; font-size: 11px;")
        self.offset_start_spin = QSpinBox()
        self.offset_start_spin.setRange(-2000, 2000)
        self.offset_start_spin.setSingleStep(100)
        self.offset_start_spin.setSuffix(" ms")
        self.offset_start_spin.setValue(0)
        self.offset_start_spin.setFixedWidth(110)
        self.offset_start_spin.setToolTip("Shift cut start (negative = earlier)")
        end_lbl = QLabel("End:")
        end_lbl.setStyleSheet(f"color: {TEXT3}; font-size: 11px;")
        self.offset_end_spin = QSpinBox()
        self.offset_end_spin.setRange(-2000, 2000)
        self.offset_end_spin.setSingleStep(100)
        self.offset_end_spin.setSuffix(" ms")
        self.offset_end_spin.setValue(0)
        self.offset_end_spin.setFixedWidth(110)
        self.offset_end_spin.setToolTip("Shift cut end (negative = shorter)")

        footer_layout.addWidget(self.btn_preview)
        footer_layout.addWidget(self.btn_stop)
        footer_layout.addWidget(self.preview_label)
        footer_layout.addWidget(start_lbl)
        footer_layout.addWidget(self.offset_start_spin)
        footer_layout.addWidget(end_lbl)
        footer_layout.addWidget(self.offset_end_spin)
        footer_layout.addStretch()

        # Queue actions
        self.btn_remove = QPushButton("Remove selected")
        self.btn_remove.setProperty("ghost", True)
        self.btn_clear_done = QPushButton("Clear done")
        self.btn_clear_done.setProperty("ghost", True)
        self.auto_clear_check = QCheckBox("Auto")
        self.auto_clear_check.setToolTip("Automatically clear done items after cutting")
        self.auto_clear_check.setStyleSheet(f"color: {TEXT3}; font-size: 11px;")
        self.auto_clear_check.setChecked(True)
        self.btn_clear_all = QPushButton("Clear all")
        self.btn_clear_all.setProperty("ghost", True)
        self.btn_cut_all = QPushButton("Cut all")
        self.btn_cut_all.setProperty("accent", True)
        self.btn_cut_all.setEnabled(False)
        self.btn_cut_all.setStyleSheet(f"""
            QPushButton {{
                background: {ACCENT}; color: {BG}; border: none;
                font-weight: 600; font-size: 13px;
                padding: 10px 24px; border-radius: {R_LG}px;
            }}
            QPushButton:hover {{ background: {ACCENT_LIGHT}; }}
            QPushButton:disabled {{ background: {SURFACE3}; color: {TEXT3}; }}
        """)

        footer_layout.addWidget(self.btn_remove)
        footer_layout.addWidget(self.btn_clear_done)
        footer_layout.addWidget(self.auto_clear_check)
        footer_layout.addWidget(self.btn_clear_all)
        footer_layout.addWidget(self.btn_cut_all)
        layout.addWidget(footer)

    def _connect_signals(self):
        self.btn_pick_dir.clicked.connect(self._pick_dir)
        self.fmt_combo.currentIndexChanged.connect(self._on_fmt_changed)
        self.btn_remove.clicked.connect(self._remove_selected)
        self.btn_clear_done.clicked.connect(self._clear_done)
        self.btn_clear_all.clicked.connect(self._clear_all)
        self.btn_cut_all.clicked.connect(self._cut_all)
        self.btn_preview.clicked.connect(self._preview_current)
        # Thread-safe signals for cutter callbacks
        self._sig_job_start.connect(self._ui_job_start)
        self._sig_job_done.connect(self._ui_job_done)
        self._sig_job_error.connect(self._ui_job_error)
        self._sig_all_done.connect(self._ui_all_done)
        self.btn_stop.clicked.connect(self._stop_preview)
        self.table.doubleClicked.connect(self._on_double_click)
        self.table.installEventFilter(self)
        self.offset_start_spin.valueChanged.connect(self._on_offset_changed)
        self.offset_end_spin.valueChanged.connect(self._on_offset_changed)
        self.table.selectionModel().currentRowChanged.connect(self._on_row_changed)
        self._syncing_offsets = False

    def _on_fmt_changed(self):
        self._output_fmt = self.fmt_combo.currentData()
        _save_cutter_config(self.output_dir, self._output_fmt)

    # ── Public API ────────────────────────────────────

    def add_jobs(self, jobs: List[CutJob]):
        for job in jobs:
            self.engine.add(job)

    def remove_job_by_range(self, start: float, end: float):
        self.engine.remove_by_range(start, end)

    def update_job_label(self, start: float, end: float, label: str):
        self.engine.update_label(start, end, label)

    def refresh(self):
        self._queue_model.refresh()
        self._update_queue_count()
        self._check_ready()

    # ── Dir picker ────────────────────────────────────

    def _pick_dir(self):
        path = QFileDialog.getExistingDirectory(self, "Select output folder")
        if path:
            self.output_dir = path
            self.dir_label.setText(path)
            self.dir_label.setStyleSheet(f"color: {TEXT_PRIMARY};")
            _save_cutter_config(self.output_dir, self._output_fmt)
            self._check_ready()

    # ── Queue management ──────────────────────────────

    def _remove_selected(self):
        idx = self.table.currentIndex()
        if idx.isValid():
            self.engine.remove(idx.row())
            self._queue_model.refresh()
            self._update_queue_count()
            self._check_ready()

    def _clear_done(self):
        self.engine.clear_done()
        self._queue_model.refresh()
        self._update_queue_count()
        self._check_ready()

    def _auto_clear_done(self):
        """Auto-clear after brief delay so user sees Done status."""
        self.engine.clear_done()
        self._queue_model.refresh()
        self._update_queue_count()
        self._check_ready()

    def _clear_all(self):
        self.engine.clear_all()
        self._queue_model.refresh()
        self._update_queue_count()
        self._check_ready()

    def _update_queue_count(self):
        count = len(self.engine.queue)
        pending = self.engine.pending_count
        done = self.engine.done_count
        self.queue_count_label.setText(
            f"{count} total / {pending} pending / {done} done" if count
            else "Queue is empty"
        )

    def _check_ready(self):
        ready = bool(self.output_dir) and self.engine.pending_count > 0
        self.btn_cut_all.setEnabled(ready)

    # ── Preview ───────────────────────────────────────

    def eventFilter(self, obj, event):
        if obj is self.table and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_P and not event.modifiers():
                idx = self.table.currentIndex()
                if idx.isValid():
                    self._preview_row(idx.row())
                    return True
            if event.key() == Qt.Key_Escape and self._preview.is_playing:
                self._stop_preview()
                return True
        return super().eventFilter(obj, event)

    def _on_double_click(self, index: QModelIndex):
        if index.isValid():
            self._preview_row(index.row())

    def _on_row_changed(self, current, previous):
        """Load per-job offsets into spinboxes."""
        if not current.isValid():
            return
        row = current.row()
        if row >= len(self.engine.queue):
            return
        job = self.engine.queue[row]
        self._syncing_offsets = True
        self.offset_start_spin.setValue(int(job.offset_start_ms))
        self.offset_end_spin.setValue(int(job.offset_end_ms))
        self._syncing_offsets = False
        self._update_preview_label()

    def _on_offset_changed(self):
        """Save offset to current job."""
        if self._syncing_offsets:
            return
        idx = self.table.currentIndex()
        if idx.isValid() and idx.row() < len(self.engine.queue):
            job = self.engine.queue[idx.row()]
            job.offset_start_ms = self.offset_start_spin.value()
            job.offset_end_ms = self.offset_end_spin.value()
        self._update_preview_label()

    def _preview_current(self):
        idx = self.table.currentIndex()
        if idx.isValid():
            self._preview_row(idx.row())

    def _preview_row(self, row: int):
        if row < 0 or row >= len(self.engine.queue):
            return
        job = self.engine.queue[row]
        self.btn_stop.setEnabled(True)
        off_s = self.offset_start_spin.value()
        off_e = self.offset_end_spin.value()
        _, adj_s, adj_e = _apply_padding(job.label, job.start, job.end)
        adj_s = max(0.0, adj_s + off_s / 1000.0)
        adj_e = adj_e + off_e / 1000.0
        self.preview_label.setText(
            f"Playing: {fmt_ts(adj_s)} → {fmt_ts(adj_e)} ({adj_e - adj_s:.1f}s)"
        )
        self._preview.play_segment(
            job.source_path, job.start, job.end, job.label,
            on_finished=self._on_preview_finished,
            offset_start_ms=off_s,
            offset_end_ms=off_e,
        )

    def _stop_preview(self):
        self._preview.stop()
        self._on_preview_finished()

    def _on_preview_finished(self):
        QTimer.singleShot(0, self._reset_preview_ui)

    def _reset_preview_ui(self):
        self.btn_stop.setEnabled(False)
        self._update_preview_label()

    def _update_preview_label(self):
        if self._preview.is_playing:
            return
        idx = self.table.currentIndex()
        if not idx.isValid() or idx.row() >= len(self.engine.queue):
            self.preview_label.setText("")
            return
        job = self.engine.queue[idx.row()]
        off_s = self.offset_start_spin.value()
        off_e = self.offset_end_spin.value()
        _, adj_s, adj_e = _apply_padding(job.label, job.start, job.end)
        adj_s = max(0.0, adj_s + off_s / 1000.0)
        adj_e = adj_e + off_e / 1000.0
        self.preview_label.setText(
            f"{fmt_ts(adj_s)} → {fmt_ts(adj_e)} ({adj_e - adj_s:.1f}s)"
        )

    # ── Execute cuts ──────────────────────────────────

    def _cut_all(self):
        if not self.output_dir:
            self.done_frame.setVisible(True)
            self.status_label.setText("Select output folder first!")
            self.status_label.setStyleSheet(f"color: {ERROR}; font-size: 12px;")
            self.done_frame.setStyleSheet(f"""
                QWidget {{ background: rgba(232,113,113,0.10); border-top: 1px solid rgba(232,113,113,0.15); }}
            """)
            return

        self.btn_cut_all.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.done_frame.setVisible(False)

        self._cut_total = self.engine.pending_count

        def on_start(job, i):
            self._sig_job_start.emit(i, self._cut_total)

        def on_done(job, i):
            self._sig_job_done.emit(i)

        def on_error(job, i, err):
            self._sig_job_error.emit(i, err)

        def on_all_done(done_count, error_count):
            self._sig_all_done.emit(done_count, error_count)

        self.engine.process_queue(
            output_dir=self.output_dir,
            output_fmt=self._output_fmt,
            on_job_start=on_start,
            on_job_done=on_done,
            on_job_error=on_error,
            on_all_done=on_all_done,
            offset_start_ms=self.offset_start_spin.value(),
            offset_end_ms=self.offset_end_spin.value(),
        )

    def _ui_job_start(self, i, total):
        self.progress_bar.setValue(int(i / max(total, 1) * 1000))
        self._queue_model.refresh_row(i)
        w = self.window()
        if w:
            w.setWindowTitle(f"Mamrot — Cutting {i+1}/{total}")

    def _ui_job_done(self, i):
        self._queue_model.refresh_row(i)
        self._update_queue_count()

    def _ui_job_error(self, i, err):
        self._queue_model.refresh_row(i)

    def _ui_all_done(self, done_count, error_count):
        self.progress_bar.setValue(1000)
        self.progress_bar.setVisible(False)
        self.done_frame.setVisible(True)
        if error_count > 0:
            first_err = next((j.error for j in self.engine.queue if j.status == "error"), "")
            self.status_label.setText(
                f"Done with {error_count} error(s). {done_count} files cut. "
                f"Last: {first_err[:120]}"
            )
            self.status_label.setStyleSheet(f"color: {ERROR}; font-size: 12px;")
            self.done_frame.setStyleSheet(f"""
                QWidget {{ background: rgba(232,113,113,0.10); border-top: 1px solid rgba(232,113,113,0.15); }}
            """)
        else:
            self.status_label.setText(f"Done! {done_count} files cut to {self.output_dir}")
            self.status_label.setStyleSheet(f"color: {SUCCESS}; font-size: 12px; font-weight: 500;")
            self.done_frame.setStyleSheet(f"""
                QWidget {{ background: {SUCCESS_DIM}; border-top: 1px solid rgba(125,211,160,0.15); }}
            """)
        self._queue_model.refresh()
        self._update_queue_count()
        self._check_ready()
        if self.auto_clear_check.isChecked() and any(j.status == "done" for j in self.engine.queue):
            QTimer.singleShot(800, self._auto_clear_done)
        w = self.window()
        if w:
            w.setWindowTitle("Mamrot")
