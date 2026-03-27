"""Mamrot – Editor tab (Qt) with segment table, split/merge, preview."""

import json
import os
from typing import Optional, List, Set

from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, Signal, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
    QComboBox, QLineEdit, QPushButton, QTableView, QHeaderView,
    QAbstractItemView, QFileDialog, QStyledItemDelegate, QSpinBox,
)
from PySide6.QtCore import QEvent
from PySide6.QtGui import QColor, QKeySequence, QShortcut

from ..core.models import Segment, Word, TranscribeJob, CutJob, fmt_ts, load_transcript_json
from ..core.cutter import _apply_padding
from .transcribe_tab import _load_last_input_dir, _save_last_input_dir

_RECENT_CONFIG = os.path.join(os.path.expanduser("~"), ".mamrot", "recent_transcripts.json")


def _load_recent_transcripts() -> list:
    """Return list of dicts: [{path, source, name, seg_count}, ...]"""
    try:
        with open(_RECENT_CONFIG, "r") as f:
            return json.load(f)
    except Exception:
        return []


def _save_recent_transcripts(recents: list):
    try:
        os.makedirs(os.path.dirname(_RECENT_CONFIG), exist_ok=True)
        with open(_RECENT_CONFIG, "w") as f:
            json.dump(recents[:10], f)  # keep last 10
    except Exception:
        pass
from .theme import (
    ACCENT, ACCENT_LIGHT, ACCENT_DIM, TEXT, TEXT2, TEXT3,
    HIGHLIGHT_BG, SELECTED_BG, SUCCESS, ELEVATED, SURFACE2, SURFACE3,
    BORDER, BORDER_HOVER, ACCENT_TEXT, ACCENT_GLOW,
    R_SM, R_MD, R_LG, R_XL, SP_SM, SP_MD, SP_LG, SP_XL,
    FONT_FAMILY, MONO_FAMILY, BG,
)
# Legacy aliases
TEXT_PRIMARY = TEXT
TEXT_SECONDARY = TEXT2
TEXT_MUTED = TEXT3
BG_ELEVATED = ELEVATED
from .audio_preview import AudioPreview


# ── Segment table model ─────────────────────────────────────────

