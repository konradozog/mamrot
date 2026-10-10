"""Mamrot – transcriber engine (faster-whisper wrapper)."""

import os
import threading
from typing import Optional, Callable, List

from .models import (
    Segment, Word, TranscribeJob, fmt_ts,
    write_srt, write_vtt, write_csv, save_transcript_json,
)


def collect_chunks(audio, chunks, sampling_rate=16000, max_duration=float("inf")):
    """faster-whisper's `vad.collect_chunks` (1.1.0 - 1.2.1) with the same
    output, minus its quadratic cost.

    Upstream grows the speech audio by one `np.concatenate` per VAD chunk, so
    every chunk copies all the speech before it. With thousands of chunks
    (an 11 h recording has ~7700) that alone takes ~17 min before the first
    segment appears. Here the slices are collected in a list and concatenated
    once per output chunk.
    """
    import numpy as np

    if not chunks:
        return [np.array([], dtype=np.float32)], [
            {"offset": 0, "duration": 0, "segments": []}
        ]

    audio_chunks = []
    chunks_metadata = []
    pieces = []
    segments = []
    current = 0
    total = 0

    def _flush():
        audio_chunks.append(
            np.concatenate(pieces) if pieces else np.array([], dtype=np.float32)
        )
        chunks_metadata.append({
            "offset": total / sampling_rate,
            "duration": current / sampling_rate,
            "segments": segments,
        })

    for chunk in chunks:
        length = chunk["end"] - chunk["start"]
        if current + length > max_duration * sampling_rate:
            _flush()
            total += current
            # As upstream: a chunk that opens a new output chunk is not
            # listed in that chunk's segments.
            pieces, segments, current = [], [], 0
        else:
            segments.append(chunk)
        pieces.append(audio[chunk["start"]:chunk["end"]])
        current += length

    _flush()
    return audio_chunks, chunks_metadata


def _install_linear_collect_chunks() -> None:
    """Make `WhisperModel.transcribe` use the linear `collect_chunks`."""
    import faster_whisper.transcribe

    faster_whisper.transcribe.collect_chunks = collect_chunks


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

        _install_linear_collect_chunks()
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
