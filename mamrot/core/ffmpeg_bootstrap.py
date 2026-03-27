"""Auto-download ffmpeg if not found in PATH (Windows only).

On macOS/Linux, ffmpeg should be installed via the system package manager.
"""

import os
import platform
import shutil
import zipfile
from urllib.request import urlopen, Request

_MAMROT_DIR = os.path.join(os.path.expanduser("~"), ".mamrot")
_FFMPEG_DIR = os.path.join(_MAMROT_DIR, "ffmpeg")

# Only Windows gets auto-download — macOS/Linux have package managers.
_WINDOWS_URL = (
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
    "ffmpeg-master-latest-win64-gpl.zip"
)

_INSTALL_HINTS = {
    "Darwin": "brew install ffmpeg",
    "Linux": "sudo apt install ffmpeg   # or: sudo dnf install ffmpeg",
}


def _local_ffmpeg_path() -> str:
    binary = "ffmpeg.exe" if platform.system() == "Windows" else "ffmpeg"
    return os.path.join(_FFMPEG_DIR, binary)


def _download_to_file(url: str, dest_file, on_progress=None) -> None:
    """Stream download directly to a file object. No full-file buffering."""
    req = Request(url, headers={"User-Agent": "Mamrot/0.1"})
    # timeout is per socket operation (connect + individual reads), not total
    resp = urlopen(req, timeout=30)
    total = int(resp.headers.get("Content-Length", 0))
    downloaded = 0
    while True:
        chunk = resp.read(256 * 1024)
        if not chunk:
            break
        dest_file.write(chunk)
        downloaded += len(chunk)
        if on_progress:
            on_progress(downloaded, total)


def _find_ffmpeg_in_zip(zf: zipfile.ZipFile) -> str:
    """Return the archive member path that is ffmpeg.exe."""
    for name in zf.namelist():
        if os.path.basename(name) == "ffmpeg.exe" and not name.endswith("/"):
            return name
    raise FileNotFoundError("ffmpeg.exe not found in zip archive")


def download_ffmpeg(on_progress=None) -> str:
    """Download ffmpeg to ~/.mamrot/ffmpeg/ffmpeg.exe. Returns path.

    Windows only. Raises RuntimeError on other platforms.
    on_progress: optional callback(downloaded_bytes, total_bytes).
    """
    if platform.system() != "Windows":
        hint = _INSTALL_HINTS.get(platform.system(), "")
        msg = "Auto-download is only available on Windows."
        if hint:
            msg += f"\nInstall ffmpeg with: {hint}"
        raise RuntimeError(msg)

    os.makedirs(_FFMPEG_DIR, exist_ok=True)
    dest = _local_ffmpeg_path()

    # Download to temp file first (atomic: avoids broken partial binary)
    tmp_zip = os.path.join(_FFMPEG_DIR, "ffmpeg_download.tmp")
    try:
        with open(tmp_zip, "wb") as f:
            _download_to_file(_WINDOWS_URL, f, on_progress)

        # Extract ffmpeg.exe from zip → temp path, then rename
        tmp_exe = dest + ".tmp"
        with zipfile.ZipFile(tmp_zip) as zf:
            member = _find_ffmpeg_in_zip(zf)
            with zf.open(member) as src, open(tmp_exe, "wb") as dst:
                shutil.copyfileobj(src, dst)

        # Atomic-ish rename (overwrites on Windows with os.replace)
        os.replace(tmp_exe, dest)
    finally:
        # Clean up temp files
        for p in (tmp_zip, dest + ".tmp"):
            try:
                os.remove(p)
            except OSError:
                pass

    return dest


def get_ffmpeg_path() -> str:
    """Return path to ffmpeg: system PATH first, then local download, else empty string."""
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg

    local = _local_ffmpeg_path()
    if os.path.isfile(local):
        return local

    return ""


def get_install_hint() -> str:
    """Return platform-specific install instruction, or empty string for Windows."""
    return _INSTALL_HINTS.get(platform.system(), "")
