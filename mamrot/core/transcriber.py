"""Mamrot – transcriber engine (faster-whisper wrapper)."""

import os
import threading
from typing import Optional, Callable, List

from .models import (
    Segment, Word, TranscribeJob, fmt_ts,
    write_srt, write_vtt, write_csv, save_transcript_json,
)


class TranscriberEngine:
    """Wraps faster-whisper. Runs transcription in a background thread."""

    def __init__(self):
        self._model = None
        self._model_name: str = ""
        self._device: str = ""
        self._compute_type: str = ""

    def load_model(
        self,
        model_name: str = "small",
        device: str = "auto",
        compute_type: str = "auto",
        on_status: Optional[Callable[[str], None]] = None,
    ) -> None:
        """Load (or reload) the whisper model."""
        # Resolve 'auto' device
        if device == "auto":
            try:
                import ctranslate2
                ctranslate2.get_supported_compute_types("cuda")
                device = "cuda"
            except Exception:
                device = "cpu"

        # Resolve 'auto' compute type
        if compute_type == "auto":
            compute_type = "float16" if device == "cuda" else "int8"

        # Skip reload if same model already loaded
        if (
            self._model is not None
            and self._model_name == model_name
            and self._device == device
            and self._compute_type == compute_type
        ):
            if on_status:
                on_status(f"Model {model_name} already loaded.")
            return

        if on_status:
            on_status(f"Loading model {model_name} on {device} ({compute_type})...")

        from faster_whisper import WhisperModel

        self._model = WhisperModel(model_name, device=device, compute_type=compute_type)
        self._model_name = model_name
        self._device = device
        self._compute_type = compute_type

        if on_status:
            on_status(f"Model {model_name} ready ({device}/{compute_type}).")

    def transcribe(
        self,
        job: TranscribeJob,
        language: Optional[str] = None,
        beam_size: int = 5,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        on_progress: Optional[Callable[[TranscribeJob], None]] = None,
        on_done: Optional[Callable[[TranscribeJob], None]] = None,
        on_error: Optional[Callable[[TranscribeJob, str], None]] = None,
    ) -> None:
        """Run transcription in background thread."""

        def _run():
            try:
                if self._model is None:
                    raise RuntimeError("Model not loaded. Call load_model() first.")

                job.status = "running"
                job.progress = 0.0
                if on_progress:
                    on_progress(job)

                lang = language if language and language != "auto" else None

                segments_iter, info = self._model.transcribe(
                    job.source_path,
                    language=lang,
                    vad_filter=True,
                    vad_parameters=dict(
                        min_silence_duration_ms=300,
                        threshold=0.5,
                        speech_pad_ms=30,
                    ),
                    beam_size=beam_size,
                    word_timestamps=True,
                )

                job.duration = info.duration
                job.language_detected = info.language or "?"
                duration = info.duration if info.duration > 0 else 1.0

                segs: List[Segment] = []
                for seg in segments_iter:
                    words = []
                    if seg.words:
                        words = [
                            Word(start=float(w.start), end=float(w.end), text=w.word)
                            for w in seg.words
                        ]

                    s = Segment(
                        idx=len(segs),
                        start=float(seg.start),
                        end=float(seg.end),
                        text=seg.text or "",
                        words=words,
                    )

                    # If fragment mode, skip segments outside range
                    if start_time is not None and s.end < start_time:
                        continue
                    if end_time is not None and s.start > end_time:
                        continue

                    segs.append(s)
                    job.segments = segs
                    job.progress = min(float(seg.end) / duration, 1.0)
                    if on_progress:
                        on_progress(job)

                # Re-index
                for i, s in enumerate(segs):
                    s.idx = i

                job.segments = segs
                job.progress = 1.0
                job.status = "done"

                # Save outputs
                self._save_outputs(job)

                if on_done:
                    on_done(job)

            except Exception as e:
                job.status = "error"
                job.error = str(e)
                if on_error:
                    on_error(job, str(e))

        t = threading.Thread(target=_run, daemon=True)
        t.start()

    def _save_outputs(self, job: TranscribeJob) -> None:
        """Write SRT, VTT, CSV, JSON next to source file."""
        if not job.segments:
            return

        base = os.path.splitext(job.source_path)[0]

        write_srt(job.segments, base + ".srt")
        write_vtt(job.segments, base + ".vtt")
        write_csv(job.segments, base + ".csv")
        save_transcript_json(
            job.segments,
            base + ".transcript.json",
            meta={
                "model": self._model_name,
                "device": self._device,
                "compute_type": self._compute_type,
                "language_detected": job.language_detected,
                "duration_seconds": round(job.duration, 2),
                "source": os.path.abspath(job.source_path),
                "total_segments": len(job.segments),
            },
        )

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    @property
    def current_model_info(self) -> str:
        if self._model is None:
            return "No model loaded"
        return f"{self._model_name} ({self._device}/{self._compute_type})"
