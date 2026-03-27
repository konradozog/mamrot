"""Mamrot – audio cutter engine (ffmpeg wrapper)."""

import os
import re
import subprocess
import threading
import unicodedata
from typing import Optional, Callable, List

from .models import CutJob
from .ffmpeg_bootstrap import get_ffmpeg_path


def _find_ffmpeg() -> str:
    """Return ffmpeg path or raise."""
    path = get_ffmpeg_path()
    if not path:
        raise FileNotFoundError(
            "ffmpeg not found. Restart Mamrot to download it, "
            "or install manually: https://ffmpeg.org/download.html"
        )
    return path


_EXTRA_TRANSLIT = str.maketrans({
    "ł": "l", "Ł": "L", "đ": "d", "Đ": "D", "ø": "o", "Ø": "O",
    "ß": "ss", "æ": "ae", "Æ": "AE", "þ": "th", "Þ": "Th",
})


def _slugify(text: str, max_words: int = 6) -> str:
    """Turn text into a safe ASCII filename fragment (first N words)."""
    # Transliterate unicode to ASCII (ę→e, ą→a, ł→l, etc.)
    mapped = text.translate(_EXTRA_TRANSLIT)
    nfkd = unicodedata.normalize("NFKD", mapped)
    ascii_text = nfkd.encode("ascii", "ignore").decode("ascii")
    # Keep only letters, digits, spaces, hyphens
    clean = re.sub(r'[^\w\s-]', '', ascii_text.strip())
    words = clean.split()[:max_words]
    slug = "_".join(words)
    return slug[:80] if slug else "clip"


_DEFAULT_PAD_START_MS = 60   # default padding before cut start
_DEFAULT_PAD_END_MS = 150    # default padding after cut end (whisper cuts words short)
_PAD_PER_MARKER_MS = 300     # additional ms per ^ marker


def _apply_padding(text: str, start: float, end: float):
    """Apply default padding + parse ^ markers from text.

    Default: 60ms before start, 150ms after end (compensates whisper).
    Trailing ^ are stripped first, then leading ^.
    Each trailing ^: adds 300ms after end.
    Each leading ^: adds 300ms before start.
    Returns (clean_text, adjusted_start, adjusted_end).
    """
    clean = text
    # Count and strip trailing ^
    end_pad = 0
    while clean.endswith("^"):
        clean = clean[:-1]
        end_pad += 1
    # Count and strip leading ^
    start_pad = 0
    while clean.startswith("^"):
        clean = clean[1:]
        start_pad += 1

    adj_start = max(0.0, start - _DEFAULT_PAD_START_MS / 1000 - start_pad * _PAD_PER_MARKER_MS / 1000)
    adj_end = end + _DEFAULT_PAD_END_MS / 1000 + end_pad * _PAD_PER_MARKER_MS / 1000
    return clean.strip(), adj_start, adj_end


OUTPUT_FORMATS = {
    "wav":  {"ext": ".wav",  "codec": ["-acodec", "pcm_s16le"]},
    "mp3":  {"ext": ".mp3",  "codec": ["-acodec", "libmp3lame", "-q:a", "2"]},
    "flac": {"ext": ".flac", "codec": ["-acodec", "flac"]},
    "ogg":  {"ext": ".ogg",  "codec": ["-acodec", "libvorbis", "-q:a", "5"]},
    "aac":  {"ext": ".m4a",  "codec": ["-acodec", "aac", "-b:a", "192k"]},
    "opus": {"ext": ".opus", "codec": ["-acodec", "libopus", "-b:a", "128k"]},
}


def cut_audio(
    src: str,
    start_s: float,
    end_s: float,
    out_path: str,
    audio_only: bool = True,
    fmt: str = "wav",
) -> str:
    """Cut [start_s, end_s] from src into out_path."""
    if end_s <= start_s:
        raise ValueError(f"End ({end_s}) must be greater than start ({start_s}).")

    ffmpeg = _find_ffmpeg()
    duration = end_s - start_s

    fmt_info = OUTPUT_FORMATS.get(fmt, OUTPUT_FORMATS["wav"])

    # Fix extension to match format
    base, _ = os.path.splitext(out_path)
    out_path = base + fmt_info["ext"]

    # -ss before -i for fast seeking, -t for duration, re-encode for accuracy
    args = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    args += ["-ss", f"{start_s:.3f}"]
    args += ["-i", src]
    args += ["-t", f"{duration:.3f}"]

    if audio_only:
        args += ["-vn"]

    args += fmt_info["codec"]
    args += [out_path]

    kwargs = dict(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    proc = subprocess.run(args, **kwargs)
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"ffmpeg error: {err}")

    if not os.path.exists(out_path):
        raise RuntimeError(f"Output file not created: {out_path}")

    return out_path