class SegmentTableModel(QAbstractTableModel):
    """Model for the segment table. Columns: #, Time, Text, Duration, Queued."""

    COLUMNS = ["#", "Time", "Text", "Dur", "Q"]
    COL_IDX, COL_TIME, COL_TEXT, COL_DUR, COL_QUEUED = range(5)

    segments_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._segments: List[Segment] = []
        self._selected: Set[int] = set()  # indices of queued segments
        self._search_query: str = ""
        self._search_matches: Set[int] = set()

    # ── Qt model interface ─────────────────────────────

    def rowCount(self, parent=QModelIndex()):
        return len(self._segments)

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
        seg = self._segments[row]

        if role == Qt.DisplayRole:
            if col == self.COL_IDX:
                return str(row)
            elif col == self.COL_TIME:
                return fmt_ts(seg.start)
            elif col == self.COL_TEXT:
                return seg.text.strip()
            elif col == self.COL_DUR:
                _, adj_s, adj_e = _apply_padding(seg.text, seg.start, seg.end)
                return f"{adj_e - adj_s:.1f}s"
            elif col == self.COL_QUEUED:
                return None  # handled by CheckStateRole

        elif role == Qt.CheckStateRole:
            if col == self.COL_QUEUED:
                return Qt.Checked if row in self._selected else Qt.Unchecked

        elif role == Qt.EditRole:
            if col == self.COL_TEXT:
                return seg.text.strip()

        elif role == Qt.ForegroundRole:
            if col == self.COL_TIME:
                return QColor(ACCENT_LIGHT if row in self._selected else TEXT_SECONDARY)
            elif col == self.COL_DUR:
                has_pad = "^" in seg.text
                return QColor(ACCENT_LIGHT if has_pad else TEXT_MUTED)
            elif col == self.COL_IDX:
                return QColor(TEXT_MUTED)
            return QColor(TEXT_PRIMARY)

        elif role == Qt.BackgroundRole:
            if row in self._selected:
                return QColor(SELECTED_BG)
            if row in self._search_matches:
                return QColor(HIGHLIGHT_BG)

        elif role == Qt.ToolTipRole:
            if col == self.COL_DUR:
                _, adj_s, adj_e = _apply_padding(seg.text, seg.start, seg.end)
                return f"Padded: {fmt_ts(adj_s)} → {fmt_ts(adj_e)}"
            if col == self.COL_TEXT:
                return f"{fmt_ts(seg.start)} → {fmt_ts(seg.end)}"

        return None

    def flags(self, index):
        f = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        col = index.column()
        if col == self.COL_TEXT:
            seg = self._segments[index.row()]
            if seg.words:
                f |= Qt.ItemIsEditable
        if col == self.COL_QUEUED:
            f |= Qt.ItemIsUserCheckable
        return f

    def setData(self, index, value, role=Qt.EditRole):
        if not index.isValid():
            return False
        row = index.row()
        col = index.column()

        if role == Qt.CheckStateRole and col == self.COL_QUEUED:
            if value == Qt.Checked.value:
                self._selected.add(row)
            else:
                self._selected.discard(row)
            self.dataChanged.emit(index, index, [role, Qt.BackgroundRole, Qt.ForegroundRole])
            # Also refresh the Time column (color changes)
            time_idx = self.index(row, self.COL_TIME)
            self.dataChanged.emit(time_idx, time_idx, [Qt.ForegroundRole])
            self.segments_changed.emit()
            return True

        if role == Qt.EditRole and col == self.COL_TEXT:
            text = str(value).strip()
            if not text:
                return False  # don't allow empty (merge handled by delegate)
            self._segments[row].text = text
            self.dataChanged.emit(index, index, [role])
            # Duration may change (^ markers)
            dur_idx = self.index(row, self.COL_DUR)
            self.dataChanged.emit(dur_idx, dur_idx, [Qt.DisplayRole, Qt.ForegroundRole])
            self.segments_changed.emit()
            return True

        return False

    # ── Data access ────────────────────────────────────

    def set_segments(self, segments: List[Segment]):
        self.beginResetModel()
        self._segments = segments
        self._selected.clear()
        self._search_matches.clear()
        self._search_query = ""
        self.endResetModel()
        self.segments_changed.emit()

    def segment_at(self, row: int) -> Optional[Segment]:
        if 0 <= row < len(self._segments):
            return self._segments[row]
        return None

    @property
    def segments(self) -> List[Segment]:
        return self._segments

    @property
    def selected_rows(self) -> Set[int]:
        return self._selected

    # ── Search ─────────────────────────────────────────

    def set_search(self, query: str):
        self._search_query = query.strip().lower()
        old = set(self._search_matches)
        self._search_matches.clear()
        if self._search_query:
            for i, seg in enumerate(self._segments):
                if self._search_query in seg.text.lower():
                    self._search_matches.add(i)
        changed = old.symmetric_difference(self._search_matches)
        for row in changed:
            tl = self.index(row, 0)
            br = self.index(row, self.columnCount() - 1)
            self.dataChanged.emit(tl, br, [Qt.BackgroundRole])

    @property
    def search_matches(self) -> Set[int]:
        return self._search_matches

    # ── Selection ──────────────────────────────────────

    def select_rows(self, rows: Set[int]):
        added = rows - self._selected
        self._selected.update(rows)
        for row in added:
            tl = self.index(row, 0)
            br = self.index(row, self.columnCount() - 1)
            self.dataChanged.emit(tl, br, [Qt.BackgroundRole, Qt.ForegroundRole, Qt.CheckStateRole])
        self.segments_changed.emit()

    def deselect_all(self):
        old = set(self._selected)
        self._selected.clear()
        for row in old:
            tl = self.index(row, 0)
            br = self.index(row, self.columnCount() - 1)
            self.dataChanged.emit(tl, br, [Qt.BackgroundRole, Qt.ForegroundRole, Qt.CheckStateRole])
        self.segments_changed.emit()

    # ── Split & Merge ──────────────────────────────────

    def split_segment(self, row: int, word_split_idx: int) -> Optional[int]:
        """Split segment at word boundary. Returns new row index or None."""
        if row < 0 or row >= len(self._segments):
            return None
        seg = self._segments[row]
        if not seg.words or word_split_idx <= 0 or word_split_idx >= len(seg.words):
            return None

        words_a = seg.words[:word_split_idx]
        words_b = seg.words[word_split_idx:]
        text_a = "".join(w.text for w in words_a).strip()
        text_b = "".join(w.text for w in words_b).strip()
        if not text_a or not text_b:
            return None

        seg_a = Segment(idx=0, start=words_a[0].start, end=words_a[-1].end,
                        text=text_a, words=words_a)
        seg_b = Segment(idx=0, start=words_b[0].start, end=words_b[-1].end,
                        text=text_b, words=words_b)

        was_selected = row in self._selected
        self._selected.discard(row)
        # Shift selected rows after split point
        new_selected = set()
        for s in self._selected:
            new_selected.add(s + 1 if s > row else s)
        self._selected = new_selected

        self.beginRemoveRows(QModelIndex(), row, row)
        self._segments.pop(row)
        self.endRemoveRows()

        self.beginInsertRows(QModelIndex(), row, row + 1)
        self._segments.insert(row, seg_a)
        self._segments.insert(row + 1, seg_b)
        self.endInsertRows()

        self._reindex()
        self.segments_changed.emit()
        return row + 1

    def merge_with_previous(self, row: int) -> Optional[int]:
        """Merge row with previous. Returns merged row index or None."""
        if row <= 0 or row >= len(self._segments):
            return None
        prev = self._segments[row - 1]
        curr = self._segments[row]

        merged = Segment(
            idx=0, start=prev.start, end=curr.end,
            text=(prev.text.rstrip() + " " + curr.text.lstrip()).strip(),
            words=prev.words + curr.words,
        )

        was_sel = row in self._selected
        self._selected.discard(row)
        self._selected.discard(row - 1)
        new_selected = set()
        for s in self._selected:
            new_selected.add(s - 1 if s > row else s)
        self._selected = new_selected

        self.beginRemoveRows(QModelIndex(), row - 1, row)
        self._segments.pop(row)
        self._segments.pop(row - 1)
        self.endRemoveRows()

        self.beginInsertRows(QModelIndex(), row - 1, row - 1)
        self._segments.insert(row - 1, merged)
        self.endInsertRows()

        self._reindex()
        self.segments_changed.emit()
        return row - 1

    def merge_with_next(self, row: int) -> Optional[int]:
        """Merge row with next. Returns merged row index or None."""
        if row < 0 or row + 1 >= len(self._segments):
            return None
        return self.merge_with_previous(row + 1)

    def _reindex(self):
        for i, s in enumerate(self._segments):
            s.idx = i


