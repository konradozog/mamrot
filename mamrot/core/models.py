"""Mamrot – core data models."""

from dataclasses import dataclass, field
from typing import Optional, List
import json, os


@dataclass
class Word:
    """Single word with timestamp."""
    start: float
    end: float
    text: str


@dataclass
class Segment:
    """Single transcription segment."""
    idx: int
    start: float
    end: float
    text: str
    words: List[Word] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.end - self.start

    def format_range(self) -> str:
        return f"{fmt_ts(self.start)} → {fmt_ts(self.end)}"


@dataclass
class CutJob:
    """One item in the cutter queue."""
    source_path: str
    start: float
    end: float
    label: str = ""  # text preview
    output_path: str = ""
    status: str = "queued"  # queued / cutting / done / error
    error: str = ""
    offset_start_ms: float = 0  # per-segment offset
    offset_end_ms: float = 0    # per-segment offset


@dataclass
class TranscribeJob:
    """One item in the batch transcription queue."""
    source_path: str
    status: str = "queued"  # queued / running / done / error
    progress: float = 0.0
    segments: List[Segment] = field(default_factory=list)
    language_detected: str = ""
    duration: float = 0.0
    error: str = ""


WHISPER_MODELS = ["tiny", "base", "small", "medium", "large-v3"]

LANGUAGES = {
    "auto": "Auto-detect",
    "pl": "Polski",
    "en": "English",
    "de": "Deutsch",
    "fr": "Français",
    "es": "Español",
    "it": "Italiano",
    "pt": "Português",
    "nl": "Nederlands",
    "ru": "Русский",
    "uk": "Українська",
    "ja": "日本語",
    "zh": "中文",
    "ko": "한국어",
    "cs": "Čeština",
    "sv": "Svenska",
    "da": "Dansk",
    "no": "Norsk",
    "fi": "Suomi",
    "hu": "Magyar",
    "ro": "Română",
    "tr": "Türkçe",
    "ar": "العربية",
    "hi": "हिन्दी",
}


def fmt_ts(seconds: float) -> str:
    """Format seconds to HH:MM:SS.mmm"""
    total_ms = round(seconds * 1000)
    h = total_ms // 3_600_000
    m = (total_ms % 3_600_000) // 60_000
    s = (total_ms % 60_000) // 1000
    ms = total_ms % 1000
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"
    return f"{m:02d}:{s:02d}.{ms:03d}"


def fmt_ts_srt(t: float) -> str:
    """SRT timestamp format: HH:MM:SS,mmm"""
    total_ms = round(t * 1000)
    hh = total_ms // 3_600_000
    mm = (total_ms % 3_600_000) // 60_000
    ss = (total_ms % 60_000) // 1000
    ms = total_ms % 1000
    return f"{hh:02d}:{mm:02d}:{ss:02d},{ms:03d}"


def write_srt(segments: List[Segment], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, 1):
            f.write(f"{i}\n")
            f.write(f"{fmt_ts_srt(seg.start)} --> {fmt_ts_srt(seg.end)}\n")
            f.write(seg.text.strip() + "\n\n")


def write_vtt(segments: List[Segment], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write("WEBVTT\n\n")
        for seg in segments:
            ts_start = fmt_ts_srt(seg.start).replace(",", ".")
            ts_end = fmt_ts_srt(seg.end).replace(",", ".")
            f.write(f"{ts_start} --> {ts_end}\n")
            f.write(seg.text.strip() + "\n\n")


def write_csv(segments: List[Segment], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write("index,start,end,text\n")
        for seg in segments:
            text_escaped = json.dumps(seg.text.strip(), ensure_ascii=False)
            f.write(f"{seg.idx},{seg.start:.3f},{seg.end:.3f},{text_escaped}\n")


def save_transcript_json(segments: List[Segment], path: str, meta: dict) -> None:
    payload = {
        "meta": meta,
        "segments": [
            {
                "index": s.idx, "start": s.start, "end": s.end, "text": s.text,
                "words": [{"start": w.start, "end": w.end, "text": w.text} for w in s.words],
            }
            for s in segments
        ],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def load_transcript_json(path: str):
    """Load transcript JSON. Returns (segments, source_path)."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Invalid transcript file: expected object, got {type(data).__name__}")
    segments = []
    for i, s in enumerate(data.get("segments", [])):
        try:
            words = [
                Word(start=float(w["start"]), end=float(w["end"]), text=w["text"])
                for w in s.get("words", [])
            ]
            segments.append(Segment(
                idx=i, start=float(s["start"]), end=float(s["end"]),
                text=s.get("text", ""), words=words,
            ))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Invalid segment #{i} in {path}: {exc}") from exc
    source = data.get("meta", {}).get("source", "")
    return segments, source
