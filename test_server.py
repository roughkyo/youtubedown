"""Tests for server.py.  python test_server.py [--live]

--live also runs real downloads (network + YouTube) through the public HTTP API.
"""
import http.client
import json
import shutil
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from yt_dlp.utils import DownloadError

import diagnose
import server

LIVE = "--live" in sys.argv
if LIVE:
    sys.argv.remove("--live")

SHORT_VIDEO = "https://www.youtube.com/watch?v=jNQXAC9IVRw"  # "Me at the zoo", 19 s
LONG_VIDEO = "https://www.youtube.com/watch?v=aqz-KE-bpKQ"   # Big Buck Bunny (CC-BY), ~10 min


class Client:
    def __init__(self, port):
        self.port = port

    def request(self, method, path, body=None, headers=None, raw=False):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        hdrs = {"Host": f"127.0.0.1:{self.port}"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            hdrs["Content-Type"] = "application/json"
        hdrs.update(headers or {})
        conn.request(method, path, body=data, headers=hdrs)
        res = conn.getresponse()
        payload = res.read()
        conn.close()
        if raw:
            return res, payload
        return res.status, json.loads(payload or b"{}")

    def wait(self, job_id, timeout=300):
        deadline = time.time() + timeout
        logs = []
        while time.time() < deadline:
            _, job = self.request("GET", f"/api/jobs/{job_id}?since={len(logs)}")
            logs += job["logs"]
            if job["state"] != "running":
                job["all_logs"] = logs
                return job
            time.sleep(0.5)
        raise AssertionError("job did not finish in time")


class ServerTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.DOWNLOADS.mkdir(exist_ok=True)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.client = Client(cls.httpd.server_address[1])

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()


class UrlValidation(unittest.TestCase):
    def test_accepts_youtube_hosts(self):
        for url in ("https://www.youtube.com/watch?v=x", "https://youtu.be/x",
                    "https://music.youtube.com/watch?v=x", "http://m.youtube.com/watch?v=x"):
            self.assertTrue(server.is_youtube_url(url), url)

    def test_rejects_lookalikes_and_other_schemes(self):
        for url in ("https://youtube.com.evil.example/x", "https://evilyoutube.com/x",
                    "ftp://youtube.com/x", "file:///C:/x", "javascript:alert(1)", "not a url"):
            self.assertFalse(server.is_youtube_url(url), url)


class Api(ServerTestBase):
    def test_serves_page_and_assets(self):
        for path, ctype in (("/", "text/html"), ("/app.js", "text/javascript"),
                            ("/style.css", "text/css"), ("/favicon.svg", "image/svg+xml")):
            res, body = self.client.request("GET", path, raw=True)
            self.assertEqual(res.status, 200, path)
            self.assertTrue(res.getheader("Content-Type").startswith(ctype), path)
            self.assertTrue(body)

    def test_no_path_traversal(self):
        res, _ = self.client.request("GET", "/../server.py", raw=True)
        self.assertEqual(res.status, 404)

    def test_rejects_foreign_host_header(self):
        status, _ = self.client.request("GET", "/", headers={"Host": "evil.example"})
        self.assertEqual(status, 403)

    def test_rejects_non_json_post(self):
        status, _ = self.client.request("POST", "/api/jobs", headers={"Content-Type": "text/plain"})
        self.assertEqual(status, 415)

    def test_input_validation_messages(self):
        cases = [
            ({"url": "", "mode": "720"}, "유튜브 주소를 입력해주세요."),
            ({"url": "https://example.com/v", "mode": "720"}, "YouTube 주소만 받을 수 있습니다."),
            ({"url": SHORT_VIDEO, "mode": "4k"}, "형식은 best, 1080, 720, 480, mp3 중 하나여야 합니다."),
        ]
        for body, message in cases:
            status, res = self.client.request("POST", "/api/jobs", body)
            self.assertEqual((status, res.get("error")), (400, message), body)

    def test_unknown_job(self):
        self.assertEqual(self.client.request("GET", "/api/jobs/nope")[0], 404)
        self.assertEqual(self.client.request("GET", "/api/jobs/nope/file")[0], 404)
        self.assertEqual(self.client.request("POST", "/api/jobs/nope/cancel", {})[0], 404)


class ToolInfo(ServerTestBase):
    def test_age_and_outdated_flag(self):
        from datetime import date
        with mock.patch.object(server.yt_dlp.version, "__version__", "2026.07.04"):
            fresh = server.tool_info(today=date(2026, 8, 1))
            old = server.tool_info(today=date(2026, 11, 8))
        self.assertEqual((fresh["yt_dlp_age_days"], fresh["outdated"]), (28, False))
        self.assertEqual((old["yt_dlp_age_days"], old["outdated"]), (127, True))
        self.assertEqual(old["update_command"], "python -m pip install -U yt-dlp")

    def test_patch_release_and_unknown_versions(self):
        from datetime import date
        with mock.patch.object(server.yt_dlp.version, "__version__", "2026.07.04.1"):
            self.assertEqual(server.tool_info(today=date(2026, 7, 14))["yt_dlp_age_days"], 10)
        with mock.patch.object(server.yt_dlp.version, "__version__", "nightly-abc"):
            info = server.tool_info()
        self.assertEqual((info["yt_dlp_age_days"], info["outdated"]), (None, False))

    def test_info_endpoint(self):
        status, info = self.client.request("GET", "/api/info")
        self.assertEqual(status, 200)
        self.assertEqual(info["yt_dlp"], server.yt_dlp.version.__version__)
        for key in ("yt_dlp_age_days", "outdated", "update_command", "ffmpeg", "js_runtime"):
            self.assertIn(key, info)


class Diagnosis(unittest.TestCase):
    CASES = {
        "ERROR: [youtube] abc: Private video. Sign in if you've been granted access": "private",
        "ERROR: [youtube] abc: Sign in to confirm your age. This video may be inappropriate": "age_restricted",
        "ERROR: [youtube] abc: Sign in to confirm you're not a bot.": "bot_check",
        "ERROR: [youtube] abc: Video unavailable. This video has been removed by the uploader": "unavailable",
        "ERROR: [youtube] aaaaaaaaaaa: This video is unavailable": "unavailable",  # real 2026 wording
        "ERROR: [youtube] abc: The uploader has not made this video available in your country": "geo_blocked",
        "ERROR: [youtube] abc: This live event will begin in 3 hours.": "live",
        "ERROR: [youtube] abc: Requested format is not available. Use --list-formats": "format_unavailable",
        "ERROR: Postprocessing: ffprobe and ffmpeg not found. Please install or provide the path": "ffmpeg_missing",
        "ERROR: unable to download video data: HTTP Error 403: Forbidden": "forbidden",
        "ERROR: Unable to download webpage: HTTP Error 429: Too Many Requests": "rate_limited",
        "ERROR: [youtube] abc: Unable to download webpage: <urlopen error [Errno 11001] getaddrinfo failed>": "network",
        "ERROR: Unable to extract nsig function code; please report this issue": "extractor_outdated",
        "[Errno 28] No space left on device": "disk_full",
        "[WinError 32] The process cannot access the file because it is being used by another process": "file_locked",
        "다운로드된 파일을 찾지 못했습니다.": "no_file",
        "something nobody has seen before": "unknown",
    }

    def test_rules(self):
        for message, code in self.CASES.items():
            self.assertEqual(diagnose.diagnose(message, [])["code"], code, message)

    def test_warning_lines_explain_unknown_errors(self):
        logs = ["[경고] Your yt-dlp version (2026.07.04) is older than 90 days!"]
        self.assertEqual(diagnose.diagnose("weird failure", logs)["code"], "outdated_ytdlp")
        # ...but a recognised error message always wins over warnings.
        self.assertEqual(diagnose.diagnose("Private video", logs)["code"], "private")


class FailureLogging(ServerTestBase):
    """A failing download (fake yt-dlp, no network) must be diagnosed and logged."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        patcher = mock.patch.object(diagnose, "LOGS", self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_failed_job_writes_log_and_diagnosis(self):
        class FailingYDL:
            def __init__(self, opts):
                self.logger = opts["logger"]

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def download(self, urls):
                self.logger.warning("[youtube] abc: some warning")
                raise DownloadError("ERROR: [youtube] abc: Private video. Sign in if you've been granted access")

        with mock.patch.object(server.yt_dlp, "YoutubeDL", FailingYDL):
            status, res = self.client.request("POST", "/api/jobs", {"url": SHORT_VIDEO, "mode": "480"})
            self.assertEqual(status, 201, res)
            job = self.client.wait(res["id"], timeout=10)

        self.assertEqual(job["state"], "error")
        self.assertEqual(job["diagnosis"]["code"], "private")
        self.assertTrue(job["message"].startswith("[youtube] abc: Private video"), job["message"])
        self.assertTrue(any(l.startswith("🔎 진단: 비공개 영상") for l in job["all_logs"]))
        self.assertFalse((server.DOWNLOADS / res["id"]).exists(), "failed job folder should be removed")

        log_path = self.tmp / job["log_file"]
        text = log_path.read_text(encoding="utf-8")
        for needle in ("진단       : [private] 비공개 영상", f"주소       : {SHORT_VIDEO}",
                       "형식       : 480", "[경고] [youtube] abc: some warning", "DownloadError"):
            self.assertIn(needle, text)

        records = [json.loads(l) for l in (self.tmp / "failures.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertEqual((rec["id"], rec["code"], rec["mode"], rec["log_file"]),
                         (res["id"], "private", "480", job["log_file"]))
        self.assertRegex(rec["time"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$")

        resp, body = self.client.request("GET", f"/api/jobs/{res['id']}/log", raw=True)
        self.assertEqual(resp.status, 200)
        self.assertEqual(body.decode("utf-8"), text)

    def test_cancel_is_not_logged_as_failure(self):
        class CancelledYDL:
            def __init__(self, opts):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def download(self, urls):
                raise DownloadError(server.CANCEL_MESSAGE)

        with mock.patch.object(server.yt_dlp, "YoutubeDL", CancelledYDL):
            _, res = self.client.request("POST", "/api/jobs", {"url": SHORT_VIDEO, "mode": "720"})
            job = self.client.wait(res["id"], timeout=10)
        self.assertEqual(job["state"], "cancelled")
        self.assertIsNone(job["log_file"])
        self.assertFalse((self.tmp / "failures.jsonl").exists())


@unittest.skipUnless(LIVE, "pass --live to run real downloads")
class LiveDownloads(ServerTestBase):
    def _download(self, mode, expected_ext, done_message):
        status, res = self.client.request("POST", "/api/jobs", {"url": SHORT_VIDEO, "mode": mode})
        self.assertEqual(status, 201, res)
        job = self.client.wait(res["id"])
        self.assertEqual(job["state"], "done", "\n".join(job["all_logs"]))
        self.assertEqual(job["message"], done_message)
        self.assertTrue(job["filename"].endswith(expected_ext), job["filename"])
        self.assertIn("🎉 " + done_message, job["all_logs"])
        res, body = self.client.request("GET", f"/api/jobs/{res['id']}/file", raw=True)
        self.assertEqual(res.status, 200)
        self.assertIn("filename*=UTF-8''", res.getheader("Content-Disposition"))
        on_disk = (server.DOWNLOADS / job["id"] / job["filename"]).stat().st_size
        self.assertEqual(len(body), on_disk)
        self.assertGreater(on_disk, 10_000)
        print(f"\n  {mode}: {job['filename']} ({on_disk:,} bytes)")
        return job

    def test_mp3(self):
        self._download("mp3", ".mp3", "🎵 MP3 변환 완료!")

    def test_720_mp4(self):
        job = self._download("720", ".mp4", "👍 720p 영상 다운로드 완료!")
        self.assertRegex(job["filename"], r"\(\d+p\)\.mp4$")

    def test_480_mp4(self):
        job = self._download("480", ".mp4", "📱 480p 영상 다운로드 완료!")
        self.assertRegex(job["filename"], r"\(\d+p\)\.(mp4)$")

    def test_best_original_quality(self):
        job = self._download("best", "", "💎 원본 화질 영상 다운로드 완료!")
        self.assertRegex(job["filename"], r"\(원본 \d+p\)\.(mp4|mkv)$")

    def test_real_failure_is_diagnosed_and_logged(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        with mock.patch.object(diagnose, "LOGS", tmp):
            # Well-formed but non-existent video ID.
            _, res = self.client.request("POST", "/api/jobs", {"url": "https://www.youtube.com/watch?v=aaaaaaaaaaa", "mode": "720"})
            job = self.client.wait(res["id"], timeout=120)
        self.assertEqual(job["state"], "error", "\n".join(job["all_logs"]))
        self.assertEqual(job["diagnosis"]["code"], "unavailable", job["message"])
        self.assertTrue((tmp / job["log_file"]).exists())
        print(f"\n  failure: [{job['diagnosis']['code']}] {job['message']}")

    def test_cancel(self):
        status, res = self.client.request("POST", "/api/jobs", {"url": LONG_VIDEO, "mode": "1080"})
        self.assertEqual(status, 201, res)
        deadline = time.time() + 60
        while time.time() < deadline:  # cancel once bytes are actually flowing
            _, job = self.client.request("GET", f"/api/jobs/{res['id']}")
            if job["progress"] > 0 or job["state"] != "running":
                break
            time.sleep(0.3)
        self.client.request("POST", f"/api/jobs/{res['id']}/cancel", {})
        job = self.client.wait(res["id"], timeout=60)
        self.assertEqual(job["state"], "cancelled", "\n".join(job["all_logs"]))
        self.assertEqual(job["message"], "⛔ 사용자가 작업을 중지했습니다.")
        self.assertFalse((server.DOWNLOADS / res["id"]).exists(), "partial files should be removed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