# ── Text editing delegate ─────────────────────────────────────

class _SplitLineEdit(QLineEdit):
    """QLineEdit that emits split on Ctrl+Enter, merge signals on Ctrl+Backspace/Delete."""

    split_at = Signal(int)  # cursor position
    merge_prev = Signal()
    merge_next = Signal()

    def keyPressEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                self.split_at.emit(self.cursorPosition())
                return
            if event.key() == Qt.Key_Backspace:
                self.merge_prev.emit()
                return
            if event.key() == Qt.Key_Delete:
                self.merge_next.emit()
                return
        super().keyPressEvent(event)


class SegmentTextDelegate(QStyledItemDelegate):
    """Custom delegate for text column: Enter splits, handles editing."""

    split_requested = Signal(int, int)  # row, char_pos

    merge_prev_requested = Signal(int)  # row
    merge_next_requested = Signal(int)  # row

    def createEditor(self, parent, option, index):
        editor = _SplitLineEdit(parent)
        editor.setStyleSheet(f"background: {BG_ELEVATED}; color: {TEXT_PRIMARY}; "
                             f"border: 1px solid {ACCENT}; padding: 2px 4px;")
        row = index.row()
        editor.split_at.connect(lambda pos, r=row: self.split_requested.emit(r, pos))
        editor.merge_prev.connect(lambda r=row: self.merge_prev_requested.emit(r))
        editor.merge_next.connect(lambda r=row: self.merge_next_requested.emit(r))
        return editor

    def setEditorData(self, editor, index):
        editor.setText(index.data(Qt.EditRole) or "")
        editor.deselect()
        editor.setCursorPosition(len(editor.text()))

    def setModelData(self, editor, model, index):
        model.setData(index, editor.text(), Qt.EditRole)


# ── Editor tab widget ─────────────────────────────────────────

