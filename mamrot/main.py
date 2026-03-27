"""
Mamrot -- even when you mumble, it still understands.

Desktop audio/video transcriber & cutter.
Powered by faster-whisper + ffmpeg + PySide6.

Install:  pip install .
Run:      mamrot  (or: python -m mamrot)
"""

import json
import os
import sys

from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget,
    QDialog, QVBoxLayout, QLabel, QProgressBar, QPushButton, QHBoxLayout,
)
from PySide6.QtGui import QKeyEvent, QFontDatabase, QFont, QIcon

from .core.transcriber import TranscriberEngine
from .core.cutter import CutterEngine
from .core.models import TranscribeJob, CutJob
from .core.ffmpeg_bootstrap import get_ffmpeg_path, download_ffmpeg, get_install_hint

from .ui.theme import build_stylesheet
from .ui.transcribe_tab import TranscribeTab
from .ui.editor_tab import EditorTab
from .ui.cutter_tab import CutterTab

from typing import List

_CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".mamrot", "window.json")


def _load_window_config() -> dict:
    try:
        with open(_CONFIG_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_window_config(win: QMainWindow):
    try:
        geo = win.geometry()
        data = {
            "x": geo.x(),
            "y": geo.y(),
            "width": geo.width(),
            "height": geo.height(),
        }
        os.makedirs(os.path.dirname(_CONFIG_PATH), exist_ok=True)
        with open(_CONFIG_PATH, "w") as f:
            json.dump(data, f)
    except Exception:
        pass


class MamrotWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Mamrot")

        # ── Window config ──────────────────────────────
        wc = _load_window_config()
        self.resize(wc.get("width", 1100), wc.get("height", 780))
        self.setMinimumSize(800, 600)
        if "x" in wc and "y" in wc:
            self.move(wc["x"], wc["y"])

        # ── Engines ────────────────────────────────────
        self.transcriber = TranscriberEngine()
        self.cutter = CutterEngine()

        # ── Tabs ───────────────────────────────────────
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self.transcribe_tab = TranscribeTab(self.transcriber)
        self.editor_tab = EditorTab()
        self.cutter_tab = CutterTab(self.cutter)

        self.tabs.addTab(self.transcribe_tab, "Transcribe")
        self.tabs.addTab(self.editor_tab, "Editor")
        self.tabs.addTab(self.cutter_tab, "Cutter")

        # ── Cross-tab wiring ───────────────────────────
        self.transcribe_tab.transcription_done.connect(self._on_transcription_done)
        self.editor_tab.jobs_changed.connect(self._on_editor_jobs_changed)
        self.editor_tab.go_to_cutter.connect(lambda: self.tabs.setCurrentIndex(2))
        self.tabs.currentChanged.connect(self._on_tab_changed)

    def _on_transcription_done(self, job: TranscribeJob):
        self.editor_tab.add_transcript(job)

    def _on_editor_jobs_changed(self):
        """Sync editor queue selections to cutter engine."""
        # Don't rebuild while cutter is processing
        if self.cutter.is_running:
            return
        # Don't rebuild if there are done jobs (cutter just finished)
        if any(j.status == "done" for j in self.cutter.queue):
            return
        self.cutter.clear_all()
        for cut_job in self.editor_tab.get_cut_jobs():
            self.cutter.add(cut_job)

    def _on_tab_changed(self, index: int):
        if index == 2:
            self.cutter_tab.refresh()

    def moveEvent(self, event):
        super().moveEvent(event)
        _save_window_config(self)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        _save_window_config(self)

    def closeEvent(self, event):
        _save_window_config(self)
        self.transcribe_tab.stop_and_wait()
        self.editor_tab._preview.stop()
        self.cutter_tab._preview.stop()
        super().closeEvent(event)


class _FFmpegDownloadWorker(QObject):
    progress = Signal(int, int)  # downloaded, total
    finished = Signal(str)       # path
    error = Signal(str)

    def run(self):
        try:
            path = download_ffmpeg(on_progress=lambda d, t: self.progress.emit(d, t))
            self.finished.emit(path)
        except Exception as e:
            self.error.emit(str(e))


class FFmpegDownloadDialog(QDialog):
    """Modal dialog that downloads ffmpeg with a progress bar (Windows only)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("FFmpeg not found")
        self.setMinimumWidth(420)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self._thread = None
        self._worker = None

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        self._label = QLabel(
            "FFmpeg is required for audio cutting.\n"
            "It was not found in your system PATH.\n"
            "Download it automatically (~80 MB)?"
        )
        self._label.setWordWrap(True)
        layout.addWidget(self._label)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        btn_row = QHBoxLayout()
        self._btn_download = QPushButton("Download")
        self._btn_skip = QPushButton("Skip")
        btn_row.addStretch()
        btn_row.addWidget(self._btn_skip)
        btn_row.addWidget(self._btn_download)
        layout.addLayout(btn_row)

        self._btn_download.clicked.connect(self._start_download)
        self._btn_skip.clicked.connect(self.reject)

    def _start_download(self):
        self._btn_download.setEnabled(False)
        self._btn_skip.setEnabled(False)
        self._label.setText("Downloading FFmpeg...")
        self._progress.setVisible(True)

        self._thread = QThread()
        self._worker = _FFmpegDownloadWorker()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._thread.start()

    def _on_progress(self, downloaded: int, total: int):
        if total > 0:
            self._progress.setValue(int(downloaded * 100 / total))
            mb = downloaded / 1024 / 1024
            mb_total = total / 1024 / 1024
            self._label.setText(f"Downloading FFmpeg... {mb:.0f} / {mb_total:.0f} MB")
        else:
            mb = downloaded / 1024 / 1024
            self._label.setText(f"Downloading FFmpeg... {mb:.0f} MB")

    def _on_finished(self, path: str):
        self._cleanup_thread()
        self.accept()

    def _on_error(self, msg: str):
        self._label.setText(f"Download failed: {msg}\nYou can install FFmpeg manually later.")
        self._btn_skip.setEnabled(True)
        self._btn_skip.setText("Close")
        self._cleanup_thread()

    def _cleanup_thread(self):
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(5000)
        self._thread = None
        self._worker = None

    def closeEvent(self, event):
        self._cleanup_thread()
        super().closeEvent(event)


def _check_ffmpeg(parent=None):
    """Check if ffmpeg is available. On Windows: offer download. Elsewhere: show hint."""
    if get_ffmpeg_path():
        return

    import platform as _plat

    hint = get_install_hint()
    if hint:
        # macOS / Linux — just show install instruction, no auto-download
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(
            parent, "FFmpeg not found",
            f"FFmpeg is required for audio cutting.\n\n"
            f"Install it with:\n  {hint}\n\n"
            f"Then restart Mamrot.",
        )
        return

    # Windows — offer auto-download
    dlg = FFmpegDownloadDialog(parent)
    dlg.exec()


def main():
    # Windows: set AppUserModelID so taskbar shows our icon, not python.exe
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("mamrot.mamrot.app")
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setStyleSheet(build_stylesheet())

    # App icon (waveform bars)
    icon_dir = os.path.join(os.path.dirname(__file__), "assets")
    icon = QIcon()
    for size in (16, 32, 48, 64, 128, 256):
        path = os.path.join(icon_dir, f"icon_{size}.png")
        if os.path.exists(path):
            icon.addFile(path)
    if not icon.isNull():
        app.setWindowIcon(icon)

    window = MamrotWindow()
    window.show()
    _check_ffmpeg(window)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
