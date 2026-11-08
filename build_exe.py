"""Build dist/YTDownloader.exe with PyInstaller.

    python build_exe.py --ffmpeg C:\\path\\to\\ffmpeg.exe

Used locally and by .github/workflows/release.yml. The exe bundles the current
yt-dlp (+ yt-dlp-ejs) and the given ffmpeg, so it must be rebuilt regularly;
the workflow does that weekly.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ffmpeg", required=True, help="path to a real ffmpeg.exe (not a shim)")
    args = parser.parse_args()

    ffmpeg = Path(args.ffmpeg).resolve()
    # Chocolatey/scoop shims are tiny launchers that break once copied elsewhere.
    if not ffmpeg.is_file() or ffmpeg.stat().st_size < 5_000_000:
        print(f"error: {ffmpeg} is missing or looks like a shim, not ffmpeg itself", file=sys.stderr)
        return 2

    sep = os.pathsep
    cmd = [
        sys.executable, "-m", "PyInstaller", str(ROOT / "server.py"),
        "--name", "YTDownloader",
        "--onefile", "--console", "--noconfirm", "--clean",
        "--distpath", str(ROOT / "dist"),
        "--workpath", str(ROOT / "build"),
        "--specpath", str(ROOT / "build"),
        "--add-data", f"{ROOT / 'public'}{sep}public",
        "--add-binary", f"{ffmpeg}{sep}.",
        # yt-dlp imports extractors lazily; yt-dlp-ejs ships its solver as data files.
        "--collect-submodules", "yt_dlp",
        "--collect-data", "yt_dlp_ejs",
        "--copy-metadata", "yt-dlp",
    ]
    print(" ".join(cmd), flush=True)
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode:
        return result.returncode
    exe = ROOT / "dist" / "YTDownloader.exe"
    print(f"built {exe} ({exe.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
