"""Local web YouTube downloader for education (see SPEC.md).

Runs only on 127.0.0.1. Uses the yt-dlp library and ffmpeg (bundled in the exe
build, otherwise from PATH). `--check` prints the environment and exits;
`--no-browser` stops the exe from opening the browser on start.
"""
from __future__ import annotations

import errno
import json
import os
import secrets
import shutil
import sys
import threading
import traceback
import webbrowser
from datetime import date
from http import HTTPStatus
from importlib import metadata
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote, urlparse, parse_qs

import yt_dlp
from yt_dlp.utils import DownloadError

import diagnose
import paths

PUBLIC = paths.PUBLIC
DOWNLOADS = paths.WORK_DIR
HOST = "127.0.0.1"
PORT = int(os.environ.get("PORT", "8765"))
MAX_RUNNING = 2
ALLOWED_HOSTS = ("youtube.com", "youtu.be")
STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/favicon.svg": ("favicon.svg", "image/svg+xml"),
}
CANCEL_MESSAGE = "사용자에 의해 작업이 취소되었습니다."

# Mode table (SPEC.md section 2).
MODES = {
    "best": {
        "format": "bv*+ba/b",
        "outtmpl": "%(title)s (원본 %(height)sp).%(ext)s",
        # Original-quality streams are often VP9/AV1 + Opus; fall back to mkv if mp4 can't hold them.
        "merge_output_format": "mp4/mkv",
        "label": "원본 화질 영상",
        "done": "💎 원본 화질 영상 다운로드 완료!",
    },
    "1080": {
        "format": "bv*[height<=1080]+ba/b[height<=1080]/best",
        "outtmpl": "%(title)s (%(height)sp).%(ext)s",
        "merge_output_format": "mp4",
        "label": "1080p 영상",
        "done": "✨ 1080p 영상 다운로드 완료!",
    },
    "720": {
        "format": "bv*[height<=720]+ba/b[height<=720]/best",
        "outtmpl": "%(title)s (%(height)sp).%(ext)s",
        "merge_output_format": "mp4",
        "label": "720p 영상",
        "done": "👍 720p 영상 다운로드 완료!",
    },
    "480": {
        "format": "bv*[height<=480]+ba/b[height<=480]/wv*+ba/w",
        "outtmpl": "%(title)s (%(height)sp).%(ext)s",
        "merge_output_format": "mp4",
        "label": "480p 영상",
        "done": "📱 480p 영상 다운로드 완료!",
    },
    "mp3": {
        "format": "ba/b",
        "outtmpl": "%(title)s.%(ext)s",
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}
        ],
        "label": "MP3 오디오 추출",
        "done": "🎵 MP3 변환 완료!",
    },
}


UPDATE_COMMAND = "python -m pip install -U yt-dlp"
OUTDATED_DAYS = 90  # yt-dlp itself warns once a release is older than this


def _vkey(v: str) -> tuple:
    """Compare versions numerically: pip normalises 2026.07.04 to 2026.7.4."""
    return tuple(int(p) if p.isdigit() else p for p in v.split("."))


def tool_info(today: date | None = None) -> dict:
    """Installed tool versions for the page's update guide. Version strings are YYYY.MM.DD[.N]."""
    version = yt_dlp.version.__version__  # the copy loaded in this process
    installed = None
    if not paths.FROZEN:  # an exe can't be upgraded underneath itself
        try:
            installed = metadata.version("yt-dlp")  # what pip has on disk now
        except metadata.PackageNotFoundError:
            pass
    age = None
    try:
        y, m, d = (int(p) for p in version.split(".")[:3])
        age = ((today or date.today()) - date(y, m, d)).days
    except ValueError:
        pass  # unknown format: leave the age unknown rather than guessing
    return {
        "yt_dlp": version,
        "yt_dlp_installed": installed,
        # yt-dlp was upgraded while this server kept running the old copy: downloads
        # then fail with 403 until the server is restarted.
        "restart_required": installed is not None and _vkey(installed) != _vkey(version),
        "yt_dlp_age_days": age,
        "outdated": age is not None and age > OUTDATED_DAYS,
        "outdated_days": OUTDATED_DAYS,
        "frozen": paths.FROZEN,
        "update_command": None if paths.FROZEN else UPDATE_COMMAND,
        "update_url": paths.RELEASES_URL,
        "ffmpeg": paths.ffmpeg_path() is not None,
        "js_runtime": paths.node_path() is not None,
    }


