"""Mamrot – Transcribe tab (Qt, v4 design)."""

import json
import os
import time
from typing import Optional, List

from PySide6.QtCore import Qt, Signal, QThread, QObject
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QLineEdit, QPushButton, QProgressBar,
    QListWidget, QListWidgetItem, QFileDialog, QCheckBox,
    QFrame, QSplitter, QSlider,
)
from PySide6.QtGui import QFont

from ..core.models import WHISPER_MODELS, LANGUAGES, TranscribeJob, fmt_ts
from ..core.transcriber import TranscriberEngine
from .theme import (
    ACCENT, ACCENT_LIGHT, ACCENT_TEXT, TEXT, TEXT2, TEXT3,
    SUCCESS, ERROR, SURFACE, SURFACE2, SURFACE3, ELEVATED,
    BORDER, BORDER_HOVER, ACCENT_DIM, SUCCESS_DIM,
    R_MD, R_LG, R_XL, SP_SM, SP_MD, SP_LG, SP_XL,
    FONT_FAMILY, MONO_FAMILY, BG,
)

_INPUT_DIR_CONFIG = os.path.join(os.path.expanduser("~"), ".mamrot", "input_dir.json")


def _load_last_input_dir() -> str:
    try:
        with open(_INPUT_DIR_CONFIG, "r") as f:
            return json.load(f).get("input_dir", "")
    except Exception:
        return ""


def _save_last_input_dir(path: str):
    try:
        os.makedirs(os.path.dirname(_INPUT_DIR_CONFIG), exist_ok=True)
        with open(_INPUT_DIR_CONFIG, "w") as f:
            json.dump({"input_dir": path}, f)
    except Exception:
        pass


# ── Worker for background transcription ──────────────────────

class TranscribeWorker(QObject):
    progress = Signal(TranscribeJob)
    job_done = Signal(TranscribeJob)
    job_error = Signal(TranscribeJob, str)
    all_done = Signal(float)  # elapsed seconds
    model_status = Signal(str)

    def __init__(self, engine: TranscriberEngine, jobs: List[TranscribeJob],
                 model_name: str, language: str, device: str, beam_size: int,
                 start_time: Optional[float], end_time: Optional[float]):
        super().__init__()
        self.engine = engine
        self.jobs = jobs
        self.model_name = model_name
        self.language = language
        self.device = device
        self.beam_size = beam_size
        self.start_time = start_time
        self.end_time = end_time
        self._stop = False

    def run(self):
        t0 = time.time()
        try:
            self.engine.load_model(
                model_name=self.model_name,
                device=self.device,
                compute_type="auto",
                on_status=lambda msg: self.model_status.emit(msg),
            )
        except Exception as ex:
            self.model_status.emit(f"Model load failed: {ex}")
            return

        for job in self.jobs:
            if self._stop:
                break
            if job.status == "done":
                continue  # skip already completed jobs on resume
            job.status = "running"
            job.progress = 0.0
            self.progress.emit(job)

            try:
                lang = self.language if self.language != "auto" else None
                segments_iter, info = self.engine._model.transcribe(
                    job.source_path,
                    language=lang,
                    vad_filter=True,
                    vad_parameters=dict(min_silence_duration_ms=300, threshold=0.5, speech_pad_ms=30),
                    beam_size=self.beam_size,
                    word_timestamps=True,
                )
                job.duration = info.duration
                job.language_detected = info.language or "?"
                duration = info.duration if info.duration > 0 else 1.0

                from ..core.models import Segment, Word
                segs = []
                for seg in segments_iter:
                    if self._stop:
                        break
                    words = []
                    if seg.words:
                        words = [Word(start=float(w.start), end=float(w.end), text=w.word)
                                 for w in seg.words]
                    s = Segment(idx=len(segs), start=float(seg.start), end=float(seg.end),
                                text=seg.text or "", words=words)
                    if self.start_time is not None and s.end < self.start_time:
                        continue
                    if self.end_time is not None and s.start > self.end_time:
                        continue
                    segs.append(s)
                    job.segments = segs
                    job.progress = min(float(seg.end) / duration, 1.0)
                    self.progress.emit(job)

                if self._stop:
                    # Keep partial segments collected so far
                    for i, s in enumerate(segs):
                        s.idx = i
                    job.segments = segs
                    job.status = "stopped"
                    job.error = "Paused"
                    break

                for i, s in enumerate(segs):
                    s.idx = i
                job.segments = segs
                job.progress = 1.0
                job.status = "done"
                self.engine._save_outputs(job)
                self.job_done.emit(job)

            except Exception as e:
                job.status = "error"
                job.error = str(e)
                self.job_error.emit(job, str(e))

        elapsed = time.time() - t0
        self.all_done.emit(elapsed)

    def stop(self):
        self._stop = True


