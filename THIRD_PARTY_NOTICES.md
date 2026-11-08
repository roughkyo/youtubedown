# Third-party notices

`YTDownloader.exe` (GitHub Releases) bundles the following software.

| Component | License | Source |
|---|---|---|
| FFmpeg (`ffmpeg.exe`) | see "FFmpeg builds" below | <https://ffmpeg.org/download.html> |
| yt-dlp | The Unlicense | <https://github.com/yt-dlp/yt-dlp> |
| yt-dlp-ejs | The Unlicense | <https://github.com/yt-dlp/ejs> |
| Python | PSF License | <https://www.python.org/> |
| PyInstaller bootloader | GPL v2 with bootloader exception | <https://github.com/pyinstaller/pyinstaller> |
| Other yt-dlp dependencies (certifi, requests, urllib3, websockets, brotli, pycryptodomex, mutagen) | MPL-2.0 / Apache-2.0 / MIT / BSD / Public domain, per package | see each project on PyPI |

## FFmpeg builds

FFmpeg is included as an unmodified, separate executable that the app runs as a
subprocess. Which build is inside depends on how the release was made; the
release notes say which one.

| Release made by | FFmpeg build | License | Corresponding source |
|---|---|---|---|
| GitHub Actions (`release.yml`, weekly) | BtbN `ffmpeg-master-latest-win64-lgpl` | LGPL v2.1 or later | <https://github.com/BtbN/FFmpeg-Builds> (build scripts pin every source) |
| Manual local build | gyan.dev `ffmpeg 9.0.1 essentials_build` | GPL v3 (`--enable-gpl --enable-version3`) | FFmpeg 9.0.1: <https://ffmpeg.org/releases/> · build details and bundled libraries: <https://www.gyan.dev/ffmpeg/builds/> |

The GPL v3 text is available at <https://www.gnu.org/licenses/gpl-3.0.html>.
If you need the complete corresponding source for a GPL build and cannot obtain
it from the links above, open an issue at
<https://github.com/roughkyo/youtubedown/issues> and it will be provided.