def is_youtube_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    return parsed.scheme in ("http", "https") and any(
        host == h or host.endswith("." + h) for h in ALLOWED_HOSTS
    )


class Job:
    def __init__(self, url: str, mode: str):
        self.id = secrets.token_hex(6)
        self.url = url
        self.mode = mode
        self.dir = DOWNLOADS / self.id
        self.state = "running"  # running | done | cancelled | error
        self.progress = 0.0
        self.logs: list[str] = []
        self.filename: str | None = None
        self.message = ""
        self.diagnosis: dict | None = None  # set when state == "error"
        self.log_file: str | None = None    # failure log under logs/
        self.cancel_event = threading.Event()
        self.lock = threading.Lock()
        self._last_logged_decile = -1

    def log(self, text: str) -> None:
        with self.lock:
            self.logs.append(text)

    def snapshot(self, since: int) -> dict:
        with self.lock:
            return {
                "id": self.id,
                "state": self.state,
                "mode": self.mode,
                "progress": round(self.progress, 1),
                "logs": self.logs[since:],
                "next": len(self.logs),
                "filename": self.filename,
                "message": self.message,
                "diagnosis": self.diagnosis,
                "log_file": self.log_file,
            }


class JobLogger:
    """yt-dlp logger: warnings and errors get Korean prefixes."""

    def __init__(self, job: Job):
        self.job = job

    def debug(self, msg: str) -> None:
        if not msg.startswith("[debug] "):
            self.job.log(msg)

    def info(self, msg: str) -> None:
        self.job.log(msg)

    def warning(self, msg: str) -> None:
        self.job.log("[경고] " + msg)

    def error(self, msg: str) -> None:
        self.job.log("[에러] " + msg)


JOBS: dict[str, Job] = {}
JOBS_LOCK = threading.Lock()


def running_count() -> int:
    with JOBS_LOCK:
        return sum(1 for j in JOBS.values() if j.state == "running")