class TranscribeTab(QWidget):
    """Transcription tab — v4 design with 2-column layout."""

    transcription_done = Signal(TranscribeJob)

    def __init__(self, engine: TranscriberEngine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self._jobs: List[TranscribeJob] = []
        self._worker: Optional[TranscribeWorker] = None
        self._thread: Optional[QThread] = None
        self._job_start_time = 0.0

        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Left panel: Files ─────────────────────────
        left = QWidget()
        left.setObjectName("transcribeLeft")
        left.setStyleSheet(f"#transcribeLeft {{ border-right: 1px solid {BORDER}; }}")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(SP_XL, SP_XL, SP_XL, SP_XL)
        left_layout.setSpacing(SP_LG)

        # Header
        header = QHBoxLayout()
        self.files_title = QLabel("Files (0)")
        self.files_title.setStyleSheet(f"font-size: 15px; font-weight: 600; color: {TEXT}; border: none;")
        self.btn_add = QPushButton("Add files")
        self.btn_add.setStyleSheet(f"""
            QPushButton {{ background: {SURFACE2}; color: {TEXT}; border: 1px solid {BORDER};
                           border-radius: {R_MD}px; padding: 6px 14px; font-size: 12px; }}
            QPushButton:hover {{ background: {SURFACE3}; border-color: {BORDER_HOVER}; }}
        """)
        header.addWidget(self.files_title)
        header.addStretch()
        header.addWidget(self.btn_add)
        left_layout.addLayout(header)

        # File list
        self.file_list = QListWidget()
        self.file_list.setStyleSheet(f"""
            QListWidget {{ background: {SURFACE2}; border: 1px solid {BORDER};
                           border-radius: {R_XL}px; padding: 4px; }}
            QListWidget::item {{ padding: 10px 14px; border-radius: {R_MD}px; border: none; }}
            QListWidget::item:selected {{ background: {ACCENT_DIM}; }}
            QListWidget::item:hover:!selected {{ background: {SURFACE3}; }}
        """)
        left_layout.addWidget(self.file_list, 1)

        # Progress section
        self.progress_frame = QWidget()
        self.progress_frame.setStyleSheet(f"""
            QWidget {{ background: {SURFACE2}; border: 1px solid {BORDER};
                       border-radius: {R_XL}px; }}
        """)
        pf_layout = QVBoxLayout(self.progress_frame)
        pf_layout.setContentsMargins(18, 16, 18, 16)
        pf_layout.setSpacing(SP_MD)

        pf_header = QHBoxLayout()
        self.status_label = QLabel("Loading model...")
        self.status_label.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {ACCENT}; border: none;")
        self.eta_label = QLabel("")
        self.eta_label.setStyleSheet(f"font-size: 11px; color: {TEXT2}; border: none;")
        pf_header.addWidget(self.status_label)
        pf_header.addStretch()
        pf_header.addWidget(self.eta_label)
        pf_layout.addLayout(pf_header)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(5)
        self.progress_bar.setTextVisible(False)
        pf_layout.addWidget(self.progress_bar)

        self.progress_frame.setVisible(False)
        left_layout.addWidget(self.progress_frame)

        # Done banner
        self.done_frame = QWidget()
        self.done_frame.setStyleSheet(f"""
            QWidget {{ background: {SUCCESS_DIM}; border: 1px solid rgba(125,211,160,0.15);
                       border-radius: {R_XL}px; }}
        """)
        df_layout = QHBoxLayout(self.done_frame)
        df_layout.setContentsMargins(18, 12, 18, 12)
        self.done_label = QLabel("")
        self.done_label.setStyleSheet(f"font-size: 12px; font-weight: 500; color: {SUCCESS}; border: none;")
        df_layout.addWidget(self.done_label)
        self.done_frame.setVisible(False)
        left_layout.addWidget(self.done_frame)

        outer.addWidget(left, 1)

        # ── Right panel: Settings ─────────────────────
        right = QWidget()
        right.setFixedWidth(300)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(SP_XL, SP_XL, SP_XL, SP_XL)
        right_layout.setSpacing(18)

        settings_header = QLabel("SETTINGS")
        settings_header.setStyleSheet(f"""
            font-size: 11px; font-weight: 600; color: {TEXT3};
            letter-spacing: 2px; text-transform: uppercase;
        """)
        right_layout.addWidget(settings_header)

        # Model
        right_layout.addWidget(self._field_label("Model"))
        self.model_combo = QComboBox()
        for m in WHISPER_MODELS:
            hints = {"tiny": "fastest", "base": "fast", "small": "balanced",
                     "medium": "accurate", "large-v3": "best"}
            self.model_combo.addItem(f"{m} — {hints.get(m, m)}", m)
        self.model_combo.setCurrentIndex(2)  # small
        right_layout.addWidget(self.model_combo)
        self.model_hint = QLabel("~500 MB")
        self.model_hint.setStyleSheet(f"font-size: 10px; color: {TEXT3};")
        right_layout.addWidget(self.model_hint)

        # Language
        right_layout.addWidget(self._field_label("Language"))
        self.lang_combo = QComboBox()
        for k, v in LANGUAGES.items():
            self.lang_combo.addItem(f"{v}" if k == "auto" else f"{v}", k)
        self.lang_combo.setCurrentIndex(0)
        right_layout.addWidget(self.lang_combo)

        # Device
        right_layout.addWidget(self._field_label("Device"))
        self.device_combo = QComboBox()
        self.device_combo.addItem("Auto (GPU if available)", "auto")
        self.device_combo.addItem("GPU (CUDA)", "cuda")
        self.device_combo.addItem("CPU", "cpu")
        right_layout.addWidget(self.device_combo)

        # Beam size slider
        beam_row = QHBoxLayout()
        beam_row.addWidget(self._field_label("Beam size"))
        self.beam_value_label = QLabel("5")
        self.beam_value_label.setStyleSheet(f"font-size: 11px; font-weight: 600; color: {ACCENT};")
        beam_row.addStretch()
        beam_row.addWidget(self.beam_value_label)
        right_layout.addLayout(beam_row)

        self.beam_slider = QSlider(Qt.Horizontal)
        self.beam_slider.setRange(1, 10)
        self.beam_slider.setValue(5)
        self.beam_slider.setTickPosition(QSlider.NoTicks)
        right_layout.addWidget(self.beam_slider)

        beam_hints = QHBoxLayout()
        faster_hint = QLabel("Faster")
        faster_hint.setStyleSheet(f"font-size: 10px; color: {TEXT3};")
        accurate_hint = QLabel("More accurate")
        accurate_hint.setStyleSheet(f"font-size: 10px; color: {TEXT3};")
        beam_hints.addWidget(faster_hint)
        beam_hints.addStretch()
        beam_hints.addWidget(accurate_hint)
        right_layout.addLayout(beam_hints)

        # Fragment mode
        self.fragment_check = QCheckBox("Fragment mode")
        self.fragment_check.setStyleSheet(f"font-size: 12px; color: {TEXT2};")
        right_layout.addWidget(self.fragment_check)

        frag_row = QHBoxLayout()
        self.frag_start = QLineEdit()
        self.frag_start.setPlaceholderText("From 00:00:00")
        self.frag_start.setStyleSheet(f"font-family: {MONO_FAMILY}; font-size: 12px; letter-spacing: 0.5px;")
        self.frag_start.setVisible(False)
        self.frag_end = QLineEdit()
        self.frag_end.setPlaceholderText("To 00:00:00")
        self.frag_end.setStyleSheet(f"font-family: {MONO_FAMILY}; font-size: 12px; letter-spacing: 0.5px;")
        self.frag_end.setVisible(False)
        frag_row.addWidget(self.frag_start)
        frag_row.addWidget(self.frag_end)
        right_layout.addLayout(frag_row)

        # Model status
        self.model_status_label = QLabel("No model loaded")
        self.model_status_label.setStyleSheet(f"font-size: 10px; color: {TEXT3};")
        right_layout.addWidget(self.model_status_label)

        right_layout.addStretch()

        # Transcribe button
        self.btn_start = QPushButton("Transcribe")
        self.btn_start.setProperty("accent", True)
        self.btn_start.setStyleSheet(f"""
            QPushButton {{
                background: {ACCENT}; color: {BG}; border: none;
                font-weight: 600; font-size: 14px;
                padding: 12px 20px; border-radius: {R_LG}px;
            }}
            QPushButton:hover {{ background: {ACCENT_LIGHT}; }}
            QPushButton:disabled {{ background: {TEXT3}; color: {TEXT3}; }}
        """)
        right_layout.addWidget(self.btn_start)

        outer.addWidget(right)

    def _field_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"font-size: 11px; font-weight: 500; color: {TEXT2};")
        return lbl

    def _connect_signals(self):
        self.btn_add.clicked.connect(self._pick_files)
        self.btn_start.clicked.connect(self._start)
        self.fragment_check.toggled.connect(lambda v: (
            self.frag_start.setVisible(v), self.frag_end.setVisible(v),
        ))
        self.beam_slider.valueChanged.connect(self._on_beam_changed)
        self.model_combo.currentIndexChanged.connect(self._on_model_changed)

    def _on_beam_changed(self, value):
        self.beam_value_label.setText(str(value))

    def _on_model_changed(self):
        model = self.model_combo.currentData()
        hints = {"tiny": "~75 MB", "base": "~150 MB", "small": "~500 MB",
                 "medium": "~1.5 GB, recommended", "large-v3": "~3 GB, highest accuracy"}
        self.model_hint.setText(hints.get(model, ""))

    # ── File management ──────────────────────────────

    def _pick_files(self):
        last_dir = _load_last_input_dir()
        if last_dir and not last_dir.endswith(("/", "\\")):
            last_dir += "/"
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select audio/video files", last_dir,
            "Media files (*.mp3 *.wav *.flac *.ogg *.m4a *.aac *.wma "
            "*.mp4 *.mkv *.avi *.mov *.webm *.ts);;All files (*)",
        )
        if files:
            _save_last_input_dir(os.path.normpath(os.path.dirname(files[0])))
        for f in files:
            if not any(j.source_path == f for j in self._jobs):
                self._jobs.append(TranscribeJob(source_path=f))
        self._refresh_file_list()

    def _refresh_file_list(self):
        self.file_list.clear()
        for job in self._jobs:
            name = os.path.basename(job.source_path)
            status_map = {"queued": "⏳", "running": "🔄", "done": "✅", "error": "❌", "stopped": "⏸"}
            status = status_map.get(job.status, "⏳")
            seg_info = f" ({len(job.segments)} segs)" if job.segments else ""
            item = QListWidgetItem(f"{status} {name}{seg_info}")
            self.file_list.addItem(item)
        n = len(self._jobs)
        self.files_title.setText(f"Files ({n})")

    # ── Transcription ────────────────────────────────

    def _start(self):
        # If already running, pause
        if self._worker and self._thread and self._thread.isRunning():
            self._worker.stop()
            self.btn_start.setEnabled(False)
            self.status_label.setText("Stopping...")
            self.status_label.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {ACCENT}; border: none;")
            return

        if not self._jobs:
            self.status_label.setText("No files to transcribe.")
            self.status_label.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {ERROR}; border: none;")
            return

        # Only reset jobs that haven't been completed yet
        resuming = any(j.status in ("stopped", "done") for j in self._jobs)
        for j in self._jobs:
            if j.status not in ("done",):
                j.status = "queued"
                j.segments = []
                j.progress = 0.0
                j.error = ""

        self.btn_start.setText("Stop")
        self.btn_start.setStyleSheet(f"""
            QPushButton {{
                background: {ERROR}; color: {BG}; border: none;
                font-weight: 600; font-size: 14px;
                padding: 12px 20px; border-radius: {R_LG}px;
            }}
            QPushButton:hover {{ background: #F08080; }}
        """)
        self.progress_frame.setVisible(True)
        self.done_frame.setVisible(False)
        self.progress_bar.setRange(0, 0)  # indeterminate during model load
        self.status_label.setText("Loading model...")
        self.status_label.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {ACCENT}; border: none;")
        self.eta_label.setText("")
        self._job_start_time = time.time()

        # Parse fragment times
        start_time = None
        end_time = None
        if self.fragment_check.isChecked():
            try:
                if self.frag_start.text():
                    start_time = _parse_ts(self.frag_start.text())
                if self.frag_end.text():
                    end_time = _parse_ts(self.frag_end.text())
            except ValueError:
                pass

        self._thread = QThread()
        self._worker = TranscribeWorker(
            engine=self.engine,
            jobs=self._jobs[:],
            model_name=self.model_combo.currentData(),
            language=self.lang_combo.currentData(),
            device=self.device_combo.currentData(),
            beam_size=self.beam_slider.value(),
            start_time=start_time,
            end_time=end_time,
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.job_done.connect(self._on_job_done)
        self._worker.job_error.connect(self._on_job_error)
        self._worker.all_done.connect(self._on_all_done)
        self._worker.model_status.connect(self._on_model_status)
        self._thread.start()

    def _on_model_status(self, msg: str):
        self.model_status_label.setText(msg)

    def _on_progress(self, job: TranscribeJob):
        # Switch from indeterminate to determinate on first progress
        if self.progress_bar.maximum() == 0:
            self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(int(job.progress * 1000))
        pct_str = f"{job.progress:.0%}"
        seg_count = len(job.segments)
        elapsed = time.time() - self._job_start_time if self._job_start_time else 0
        eta_str = ""
        if job.progress > 0.05 and elapsed > 2:
            eta_sec = elapsed / job.progress * (1 - job.progress)
            eta_str = f"~{eta_sec:.0f}s" if eta_sec < 60 else f"~{eta_sec / 60:.1f}min"
        self.status_label.setText(f"Transcribing... {pct_str}")
        self.status_label.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {ACCENT}; border: none;")
        self.eta_label.setText(
            f"ETA {eta_str} · Segment {seg_count}" if eta_str
            else f"Segment {seg_count}"
        )
        self._refresh_file_list()
        w = self.window()
        if w:
            w.setWindowTitle(f"Mamrot — {pct_str} {eta_str}")

    def _on_job_done(self, job: TranscribeJob):
        self._refresh_file_list()
        self.transcription_done.emit(job)
        self._job_start_time = time.time()

    def _on_job_error(self, job: TranscribeJob, error: str):
        self.status_label.setText(f"Error: {error}")
        self.status_label.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {ERROR}; border: none;")
        self._refresh_file_list()
        self._job_start_time = time.time()

    def _on_all_done(self, elapsed: float):
        time_str = f"{elapsed:.0f}s" if elapsed < 60 else f"{elapsed / 60:.1f}min"
        total_segs = sum(len(j.segments) for j in self._jobs)
        paused = any(j.status == "stopped" for j in self._jobs)
        pending = sum(1 for j in self._jobs if j.status in ("queued", "stopped"))
        self.progress_frame.setVisible(False)
        self.done_frame.setVisible(True)

        if paused:
            self.done_label.setText(f"Paused · {pending} remaining · {total_segs} segments so far")
            self.btn_start.setText("Resume")
            self.btn_start.setStyleSheet(f"""
                QPushButton {{
                    background: {SUCCESS}; color: {BG}; border: none;
                    font-weight: 600; font-size: 14px;
                    padding: 12px 20px; border-radius: {R_LG}px;
                }}
                QPushButton:hover {{ background: #90E0B0; }}
            """)
        else:
            self.done_label.setText(f"Done · {len(self._jobs)} files · {total_segs} segments · {time_str}")
            self.btn_start.setText("Transcribe")
            self.btn_start.setStyleSheet(f"""
                QPushButton {{
                    background: {ACCENT}; color: {BG}; border: none;
                    font-weight: 600; font-size: 14px;
                    padding: 12px 20px; border-radius: {R_LG}px;
                }}
                QPushButton:hover {{ background: {ACCENT_LIGHT}; }}
                QPushButton:disabled {{ background: {TEXT3}; color: {TEXT3}; }}
            """)
        self.btn_start.setEnabled(True)
        self.eta_label.setText("")
        self._refresh_file_list()
        w = self.window()
        if w:
            w.setWindowTitle("Mamrot — done!")
        if self._thread:
            self._thread.quit()
            self._thread.wait()
            self._thread = None
            self._worker = None


    def stop_and_wait(self):
        """Stop transcription worker and wait for thread to finish."""
        if self._worker:
            self._worker.stop()
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(5000)  # wait up to 5s
            self._thread = None
            self._worker = None


def _parse_ts(value: str) -> float:
    value = value.strip()
    try:
        return float(value)
    except ValueError:
        pass
    parts = value.replace(",", ".").split(":")
    if len(parts) == 3:
        h, m, s = parts
    elif len(parts) == 2:
        h, m, s = "0", parts[0], parts[1]
    else:
        raise ValueError(f"Bad timestamp: {value}")
    sec = float(s) if "." in s else int(s)
    return int(h) * 3600 + int(m) * 60 + sec
