# 유튜브 다운로더 (교육용 · 로컬 전용)

수업 자료 준비를 위해 **내 PC에서만** 실행하는 유튜브 다운로더 웹앱입니다.
링크를 붙여넣고 형식을 고르면, 완료된 파일을 브라우저 다운로드로 받습니다.

**설치 안내 페이지: <https://roughkyo.github.io/youtubedown/>**

> ⚠ **교육용 목적에 한해 사용하세요.**
> 본인이 만든 영상, 허락받은 영상, CC 라이선스 영상처럼 이용 권한이 있는 콘텐츠만 받고,
> 재배포·재업로드·상업적 이용은 하지 마세요. YouTube 이용약관은 허가 없는 다운로드를 제한하며,
> 이 앱은 공개 서버 배포용으로 만들지 않았습니다.

## 기능

- 형식 5가지: 원본 화질 / 1080p / 720p / 480p / MP3(192kbps)
- 진행률·진행 로그 표시, 작업 중지
- 실패 원인 자동 진단(비공개·연령 제한·지역 제한·삭제·403·429·네트워크 등)과 실패 로그 기록
  - `logs/<시각>_<작업ID>.log`, `logs/failures.jsonl`
- 설치된 yt-dlp 버전 확인과 업데이트 안내

## 내려받기 (Windows, 권장)

**[YTDownloader.exe 내려받기](https://github.com/roughkyo/youtubedown/releases/latest/download/YTDownloader.exe)** — Python·ffmpeg가 모두 들어 있어 설치 없이 더블클릭으로 실행됩니다.

- 실행하면 검은 창이 뜨고 브라우저에서 <http://127.0.0.1:8765> 이 열립니다. 창을 닫으면 꺼집니다.
- "Windows의 PC 보호" 창이 뜨면 **추가 정보 → 실행**을 누르세요(서명되지 않은 무료 프로그램).
- 실패 로그는 exe 옆 `logs` 폴더에 저장됩니다.
- exe에는 만들 당시의 yt-dlp가 들어 있습니다. [GitHub Actions](.github/workflows/release.yml)가 **매주 월요일** 최신 yt-dlp로 새 exe를 만들어 [Releases](https://github.com/roughkyo/youtubedown/releases)에 올립니다(yt-dlp나 코드가 바뀐 경우에만). 화면에 업데이트 안내가 뜨거나 다운로드가 자꾸 실패하면 새 exe로 바꾸세요.

## 소스로 실행 (macOS·Linux·개발용)

준비물:

- Python 3.10 이상
- [ffmpeg](https://ffmpeg.org/) (PATH에 등록) — 영상·음성 합치기와 MP3 변환에 필요
- Node.js (선택) — 있으면 yt-dlp가 YouTube의 JavaScript 확인을 처리하는 데 사용

**Windows:** `start.bat`을 더블클릭하세요. Python·ffmpeg를 확인하고, yt-dlp를 설치·업데이트한 뒤 서버를 켜고 브라우저를 엽니다.

직접 실행하려면:

```bash
pip install -r requirements.txt
python server.py
```

브라우저에서 <http://127.0.0.1:8765> 를 엽니다. 서버는 `127.0.0.1`에만 열리므로 다른 기기에서는 접속할 수 없습니다.

## yt-dlp 업데이트

YouTube가 바뀌면 오래된 yt-dlp로는 다운로드가 실패하기 쉽습니다. 서버를 끄고 아래 명령을 실행한 뒤 다시 켜세요.

```bash
python -m pip install -U yt-dlp
```

## 테스트

```bash
python test_server.py          # 네트워크 없이 실행되는 테스트
python test_server.py --live   # 실제 YouTube 다운로드까지 포함
```

## exe 직접 만들기

```bash
pip install -r requirements.txt pyinstaller
python build_exe.py --ffmpeg C:\path\to\ffmpeg.exe   # dist/YTDownloader.exe
dist\YTDownloader.exe --check                          # 구성 확인
```

배포용 exe는 [release.yml](.github/workflows/release.yml)이 LGPL ffmpeg로 만듭니다. 포함된 소프트웨어의 라이선스는 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)를 참고하세요.

## 구조

| 파일 | 역할 |
|---|---|
| `server.py` | HTTP 서버, 작업 관리, yt-dlp 실행 (`--check`, `--no-browser`) |
| `diagnose.py` | 실패 원인 분류, 실패 로그 기록 |
| `paths.py` | 소스/exe 실행 시 파일 위치 (리소스, 로그, 작업 폴더, ffmpeg) |
| `build_exe.py` | PyInstaller로 `YTDownloader.exe` 빌드 |
| `.github/workflows/release.yml` | 매주 exe 빌드 → Releases 게시 |
| `public/` | 웹 화면 (HTML/CSS/JS) |
| `test_server.py` | 단위·API·실제 다운로드 테스트 |
| `start.bat` | Windows 원클릭 실행 (준비 확인 + yt-dlp 업데이트 + 서버 실행) |
| `docs/` | GitHub Pages 설치 안내 페이지 |
| `SPEC.md` | 기능 명세 |

제작: yangphago