def run_job(job: Job) -> None:
    spec = MODES[job.mode]
    job.dir.mkdir(parents=True, exist_ok=True)

    def check_cancel_hook(d: dict) -> None:
        if job.cancel_event.is_set():
            raise DownloadError(CANCEL_MESSAGE)
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if total:
                pct = min(100.0, d.get("downloaded_bytes", 0) * 100.0 / total)
                job.progress = pct
                decile = int(pct // 10)
                if decile > job._last_logged_decile:
                    job._last_logged_decile = decile
                    job.log(f"[download] {pct:5.1f}%")
        elif d.get("status") == "finished":
            job._last_logged_decile = -1

    def check_cancel_pp(_d: dict) -> None:
        if job.cancel_event.is_set():
            raise DownloadError(CANCEL_MESSAGE)

    opts = {
        "format": spec["format"],
        "outtmpl": str(job.dir / spec["outtmpl"]),
        "noplaylist": True,
        "logger": JobLogger(job),
        "progress_hooks": [check_cancel_hook],
        "postprocessor_hooks": [check_cancel_pp],
        "noprogress": True,
        "windowsfilenames": True,
    }
    ffmpeg = paths.ffmpeg_path()
    if ffmpeg:
        opts["ffmpeg_location"] = ffmpeg
    if paths.node_path():
        # yt-dlp only enables deno by default; Node.js is its recommended alternative
        # for solving YouTube's JavaScript challenges.
        opts["js_runtimes"] = {"deno": {}, "node": {}}
    if "merge_output_format" in spec:
        opts["merge_output_format"] = spec["merge_output_format"]
    if "postprocessors" in spec:
        opts["postprocessors"] = spec["postprocessors"]

    job.log(f"🚀 [{spec['label']}] 시작합니다!")
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([job.url])
        files = [
            p for p in job.dir.iterdir()
            if p.is_file() and not p.name.endswith((".part", ".ytdl", ".temp"))
        ]
        if not files:
            raise DownloadError("다운로드된 파일을 찾지 못했습니다.")
        result = max(files, key=lambda p: p.stat().st_size)
        with job.lock:
            job.filename = result.name
            job.progress = 100.0
            job.state = "done"
            job.message = spec["done"]
        job.log("🎉 " + spec["done"])
    except Exception as exc:  # yt-dlp raises many types; report them all
        error = str(exc).removeprefix("ERROR: ")
        if job.cancel_event.is_set() or CANCEL_MESSAGE in error:
            with job.lock:
                job.state = "cancelled"
                job.message = "⛔ 사용자가 작업을 중지했습니다."
            job.log(job.message)
            shutil.rmtree(job.dir, ignore_errors=True)
            return
        job.log("💦 상세 내용: " + error)
        with job.lock:
            logs = list(job.logs)
        diagnosis = diagnose.diagnose(error, logs)
        info = tool_info()
        if info["restart_required"]:
            diagnosis = {
                "code": "restart_required",
                "title": "서버 재시작 필요",
                "cause": f"yt-dlp가 {info['yt_dlp_installed']}(으)로 업데이트되었지만 이 서버는 이전 버전 "
                         f"{info['yt_dlp']}로 실행 중입니다. ({diagnosis['title']})",
                "fix": "서버 창을 닫고 start.bat(또는 python server.py)으로 다시 실행한 뒤 다시 시도하세요.",
            }
        job.log(f"🔎 진단: {diagnosis['title']} — {diagnosis['cause']}")
        job.log(f"🛠 해결 방법: {diagnosis['fix']}")
        try:
            log_file = diagnose.write_failure_log(
                job_id=job.id, url=job.url, mode=job.mode, error=error,
                error_type=type(exc).__name__, traceback_text=traceback.format_exc(),
                logs=logs, diagnosis=diagnosis,
            )
            job.log(f"📝 실패 로그 저장: logs/{log_file}")
        except OSError as log_exc:  # never hide the download failure behind a logging failure
            log_file = None
            job.log(f"[경고] 실패 로그를 저장하지 못했습니다: {log_exc}")
        with job.lock:
            job.state = "error"
            job.message = error
            job.diagnosis = diagnosis
            job.log_file = log_file
        # Keep partial files out of downloads/; the log keeps the evidence.
        shutil.rmtree(job.dir, ignore_errors=True)


class Handler(BaseHTTPRequestHandler):
    server_version = "YTDownloaderWeb/1.0"

    def log_message(self, fmt: str, *args) -> None:  # skip status-poll noise
        if not (self.command == "GET" and self.path.startswith("/api/jobs/")):
            super().log_message(fmt, *args)

    # --- helpers -------------------------------------------------------
    def _host_ok(self) -> bool:
        # Blocks DNS-rebinding pages from reaching this local server.
        host = (self.headers.get("Host") or "").split(":")[0].lower()
        return host in ("127.0.0.1", "localhost")

    def _json(self, status: int, body: dict) -> None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _error(self, status: int, message: str) -> None:
        self._json(status, {"error": message})

    def _job(self, job_id: str) -> Job | None:
        with JOBS_LOCK:
            return JOBS.get(job_id)

    # --- routes --------------------------------------------------------
    def do_GET(self) -> None:
        if not self._host_ok():
            return self._error(HTTPStatus.FORBIDDEN, "허용되지 않은 Host입니다.")
        parsed = urlparse(self.path)
        if parsed.path in STATIC:
            name, ctype = STATIC[parsed.path]
            data = (PUBLIC / name).read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if parsed.path == "/api/info":
            return self._json(HTTPStatus.OK, tool_info())
        parts = parsed.path.strip("/").split("/")
        if len(parts) == 3 and parts[:2] == ["api", "jobs"]:
            job = self._job(parts[2])
            if not job:
                return self._error(HTTPStatus.NOT_FOUND, "작업을 찾을 수 없습니다.")
            try:
                since = max(0, int(parse_qs(parsed.query).get("since", ["0"])[0]))
            except ValueError:
                since = 0
            return self._json(HTTPStatus.OK, job.snapshot(since))
        if len(parts) == 4 and parts[:2] == ["api", "jobs"] and parts[3] == "log":
            job = self._job(parts[2])
            if not job or not job.log_file:
                return self._error(HTTPStatus.NOT_FOUND, "실패 로그가 없습니다.")
            data = (diagnose.LOGS / job.log_file).read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Content-Disposition", f"attachment; filename=\"{job.log_file}\"")
            self.end_headers()
            self.wfile.write(data)
            return
        if len(parts) == 4 and parts[:2] == ["api", "jobs"] and parts[3] == "file":
            job = self._job(parts[2])
            if not job or job.state != "done" or not job.filename:
                return self._error(HTTPStatus.NOT_FOUND, "받을 수 있는 파일이 없습니다.")
            path = job.dir / job.filename
            size = path.stat().st_size
            ascii_name = job.filename.encode("ascii", "replace").decode().replace('"', "_")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(size))
            self.send_header(
                "Content-Disposition",
                f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(job.filename)}",
            )
            self.end_headers()
            with open(path, "rb") as f:
                shutil.copyfileobj(f, self.wfile, 1024 * 256)
            return
        self._error(HTTPStatus.NOT_FOUND, "없는 경로입니다.")

    def do_POST(self) -> None:
        if not self._host_ok():
            return self._error(HTTPStatus.FORBIDDEN, "허용되지 않은 Host입니다.")
        # Requiring JSON forces a CORS preflight, which this server never approves,
        # so other web pages cannot start downloads here.
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return self._error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "JSON 요청만 받습니다.")
        parts = urlparse(self.path).path.strip("/").split("/")
        if parts == ["api", "jobs"]:
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(min(length, 8192)) or b"{}")
            except (ValueError, json.JSONDecodeError):
                return self._error(HTTPStatus.BAD_REQUEST, "요청 형식이 올바르지 않습니다.")
            url = str(body.get("url", "")).strip()
            mode = str(body.get("mode", "720"))
            if not url:
                return self._error(HTTPStatus.BAD_REQUEST, "유튜브 주소를 입력해주세요.")
            if not is_youtube_url(url):
                return self._error(HTTPStatus.BAD_REQUEST, "YouTube 주소만 받을 수 있습니다.")
            if mode not in MODES:
                return self._error(HTTPStatus.BAD_REQUEST, "형식은 best, 1080, 720, 480, mp3 중 하나여야 합니다.")
            if running_count() >= MAX_RUNNING:
                return self._error(HTTPStatus.TOO_MANY_REQUESTS, "이미 진행 중인 작업이 많습니다. 잠시 후 다시 시도해주세요.")
            job = Job(url, mode)
            with JOBS_LOCK:
                JOBS[job.id] = job
            threading.Thread(target=run_job, args=(job,), daemon=True).start()
            return self._json(HTTPStatus.CREATED, {"id": job.id})
        if len(parts) == 4 and parts[:2] == ["api", "jobs"] and parts[3] == "cancel":
            job = self._job(parts[2])
            if not job:
                return self._error(HTTPStatus.NOT_FOUND, "작업을 찾을 수 없습니다.")
            if job.state == "running":
                job.cancel_event.set()
                job.log("⛔ 작업 중지 요청됨... 잠시만 기다려주세요.")
            return self._json(HTTPStatus.OK, {"state": job.state})
        self._error(HTTPStatus.NOT_FOUND, "없는 경로입니다.")


