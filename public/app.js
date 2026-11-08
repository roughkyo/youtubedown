// Web front end for the local YouTube downloader. Talks to server.py over JSON.
const $ = (id) => document.getElementById(id);
const form = $("form"), urlInput = $("url"), startBtn = $("start"), stopBtn = $("stop");
const bar = $("bar"), statusEl = $("status"), logEl = $("log"), saveLink = $("save");
const diagBox = $("diag"), diagLog = $("diag-log");
const MODE_LABELS = { best: "원본 화질 영상", "1080": "1080p 영상", "720": "720p 영상", "480": "480p 영상", mp3: "MP3 오디오 추출" };

function showDiagnosis(job) {
  const d = job.diagnosis;
  if (!d) return;
  $("diag-title").textContent = d.title;
  $("diag-cause").textContent = d.cause;
  $("diag-fix").textContent = d.fix;
  diagLog.hidden = !job.log_file;
  if (job.log_file) {
    diagLog.href = `/api/jobs/${job.id}/log`;
    diagLog.textContent = `실패 로그 받기 (${job.log_file})`;
  }
  diagBox.hidden = false;
}

let jobId = null, since = 0, timer = null;

function appendLog(lines) {
  if (!lines.length) return;
  logEl.textContent += lines.join("\n") + "\n";
  logEl.scrollTop = logEl.scrollHeight;
}

function setRunning(running) {
  startBtn.disabled = running;
  stopBtn.disabled = !running;
  urlInput.disabled = running;
  startBtn.textContent = running ? "다운로드 중..." : "다운로드 시작";
}

function setStatus(text, kind = "") {
  statusEl.textContent = text;
  statusEl.className = "status " + kind;
}

async function api(path, body) {
  const res = await fetch(path, body === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `요청 실패 (${res.status})`);
  return data;
}

async function poll() {
  try {
    const job = await api(`/api/jobs/${jobId}?since=${since}`);
    since = job.next;
    appendLog(job.logs);
    bar.style.width = job.progress + "%";
    if (job.state === "running") return;
    clearInterval(timer);
    setRunning(false);
    if (job.state === "done") {
      setStatus(job.message, "ok");
      saveLink.href = `/api/jobs/${jobId}/file`;
      saveLink.textContent = `파일 저장하기 — ${job.filename}`;
      saveLink.hidden = false;
      saveLink.click(); // start the browser download right away
    } else if (job.state === "cancelled") {
      setStatus("작업이 중지되었습니다.", "fail");
      bar.style.width = "0";
    } else {
      setStatus("다운로드에 실패했습니다.", "fail");
      showDiagnosis(job);
    }
  } catch (err) {
    clearInterval(timer);
    setRunning(false);
    setStatus("서버와 연결이 끊겼습니다: " + err.message, "fail");
  }
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const url = urlInput.value.trim();
  if (!url) return setStatus("유튜브 주소를 입력해주세요.", "fail");
  const mode = form.elements.mode.value;
  const label = MODE_LABELS[mode];
  logEl.textContent = "";
  saveLink.hidden = true;
  diagBox.hidden = true;
  bar.style.width = "0";
  setStatus(`[${label}] 준비 중...`);
  setRunning(true);
  try {
    jobId = (await api("/api/jobs", { url, mode })).id;
    since = 0;
    timer = setInterval(poll, 700);
  } catch (err) {
    setRunning(false);
    setStatus(err.message, "fail");
  }
});

// Per-mode hint under the format cards.
const MODE_HINTS = {
  best: ["원본 화질은 4K·AV1인 경우가 많아 오래된 PC에서 재생되지 않을 수 있고 파일이 큽니다. 수업용은 1080p·720p를 권장합니다.", "warn"],
  "1080": ["FHD 화질입니다. 큰 화면 수업 송출에 적합합니다.", ""],
  "720": ["가장 무난한 기본 화질입니다.", ""],
  "480": ["파일이 가볍습니다. 학생 배포나 느린 네트워크에 적합합니다.", ""],
  mp3: ["음성만 MP3(192kbps)로 저장합니다.", ""],
};
const modeHint = $("mode-hint");
function updateModeHint() {
  const [text, kind] = MODE_HINTS[form.elements.mode.value] || ["", ""];
  modeHint.textContent = text;
  modeHint.className = "mode-hint " + kind;
}
form.addEventListener("change", (e) => { if (e.target.name === "mode") updateModeHint(); });
updateModeHint();

// yt-dlp version / update guide.
async function loadToolInfo() {
  try {
    const info = await api("/api/info");
    const box = $("version-box"), text = $("version-text");
    const age = info.yt_dlp_age_days;
    text.textContent = `yt-dlp ${info.yt_dlp}` + (age === null ? " (출시일 확인 불가)" : ` · 출시 ${age}일 경과`) +
      (info.outdated ? ` — ${info.outdated_days}일이 지나 업데이트를 권장합니다.` : " — 최신 상태에 가깝습니다.");
    box.classList.add(info.outdated ? "old" : "ok");
    $("update-cmd").textContent = info.update_command;
    if (info.outdated) {
      const alert = $("update-alert");
      alert.textContent = `⚠ yt-dlp(${info.yt_dlp})가 ${age}일 지난 버전입니다. 다운로드가 실패하면 업데이트하세요 →`;
      alert.hidden = false;
    }
  } catch (err) {
    $("version-text").textContent = "버전을 확인하지 못했습니다: " + err.message;
  }
}
loadToolInfo();

$("copy-cmd").addEventListener("click", async (e) => {
  const btn = e.currentTarget;
  try {
    await navigator.clipboard.writeText($("update-cmd").textContent);
    btn.textContent = "복사됨";
  } catch {
    btn.textContent = "직접 선택해 복사하세요";
  }
  setTimeout(() => { btn.textContent = "복사"; }, 1800);
});

stopBtn.addEventListener("click", async () => {
  if (!jobId) return;
  stopBtn.disabled = true;
  try { await api(`/api/jobs/${jobId}/cancel`, {}); } catch (err) { setStatus(err.message, "fail"); }
});