class CutterEngine:
    """Manages a queue of CutJobs and processes them."""

    def __init__(self):
        self.queue: List[CutJob] = []
        self._running_lock = threading.Lock()
        self._running = False

    def add(self, job: CutJob) -> None:
        self.queue.append(job)

    def remove(self, index: int) -> None:
        if 0 <= index < len(self.queue):
            self.queue.pop(index)

    def remove_by_range(self, start: float, end: float) -> None:
        """Remove queued job matching the given time range."""
        self.queue = [
            j for j in self.queue
            if not (abs(j.start - start) < 0.001 and abs(j.end - end) < 0.001 and j.status == "queued")
        ]

    def update_label(self, start: float, end: float, label: str) -> None:
        """Update label of a queued job matching the given time range."""
        for j in self.queue:
            if abs(j.start - start) < 0.001 and abs(j.end - end) < 0.001 and j.status == "queued":
                j.label = label
                break

    def clear_done(self) -> None:
        self.queue = [j for j in self.queue if j.status not in ("done",)]

    def clear_all(self) -> None:
        self.queue.clear()

    def process_queue(
        self,
        output_dir: str,
        output_fmt: str = "wav",
        on_job_start: Optional[Callable[[CutJob, int], None]] = None,
        on_job_done: Optional[Callable[[CutJob, int], None]] = None,
        on_job_error: Optional[Callable[[CutJob, int, str], None]] = None,
        on_all_done: Optional[Callable[[int, int], None]] = None,
        offset_start_ms: float = 0,
        offset_end_ms: float = 0,
    ) -> None:
        """Process all queued jobs in a background thread."""

        def _run():
            with self._running_lock:
                self._running = True

            done_count = 0
            error_count = 0

            try:
                os.makedirs(output_dir, exist_ok=True)

                for i, job in enumerate(self.queue):
                    if job.status == "done":
                        done_count += 1
                        continue

                    job.status = "cutting"
                    job.error = ""
                    if on_job_start:
                        on_job_start(job, i)

                    try:
                        # Apply ^ padding markers from label
                        clean_label, adj_start, adj_end = _apply_padding(
                            job.label, job.start, job.end,
                        )
                        # Use per-job offsets first, fall back to global
                        off_s = job.offset_start_ms if job.offset_start_ms else offset_start_ms
                        off_e = job.offset_end_ms if job.offset_end_ms else offset_end_ms
                        adj_start = max(0.0, adj_start + off_s / 1000)
                        adj_end = adj_end + off_e / 1000

                        # Generate output filename from label (first few words)
                        slug = _slugify(clean_label) if clean_label else f"clip_{i+1}"
                        fmt_ext = OUTPUT_FORMATS.get(output_fmt, OUTPUT_FORMATS["wav"])["ext"]
                        out_name = f"{slug}{fmt_ext}"

                        # Avoid overwriting: append number if exists
                        out_path = os.path.join(output_dir, out_name)
                        counter = 2
                        while os.path.exists(out_path):
                            out_path = os.path.join(output_dir, f"{slug}_{counter}{fmt_ext}")
                            counter += 1

                        result_path = cut_audio(job.source_path, adj_start, adj_end, out_path, fmt=output_fmt)
                        job.output_path = result_path
                        job.status = "done"
                        done_count += 1
                        if on_job_done:
                            on_job_done(job, i)

                    except Exception as e:
                        job.status = "error"
                        job.error = str(e)
                        error_count += 1
                        if on_job_error:
                            on_job_error(job, i, str(e))
            finally:
                with self._running_lock:
                    self._running = False

            if on_all_done:
                on_all_done(done_count, error_count)

        t = threading.Thread(target=_run, daemon=True)
        t.start()

    @property
    def is_running(self) -> bool:
        with self._running_lock:
            return self._running

    @property
    def pending_count(self) -> int:
        return sum(1 for j in self.queue if j.status == "queued")

    @property
    def done_count(self) -> int:
        return sum(1 for j in self.queue if j.status == "done")
