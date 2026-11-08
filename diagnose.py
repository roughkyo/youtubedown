"""Failure analysis and failure-log writing for the web downloader.

diagnose() maps a yt-dlp / OS error (plus the job's warning lines) to a Korean
cause and fix. write_failure_log() keeps a per-job text log and appends one JSON
line to logs/failures.jsonl so repeated failures can be reviewed later.
"""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime

import yt_dlp

import paths

LOGS = paths.LOGS
_INDEX_LOCK = threading.Lock()

# How to get a newer yt-dlp depends on how the app is installed.
UPDATE_HINT = (
    f"새 버전 exe를 {paths.RELEASES_URL} 에서 받아 기존 파일과 바꾼 뒤 다시 실행하세요."
    if paths.FROZEN else
    "start.bat으로 다시 실행하거나, 터미널에서 `python -m pip install -U yt-dlp` 후 서버를 다시 실행하세요."
)

# (code, title, cause, fix, patterns) — checked in order; first match wins.
RULES: list[tuple[str, str, str, str, tuple[str, ...]]] = [
    ("age_restricted", "연령 제한 영상", "로그인해야 볼 수 있는 연령 제한 영상입니다.",
     "로그인이 필요한 영상은 이 도구로 받을 수 없습니다. 다른 자료를 사용하세요.",
     ("confirm your age", "age-restricted", "age restricted", "inappropriate for some users")),
    ("bot_check", "YouTube 봇 확인", "YouTube가 자동 접근으로 판단해 로그인 확인을 요구했습니다.",
     "잠시(수십 분) 뒤 다시 시도하세요. 짧은 시간에 많이 받으면 자주 발생합니다.",
     ("not a bot", "sign in to confirm you")),
    ("private", "비공개 영상", "비공개로 설정된 영상입니다.", "영상 소유자에게 공개 여부를 확인하세요.",
     ("private video", "video is private")),
    ("members_only", "회원 전용 영상", "채널 멤버십 회원만 볼 수 있는 영상입니다.", "회원 전용 영상은 받을 수 없습니다.",
     ("members-only", "members only", "join this channel")),
    ("geo_blocked", "지역 제한", "현재 국가에서 볼 수 없도록 제한된 영상입니다.", "지역 제한 영상은 받을 수 없습니다.",
     ("available in your country", "geo restrict", "geo-restrict", "blocked it in your country")),
    ("copyright", "저작권 차단", "저작권 신고로 차단된 영상입니다.", "저작권 문제로 차단된 영상은 받을 수 없습니다.",
     ("copyright claim", "copyright grounds", "blocked it on copyright")),
    ("unavailable", "이용할 수 없는 영상", "삭제되었거나 주소가 잘못된 영상입니다.",
     "브라우저에서 주소를 열어 영상이 재생되는지 확인하세요.",
     ("video unavailable", "video is unavailable", "has been removed", "account associated with this video has been terminated",
      "this video is no longer available", "incomplete youtube id", "does not exist")),
    ("live", "라이브·예정 영상", "아직 시작하지 않았거나 진행 중인 라이브 방송입니다.",
     "방송이 끝나고 다시보기가 올라온 뒤에 받으세요.",
     ("live event will begin", "premieres in", "this live event", "will begin in")),
    ("format_unavailable", "선택한 화질 없음", "이 영상에는 선택한 형식(화질)이 없습니다.",
     "다른 화질(예: 원본 화질 또는 720p)을 선택해 다시 시도하세요.",
     ("requested format is not available", "no video formats found", "format is not available")),
    ("ffmpeg_missing", "ffmpeg 없음", "영상·음성을 합치거나 MP3로 바꾸는 ffmpeg를 찾지 못했습니다.",
     "ffmpeg를 설치하고 PATH에 등록한 뒤 서버를 다시 실행하세요.",
     ("ffmpeg not found", "ffprobe and ffmpeg not found", "ffmpeg is not installed",
      "ffprobe/avprobe and ffmpeg/avconv not found")),
    ("postprocess", "변환 실패", "다운로드 후 파일을 합치거나 변환하는 단계에서 실패했습니다.",
     "다른 형식을 선택하거나 ffmpeg를 최신 버전으로 업데이트하세요.",
     ("postprocessing", "conversion failed", "error opening output", "invalid data found when processing input")),
    ("rate_limited", "요청 과다", "짧은 시간에 요청이 너무 많아 YouTube가 일시적으로 차단했습니다.",
     "잠시 뒤 다시 시도하세요.",
     ("http error 429", "too many requests")),
    ("forbidden", "접근 거부(403)", "YouTube가 다운로드 요청을 거부했습니다. yt-dlp가 오래된 경우 자주 발생합니다.",
     "{update}",
     ("http error 403", "403: forbidden")),
    ("extractor_outdated", "추출기 오류", "YouTube 페이지 구조가 바뀌어 yt-dlp가 영상 정보를 읽지 못했습니다.",
     "{update}",
     ("unable to extract", "nsig extraction failed", "signature extraction failed", "n challenge",
      "please report this issue", "confirm you are on the latest version")),
    ("network", "네트워크 오류", "인터넷 연결이 끊겼거나 응답이 너무 늦습니다.",
     "인터넷 연결을 확인하고 다시 시도하세요.",
     ("unable to download webpage", "getaddrinfo failed", "timed out", "connection reset", "connection refused",
      "connection aborted", "network is unreachable", "urlopen error", "name or service not known",
      "temporary failure in name resolution", "remote end closed connection", "ssl:")),
    ("disk_full", "저장 공간 부족", "디스크 공간이 부족해 파일을 저장하지 못했습니다.",
     "디스크 공간을 확보한 뒤 다시 시도하세요.",
     ("no space left", "errno 28", "winerror 112", "disk full")),
    ("file_locked", "파일 접근 오류", "다른 프로그램이 파일을 사용 중이거나 쓰기 권한이 없습니다.",
     "downloads 폴더의 파일을 연 프로그램을 닫고 다시 시도하세요.",
     ("permission denied", "winerror 5", "winerror 32", "access is denied", "being used by another process")),
    ("unsupported_url", "지원하지 않는 주소", "영상 주소로 인식할 수 없습니다.", "영상 페이지의 주소를 그대로 복사해 넣으세요.",
     ("unsupported url", "is not a valid url")),
    ("no_file", "결과 파일 없음", "다운로드는 끝났지만 저장된 파일을 찾지 못했습니다.",
     "다시 시도하고, 반복되면 로그 파일을 확인하세요.",
     ("다운로드된 파일을 찾지 못했습니다",)),
    # Only reached through warning lines when the error itself matched nothing above.
    ("outdated_ytdlp", "yt-dlp 업데이트 필요", "yt-dlp가 오래되어 YouTube 변경을 따라가지 못했을 가능성이 큽니다.",
     "{update}",
     ("older than 90 days", "is out of date")),
]