class EditorTab(QWidget):
    """Transcript editor with split/merge, search, queue, and audio preview."""

    jobs_changed = Signal()  # emitted when queue changes
    go_to_cutter = Signal()  # emitted when user clicks queue pill

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source_path: str = ""
        self._transcripts: dict = {}
        self._preview = AudioPreview()
        self._search_match_list: list = []
        self._search_match_pos: int = 0
        self._row_offsets: dict = {}  # {row: (start_ms, end_ms)}
        self._syncing_offsets = False  # guard against feedback loop

        self._model = SegmentTableModel(self)
        self._delegate = SegmentTextDelegate(self)

        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)

        # ── Toolbar ──────────────────────────────────
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(SP_XL, SP_MD, SP_XL, SP_MD)
        toolbar.setSpacing(SP_MD)

        self.source_combo = QComboBox()
        self.source_combo.setFixedWidth(160)
        self.source_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.btn_load_json = QPushButton("JSON")
        self.btn_load_json.setFixedWidth(65)
        self.btn_load_json.setProperty("ghost", True)
        toolbar.addWidget(self.source_combo)
        toolbar.addWidget(self.btn_load_json)

        self.summary_label = QLabel("")
        self.summary_label.setStyleSheet(f"color: {TEXT3}; font-size: 11px;")
        toolbar.addWidget(self.summary_label)
        toolbar.addStretch()

        # Search field (integrated)
        self.search_field = QLineEdit()
        self.search_field.setPlaceholderText("Search segments...")
        self.search_field.setMinimumWidth(200)
        self.search_field.setStyleSheet(f"""
            QLineEdit {{ background: {SURFACE2}; border: 1px solid {BORDER};
                         border-radius: {R_LG}px; padding: 7px 12px; font-size: 12px; }}
            QLineEdit:focus {{ border-color: {ACCENT}; }}
        """)
        self.btn_prev_match = QPushButton("◀")
        self.btn_next_match = QPushButton("▶")
        nav_btn_style = f"""
            QPushButton {{
                background: {SURFACE3}; border: none; color: {TEXT2};
                font-size: 12px; border-radius: {R_SM}px;
                min-width: 28px; min-height: 28px; max-width: 28px; max-height: 28px;
            }}
            QPushButton:hover {{ background: {ELEVATED}; color: {TEXT}; }}
        """
        self.btn_prev_match.setStyleSheet(nav_btn_style)
        self.btn_next_match.setStyleSheet(nav_btn_style)

        self.search_count_label = QLabel("")
        self.search_count_label.setFixedWidth(40)
        self.search_count_label.setAlignment(Qt.AlignCenter)
        self.search_count_label.setStyleSheet(f"color: {TEXT2}; font-size: 11px; border: none;")

        self.btn_select_matches = QPushButton("Select matches")
        self.btn_select_matches.setStyleSheet(f"""
            QPushButton {{ background: transparent; border: none; color: {ACCENT};
                           font-size: 11px; font-weight: 600; padding: 4px 12px; }}
            QPushButton:hover {{ background: {ACCENT_DIM}; border-radius: {R_MD}px; }}
        """)

        toolbar.addWidget(self.search_field)
        toolbar.addWidget(self.btn_prev_match)
        toolbar.addWidget(self.search_count_label)
        toolbar.addWidget(self.btn_next_match)
        toolbar.addWidget(self.btn_select_matches)

        toolbar_widget = QWidget()
        toolbar_widget.setObjectName("editorToolbar")
        toolbar_widget.setLayout(toolbar)
        toolbar_widget.setStyleSheet(f"#editorToolbar {{ border-bottom: 1px solid {BORDER}; }}")
        layout.addWidget(toolbar_widget)

        # ── Segment table ────────────────────────────
        self.table = QTableView()
        self.table.setModel(self._model)
        self.table.setItemDelegateForColumn(SegmentTableModel.COL_TEXT, self._delegate)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(False)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setSortingEnabled(False)

        # Column sizing
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(SegmentTableModel.COL_IDX, QHeaderView.Fixed)
        hdr.setSectionResizeMode(SegmentTableModel.COL_TIME, QHeaderView.Fixed)
        hdr.setSectionResizeMode(SegmentTableModel.COL_TEXT, QHeaderView.Stretch)
        hdr.setSectionResizeMode(SegmentTableModel.COL_DUR, QHeaderView.Fixed)
        hdr.setSectionResizeMode(SegmentTableModel.COL_QUEUED, QHeaderView.Fixed)
        self.table.setColumnWidth(SegmentTableModel.COL_IDX, 44)
        self.table.setColumnWidth(SegmentTableModel.COL_TIME, 110)
        self.table.setColumnWidth(SegmentTableModel.COL_DUR, 70)
        self.table.setColumnWidth(SegmentTableModel.COL_QUEUED, 40)

        layout.addWidget(self.table, 1)

        # ── Footer: Preview + queue info ─────────────
        footer = QWidget()
        footer.setObjectName("editorFooter")
        footer.setStyleSheet(f"#editorFooter {{ border-top: 1px solid {BORDER}; }}")
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(SP_XL, SP_MD, SP_XL, SP_MD)
        footer_layout.setSpacing(6)

        # Row 1: preview + offsets + queue pill
        preview_row = QHBoxLayout()
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

        offset_lbl = QLabel("Offset:")
        offset_lbl.setStyleSheet(f"color: {TEXT3}; font-size: 11px;")
        self.offset_start_spin = QSpinBox()
        self.offset_start_spin.setRange(-2000, 2000)
        self.offset_start_spin.setSingleStep(100)
        self.offset_start_spin.setSuffix(" ms")
        self.offset_start_spin.setValue(0)
        self.offset_start_spin.setFixedWidth(110)
        self.offset_start_spin.setToolTip("Shift start time (ms)")
        self.offset_end_spin = QSpinBox()
        self.offset_end_spin.setRange(-2000, 2000)
        self.offset_end_spin.setSingleStep(100)
        self.offset_end_spin.setSuffix(" ms")
        self.offset_end_spin.setValue(0)
        self.offset_end_spin.setFixedWidth(110)
        self.offset_end_spin.setToolTip("Shift end time (ms)")

        preview_row.addWidget(self.btn_preview)
        preview_row.addWidget(self.btn_stop)
        preview_row.addWidget(self.preview_label)
        preview_row.addWidget(offset_lbl)
        preview_row.addWidget(self.offset_start_spin)
        preview_row.addWidget(self.offset_end_spin)
        preview_row.addStretch()

        self.btn_select_all = QPushButton("Select all")
        self.btn_select_all.setFixedWidth(80)
        self.btn_select_all.setProperty("ghost", True)
        self.btn_clear_sel = QPushButton("Clear")
        self.btn_clear_sel.setFixedWidth(60)
        self.btn_clear_sel.setProperty("ghost", True)

        # Queue count pill (clickable → go to Cutter)
        self.selection_label = QPushButton("0 in queue")
        self.selection_label.setFixedWidth(160)
        self.selection_label.setCursor(Qt.PointingHandCursor)
        self.selection_label.setToolTip("Go to Cutter tab")
        self.selection_label.setStyleSheet(f"""
            QPushButton {{
                background: {ACCENT_DIM}; color: {ACCENT}; font-size: 12px; font-weight: 600;
                padding: 5px 14px; border-radius: 15px; border: none;
            }}
            QPushButton:hover {{ background: {ACCENT_GLOW}; }}
        """)
        self.duration_label = QLabel("")
        self.duration_label.setFixedWidth(110)
        self.duration_label.setStyleSheet(f"color: {TEXT3}; font-size: 11px;")

        preview_row.addWidget(self.btn_select_all)
        preview_row.addWidget(self.btn_clear_sel)
        preview_row.addWidget(self.selection_label)
        preview_row.addWidget(self.duration_label)
        footer_layout.addLayout(preview_row)

        # Row 2: keyboard hints
        hints_row = QHBoxLayout()
        hint_text = "Click text to edit  |  Ctrl+Enter split  |  Ctrl+Bksp merge  |  P preview  |  Space queue"
        hint = QLabel(hint_text)
        hint.setStyleSheet(f"color: {TEXT3}; font-size: 10px;")
        hints_row.addWidget(hint)
        hints_row.addStretch()
        footer_layout.addLayout(hints_row)

        layout.addWidget(footer)

    def _connect_signals(self):
        self.source_combo.currentIndexChanged.connect(self._on_source_changed)
        self.btn_load_json.clicked.connect(self._pick_json)
        self.search_field.textChanged.connect(self._on_search_changed)
        self.btn_prev_match.clicked.connect(self._goto_prev_match)
        self.btn_next_match.clicked.connect(self._goto_next_match)
        self.btn_select_matches.clicked.connect(self._select_all_matches)
        self.btn_select_all.clicked.connect(self._select_all)
        self.btn_clear_sel.clicked.connect(self._clear_selection)
        self._model.segments_changed.connect(self._update_selection_info)
        self.offset_start_spin.valueChanged.connect(self._on_offset_changed)
        self.offset_end_spin.valueChanged.connect(self._on_offset_changed)
        self._delegate.split_requested.connect(self._on_split_requested)
        self._delegate.merge_prev_requested.connect(self._do_merge_prev)
        self._delegate.merge_next_requested.connect(self._do_merge_next)
        self.btn_preview.clicked.connect(self._preview_current)
        self.btn_stop.clicked.connect(self._stop_preview)
        self.selection_label.clicked.connect(self._go_to_cutter)
        self.table.doubleClicked.connect(self._on_double_click)

        # Intercept key events on the table
        self.table.installEventFilter(self)
        self.table.selectionModel().currentRowChanged.connect(self._on_row_changed)

        # Keyboard shortcuts
        QShortcut(QKeySequence("Ctrl+F"), self, self.search_field.setFocus)
        QShortcut(QKeySequence("F3"), self, self._goto_next_match)
        QShortcut(QKeySequence("Shift+F3"), self, self._goto_prev_match)

    # ── Public API ────────────────────────────────────

    def add_transcript(self, job: TranscribeJob):
        name = os.path.basename(job.source_path)
        key = job.source_path
        # Replace all previous transcripts — keep only the latest
        self._transcripts.clear()
        self._transcripts[key] = (job.segments, job.source_path)
        self.source_combo.blockSignals(True)
        self.source_combo.clear()
        self.source_combo.addItem(f"{name} ({len(job.segments)} segs)", key)
        self.source_combo.setCurrentIndex(0)
        self.source_combo.blockSignals(False)
        self._load_segments(job.segments, job.source_path)

    def get_cut_jobs(self) -> List[CutJob]:
        """Return CutJobs for all queued segments with per-segment offsets."""
        jobs = []
        for row in sorted(self._model.selected_rows):
            seg = self._model.segment_at(row)
            if seg:
                off_s, off_e = self._row_offsets.get(row, (0, 0))
                jobs.append(CutJob(
                    source_path=self._source_path,
                    start=seg.start, end=seg.end,
                    label=seg.text.strip()[:80],
                    offset_start_ms=off_s,
                    offset_end_ms=off_e,
                ))
        return jobs

    def eventFilter(self, obj, event):
        """Intercept key events on the table."""
        if obj is self.table and event.type() == QEvent.KeyPress:
            editing = self.table.state() == QAbstractItemView.EditingState

            # When editing, let the editor handle everything
            if editing:
                return False

            current = self.table.currentIndex()
            if not current.isValid():
                return super().eventFilter(obj, event)

            row = current.row()

            # Ctrl+Backspace/Delete = merge (not in edit mode, no reopen)
            if event.modifiers() & Qt.ControlModifier:
                if event.key() == Qt.Key_Backspace:
                    self._do_merge_prev(row, reopen_editor=False)
                    return True
                elif event.key() == Qt.Key_Delete:
                    self._do_merge_next(row, reopen_editor=False)
                    return True

            # No modifiers
            if not event.modifiers():
                # Enter / Right arrow = start editing text
                if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Right):
                    self._focus_and_edit(row)
                    return True

                # Space = toggle queue selection
                if event.key() == Qt.Key_Space:
                    self._toggle_queue(row)
                    return True

                # Up/Down = navigate rows, stay in Text column
                if event.key() == Qt.Key_Up and row > 0:
                    self.table.setCurrentIndex(
                        self._model.index(row - 1, SegmentTableModel.COL_TEXT))
                    return True
                if event.key() == Qt.Key_Down and row < self._model.rowCount() - 1:
                    self.table.setCurrentIndex(
                        self._model.index(row + 1, SegmentTableModel.COL_TEXT))
                    return True

                # Home/End = first/last row
                if event.key() in (Qt.Key_Home, Qt.Key_End):
                    target = 0 if event.key() == Qt.Key_Home else self._model.rowCount() - 1
                    if target >= 0:
                        self.table.setCurrentIndex(
                            self._model.index(target, SegmentTableModel.COL_TEXT))
                        self.table.scrollTo(self._model.index(target, 0))
                    return True

                # P = preview current segment audio
                if event.key() == Qt.Key_P:
                    self._preview_row(row)
                    return True

                # Escape = stop preview
                if event.key() == Qt.Key_Escape:
                    if self._preview.is_playing:
                        self._stop_preview()
                        return True

        return super().eventFilter(obj, event)

    # ── Source selection ──────────────────────────────

    def _on_source_changed(self, index):
        if index < 0:
            return
        key = self.source_combo.itemData(index)
        if key in self._transcripts:
            segs, src = self._transcripts[key]
            self._load_segments(segs, src)
        elif key and os.path.exists(key):
            # Lazy-load from recents
            try:
                segs, src = load_transcript_json(key)
                if not src:
                    src = key.replace(".transcript.json", "")
                self._transcripts[key] = (segs, src)
                self._load_segments(segs, src)
            except Exception as ex:
                self.summary_label.setText(f"Error loading: {ex}")
                self.summary_label.setStyleSheet(f"color: {ACCENT};")

    def _pick_json(self):
        last_dir = _load_last_input_dir()
        # QFileDialog needs a trailing separator for directory-only paths
        if last_dir and not last_dir.endswith(("/", "\\")):
            last_dir += "/"
        path, _ = QFileDialog.getOpenFileName(
            self, "Load transcript JSON", last_dir,
            "JSON files (*.json);;All files (*)",
        )
        if not path:
            return
        _save_last_input_dir(os.path.normpath(os.path.dirname(path)))
        try:
            segs, src = load_transcript_json(path)
            if not src:
                src = path.replace(".transcript.json", "")
            name = os.path.basename(path)
            key = path
            self._transcripts[key] = (segs, src)
            for i in range(self.source_combo.count()):
                if self.source_combo.itemData(i) == key:
                    self.source_combo.setCurrentIndex(i)
                    return
            self.source_combo.addItem(f"{name} ({len(segs)} segs)", key)
            self.source_combo.setCurrentIndex(self.source_combo.count() - 1)
            self._save_to_recents(path, src, name, len(segs))
        except Exception as ex:
            self.summary_label.setText(f"Error: {ex}")
            self.summary_label.setStyleSheet(f"color: {ACCENT};")

    def _load_segments(self, segments: List[Segment], source_path: str):
        self._source_path = source_path
        self._row_offsets.clear()
        # Reindex
        for i, s in enumerate(segments):
            s.idx = i
        self._model.set_segments(segments)
        self._update_summary()
        self._update_selection_info()

    def _load_recents(self):
        """Populate source combo with recently loaded transcripts."""
        for r in _load_recent_transcripts():
            path = r.get("path", "")
            if not path or not os.path.exists(path):
                continue
            name = r.get("name", os.path.basename(path))
            seg_count = r.get("seg_count", "?")
            # Don't duplicate
            already = False
            for i in range(self.source_combo.count()):
                if self.source_combo.itemData(i) == path:
                    already = True
                    break
            if not already:
                self.source_combo.addItem(f"{name} ({seg_count} segs)", path)

    def _save_to_recents(self, path: str, source: str, name: str, seg_count: int):
        recents = _load_recent_transcripts()
        # Remove existing entry for same path
        recents = [r for r in recents if r.get("path") != path]
        # Add at front
        recents.insert(0, {"path": path, "source": source, "name": name, "seg_count": seg_count})
        _save_recent_transcripts(recents)

    # ── Search ───────────────────────────────────────

    def _on_search_changed(self, text):
        self._model.set_search(text)
        matches = self._model.search_matches
        n = len(matches)
        if n and text.strip():
            self._search_match_list = sorted(matches)
            self._search_match_pos = 0
            self._goto_match(0)
            self.search_count_label.setText(f"1/{n}")
        else:
            self._search_match_list = []
            self._search_match_pos = 0
            self.search_count_label.setText("")

    def _goto_next_match(self):
        if not self._search_match_list:
            return
        self._search_match_pos = (self._search_match_pos + 1) % len(self._search_match_list)
        self._goto_match(self._search_match_pos)

    def _goto_prev_match(self):
        if not self._search_match_list:
            return
        self._search_match_pos = (self._search_match_pos - 1) % len(self._search_match_list)
        self._goto_match(self._search_match_pos)

    def _goto_match(self, pos: int):
        row = self._search_match_list[pos]
        idx = self._model.index(row, SegmentTableModel.COL_TEXT)
        self.table.scrollTo(idx, QAbstractItemView.PositionAtCenter)
        self.table.setCurrentIndex(idx)
        n = len(self._search_match_list)
        self.search_count_label.setText(f"{pos + 1}/{n}")

    def _select_all_matches(self):
        self._model.select_rows(self._model.search_matches)
        self.jobs_changed.emit()

    # ── Selection ────────────────────────────────────

    def _select_all(self):
        all_rows = set(range(len(self._model.segments)))
        self._model.select_rows(all_rows)
        self.jobs_changed.emit()

    def _toggle_queue(self, row: int):
        """Toggle queue selection for a single row."""
        idx = self._model.index(row, SegmentTableModel.COL_QUEUED)
        current = self._model.data(idx, Qt.CheckStateRole)
        new_val = Qt.Unchecked if current == Qt.Checked else Qt.Checked
        self._model.setData(idx, new_val.value, Qt.CheckStateRole)

    def _go_to_cutter(self):
        if self._model.selected_rows:
            self.go_to_cutter.emit()

    def _clear_selection(self):
        self._model.deselect_all()
        self.jobs_changed.emit()

    def _update_selection_info(self):
        sel = self._model.selected_rows
        count = len(sel)
        self.selection_label.setText(f"{count} segment{'s' if count != 1 else ''} queued")
        if count > 0:
            total_dur = sum(
                self._model.segment_at(r).duration
                for r in sel
                if self._model.segment_at(r)
            )
            self.duration_label.setText(f"({fmt_ts(total_dur)} total)")
        else:
            self.duration_label.setText("")
        self.jobs_changed.emit()

    def _update_summary(self):
        segs = self._model.segments
        if segs:
            total_dur = segs[-1].end
            self.summary_label.setText(
                f"{len(segs)} segments · {fmt_ts(total_dur)} total"
                f" · Source: {os.path.basename(self._source_path)}"
            )
            self.summary_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")

    # ── Merge ────────────────────────────────────────

    def _do_merge_prev(self, row: int, reopen_editor: bool = True):
        new_row = self._model.merge_with_previous(row)
        if new_row is not None:
            self._update_summary()
            if reopen_editor:
                QTimer.singleShot(0, lambda: self._focus_and_edit(new_row))
            else:
                self.table.setCurrentIndex(
                    self._model.index(new_row, SegmentTableModel.COL_TEXT))

    def _do_merge_next(self, row: int, reopen_editor: bool = True):
        new_row = self._model.merge_with_next(row)
        if new_row is not None:
            self._update_summary()
            if reopen_editor:
                QTimer.singleShot(0, lambda: self._focus_and_edit(new_row))
            else:
                self.table.setCurrentIndex(
                    self._model.index(new_row, SegmentTableModel.COL_TEXT))

    # ── Split ────────────────────────────────────────

    def _on_split_requested(self, row: int, char_pos: int):
        seg = self._model.segment_at(row)
        if not seg or not seg.words:
            return
        word_idx = self._char_pos_to_word_idx(seg, char_pos)
        if word_idx is None:
            return
        # Close editor before modifying model
        self.table.closePersistentEditor(self.table.currentIndex())
        new_row = self._model.split_segment(row, word_idx)
        if new_row is not None:
            QTimer.singleShot(0, lambda: self._focus_and_edit(new_row))
            self._update_summary()

    def _focus_and_edit(self, row: int):
        idx = self._model.index(row, SegmentTableModel.COL_TEXT)
        self.table.setCurrentIndex(idx)
        self.table.edit(idx)

    def _char_pos_to_word_idx(self, seg: Segment, char_pos: int) -> Optional[int]:
        pos = 0
        boundaries = []
        for i, w in enumerate(seg.words):
            boundaries.append((pos, i))
            pos += len(w.text)
        best_idx = None
        best_dist = float("inf")
        for bp, wi in boundaries:
            if wi == 0:
                continue
            dist = abs(bp - char_pos)
            if dist < best_dist:
                best_dist = dist
                best_idx = wi
        return best_idx

    # ── Preview ──────────────────────────────────────

    def _on_double_click(self, index: QModelIndex):
        """Double-click on non-text column → preview segment."""
        if index.column() == SegmentTableModel.COL_TEXT:
            return  # let editing happen
        self._preview_row(index.row())

    def _preview_current(self):
        current = self.table.currentIndex()
        if current.isValid():
            self._preview_row(current.row())

    def _preview_row(self, row: int):
        seg = self._model.segment_at(row)
        if not seg or not self._source_path:
            return
        self.btn_stop.setEnabled(True)
        off_s = self.offset_start_spin.value()
        off_e = self.offset_end_spin.value()
        _, adj_s, adj_e = _apply_padding(seg.text, seg.start, seg.end)
        adj_s = max(0.0, adj_s + off_s / 1000.0)
        adj_e = adj_e + off_e / 1000.0
        self.preview_label.setText(
            f"Playing: {fmt_ts(adj_s)} → {fmt_ts(adj_e)} ({adj_e - adj_s:.1f}s)"
        )
        self._preview.play_segment(
            self._source_path, seg.start, seg.end, seg.text,
            on_finished=self._on_preview_finished,
            offset_start_ms=off_s,
            offset_end_ms=off_e,
        )

    def _stop_preview(self):
        self._preview.stop()
        self._on_preview_finished()

    def _on_preview_finished(self):
        # Must update UI from main thread
        QTimer.singleShot(0, self._reset_preview_ui)

    def _reset_preview_ui(self):
        self.btn_preview.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self._update_preview_label()

    def _on_row_changed(self, current, previous):
        """Load per-row offsets into spinboxes when row changes."""
        if not current.isValid():
            return
        row = current.row()
        off_s, off_e = self._row_offsets.get(row, (0, 0))
        self._syncing_offsets = True
        self.offset_start_spin.setValue(int(off_s))
        self.offset_end_spin.setValue(int(off_e))
        self._syncing_offsets = False
        self._update_preview_label()

    def _on_offset_changed(self):
        """Save offset values to current row."""
        if self._syncing_offsets:
            return
        current = self.table.currentIndex()
        if current.isValid():
            row = current.row()
            self._row_offsets[row] = (
                self.offset_start_spin.value(),
                self.offset_end_spin.value(),
            )
        self._update_preview_label()

    def _update_preview_label(self):
        """Show adjusted time range for the current segment (without playing)."""
        if self._preview.is_playing:
            return  # don't overwrite "Playing:" while active
        current = self.table.currentIndex()
        if not current.isValid():
            self.preview_label.setText("")
            return
        seg = self._model.segment_at(current.row())
        if not seg:
            self.preview_label.setText("")
            return
        off_s = self.offset_start_spin.value()
        off_e = self.offset_end_spin.value()
        _, adj_s, adj_e = _apply_padding(seg.text, seg.start, seg.end)
        adj_s = max(0.0, adj_s + off_s / 1000.0)
        adj_e = adj_e + off_e / 1000.0
        self.preview_label.setText(
            f"{fmt_ts(adj_s)} → {fmt_ts(adj_e)} ({adj_e - adj_s:.1f}s)"
        )