def check() -> int:
    """--check: report the environment; non-zero when the app could not download."""
    info = tool_info()
    print(f"build     : {'exe' if paths.FROZEN else 'source'}")
    print(f"yt-dlp    : {info['yt_dlp']}")
    print(f"ffmpeg    : {paths.ffmpeg_path() or 'missing'}")
    print(f"node      : {paths.node_path() or 'none (optional)'}")
    print(f"public    : {'ok' if (PUBLIC / 'index.html').is_file() else 'missing'}")
    print(f"logs      : {paths.LOGS}")
    ok = paths.ffmpeg_path() is not None and (PUBLIC / "index.html").is_file()
    return 0 if ok else 1


def main() -> None:
    if "--check" in sys.argv[1:]:
        sys.exit(check())
    url = f"http://{HOST}:{PORT}"
    try:
        server = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE or getattr(exc, "winerror", None) == 10048:
            print(f"이미 실행 중입니다. 브라우저에서 {url} 을 엽니다.", flush=True)
            webbrowser.open(url)
            return
        raise
    # In-progress files from a previous run belong to jobs that no longer exist.
    shutil.rmtree(DOWNLOADS, ignore_errors=True)
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    print("유튜브 다운로더 (교육용 · 로컬 전용)", flush=True)
    print(f"  주소   : {url}", flush=True)
    print(f"  yt-dlp : {yt_dlp.version.__version__}   ffmpeg: {'있음' if paths.ffmpeg_path() else '없음'}", flush=True)
    print("  이 창을 닫으면 프로그램이 꺼집니다.", flush=True)
    if paths.FROZEN and "--no-browser" not in sys.argv[1:]:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