UNKNOWN = ("unknown", "알 수 없는 오류", "분류되지 않은 오류입니다.",
           "로그 파일을 내려받아 오류 내용을 확인하세요. yt-dlp 업데이트로 해결되는 경우가 많습니다: {update}")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).lower()


def diagnose(error: str, logs: list[str]) -> dict:
    """Classify a failure. The error message wins; then the latest error/warning lines."""
    sources = [error] + [l for l in reversed(logs) if l.startswith(("[에러]", "[경고]"))]
    for source in sources:
        text = _norm(source)
        for code, title, cause, fix, patterns in RULES:
            if any(p.lower() in text for p in patterns):
                return {"code": code, "title": title, "cause": cause, "fix": fix.format(update=UPDATE_HINT)}
    code, title, cause, fix = UNKNOWN
    return {"code": code, "title": title, "cause": cause, "fix": fix.format(update=UPDATE_HINT)}


def environment() -> dict:
    return {
        "yt_dlp": yt_dlp.version.__version__,
        "ffmpeg": paths.ffmpeg_path(),
        "js_runtime": paths.node_path(),
        "build": "exe" if paths.FROZEN else "source",
    }


def write_failure_log(*, job_id: str, url: str, mode: str, error: str, error_type: str,
                      traceback_text: str, logs: list[str], diagnosis: dict) -> str:
    """Write logs/<time>_<id>.log and append logs/failures.jsonl. Returns the log file name."""
    LOGS.mkdir(exist_ok=True)
    now = datetime.now().astimezone()
    name = f"{now:%Y%m%d-%H%M%S}_{job_id}.log"
    env = environment()
    lines = [
        "# 유튜브 다운로더 실패 로그",
        f"시각       : {now.isoformat(timespec='seconds')}",
        f"작업 ID    : {job_id}",
        f"주소       : {url}",
        f"형식       : {mode}",
        f"진단       : [{diagnosis['code']}] {diagnosis['title']}",
        f"원인       : {diagnosis['cause']}",
        f"해결 방법  : {diagnosis['fix']}",
        f"오류 종류  : {error_type}",
        f"오류 메시지: {error}",
        f"yt-dlp     : {env['yt_dlp']}",
        f"ffmpeg     : {env['ffmpeg'] or '없음'}",
        f"JS 런타임  : {env['js_runtime'] or '없음'}",
        "",
        "## 진행 로그",
        *logs,
        "",
        "## Traceback",
        traceback_text.rstrip(),
        "",
    ]
    # LF on every OS so the saved file and the /log download are byte-identical.
    (LOGS / name).write_text("\n".join(lines), encoding="utf-8", newline="\n")
    record = {
        "time": now.isoformat(timespec="seconds"),
        "id": job_id,
        "url": url,
        "mode": mode,
        "code": diagnosis["code"],
        "title": diagnosis["title"],
        "error_type": error_type,
        "error": error,
        "log_file": name,
        **env,
    }
    with _INDEX_LOCK, open(LOGS / "failures.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return name
