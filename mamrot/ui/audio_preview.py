"""Mamrot – Audio preview player using ffplay."""

import os
import subprocess
import tempfile
import threading
from typing import Optional

from ..core.cutter import cut_audio, _apply_padding, _find_ffmpeg


class AudioPreview:
    """Play a segment preview using ffplay (bundled with ffmpeg)."""

    def __init__(self):
        self._process: Optional[subprocess.Popen] = None
        self._temp_file: Optional[str] = None
        self._lock = threading.Lock()

    def play_segment(
        self,
        source_path: str,
        start: float,
        end: float,
        text: str = "",
        on_finished: Optional[callable] = None,
        offset_start_ms: float = 0,
        offset_end_ms: float = 0,
    ):
        """Extract segment (with ^ padding + manual offsets) and play it."""
        self.stop()

        def _do():
            try:
                # Apply padding markers
                _, adj_start, adj_end = _apply_padding(text, start, end)
                adj_start = max(0.0, adj_start + offset_start_ms / 1000.0)
                adj_end = adj_end + offset_end_ms / 1000.0

                # Extract to temp WAV
                tmp = tempfile.NamedTemporaryFile(
                    suffix=".wav", prefix="mamrot_preview_", delete=False,
                )
                tmp_name = tmp.name
                tmp.close()
                self._temp_file = tmp_name  # set early so _cleanup_temp works on error

                cut_audio(source_path, adj_start, adj_end, self._temp_file)

                # Play using ffplay (comes with ffmpeg)
                import shutil
                ffplay = shutil.which("ffplay")
                if not ffplay:
                    # Try next to ffmpeg binary
                    ffmpeg_path = _find_ffmpeg()
                    ffplay_candidate = os.path.join(
                        os.path.dirname(ffmpeg_path),
                        "ffplay.exe" if os.name == "nt" else "ffplay",
                    )
                    ffplay = ffplay_candidate if os.path.exists(ffplay_candidate) else "ffplay"

                kwargs = dict(
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                if os.name == "nt":
                    kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

                with self._lock:
                    self._process = subprocess.Popen(
                        [ffplay, "-nodisp", "-autoexit", "-loglevel", "quiet",
                         self._temp_file],
                        **kwargs,
                    )

                self._process.wait()

            except Exception as e:
                pass  # silently ignore preview playback errors
            finally:
                self._cleanup_temp()
                with self._lock:
                    self._process = None
                if on_finished:
                    on_finished()

        threading.Thread(target=_do, daemon=True).start()

    def stop(self):
        """Stop current playback."""
        with self._lock:
            if self._process and self._process.poll() is None:
                try:
                    self._process.terminate()
                    self._process.wait(timeout=2)
                except Exception:
                    try:
                        self._process.kill()
                    except Exception:
                        pass
                self._process = None
        self._cleanup_temp()

    def _cleanup_temp(self):
        if self._temp_file:
            try:
                os.unlink(self._temp_file)
            except Exception:
                pass
            self._temp_file = None

    @property
    def is_playing(self) -> bool:
        with self._lock:
            return self._process is not None and self._process.poll() is None
