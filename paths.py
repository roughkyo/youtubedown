"""Where things live, both from source and inside the PyInstaller exe.

RESOURCES: read-only files shipped with the app (public/, bundled ffmpeg.exe).
APP_DIR:   where the user can find failure logs (next to the exe, or the source folder).
WORK_DIR:  scratch space for in-progress downloads; owned by the app and cleared on start.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)
SOURCE_DIR = Path(__file__).resolve().parent

if FROZEN:
    RESOURCES = Path(sys._MEIPASS)  # PyInstaller's unpack folder, deleted on exit
    APP_DIR = Path(sys.executable).resolve().parent
    WORK_DIR = Path(tempfile.gettempdir()) / "yt-downloader-web"
else:
    RESOURCES = SOURCE_DIR
    APP_DIR = SOURCE_DIR
    WORK_DIR = SOURCE_DIR / "downloads"

PUBLIC = RESOURCES / "public"
LOGS = APP_DIR / "logs"
RELEASES_URL = "https://github.com/roughkyo/youtubedown/releases/latest"


def ffmpeg_path() -> str | None:
    """Bundled ffmpeg first (exe build), then whatever is on PATH."""
    bundled = RESOURCES / "ffmpeg.exe"
    if bundled.is_file():
        return str(bundled)
    return shutil.which("ffmpeg")


def node_path() -> str | None:
    return shutil.which("node")
