# 유튜브 다운로더 웹판 — 기능 명세

## 1. 출처

- 기존 데스크톱 다운로더 프로그램 하나를 실행하지 않고 정적 분석해 기능 명세를 만들었습니다. 이 앱은 그 명세를 기준으로 새로 작성했습니다.
- 분석 중 추출한 자료는 제3자 코드이므로 저장소에 올리지 않습니다.

## 2. 기능

- 입력: YouTube 링크 1개
- 형식 5가지

| 모드 | format | 출력 파일명 | 후처리 |
|---|---|---|---|
| best (원본 화질) | `bv*+ba/b` | `제목 (원본 2160p).mp4` | mp4로 합치되 담을 수 없는 코덱이면 mkv |
| 1080 | `bv*[height<=1080]+ba/b[height<=1080]/best` | `제목 (1080p).mp4` | mp4로 병합 |
| 720 | `bv*[height<=720]+ba/b[height<=720]/best` | `제목 (720p).mp4` | mp4로 병합 |
| 480 | `bv*[height<=480]+ba/b[height<=480]/wv*+ba/w` | `제목 (480p).mp4` | mp4로 병합 |
| mp3 | `ba/b` | `제목.mp3` | FFmpegExtractAudio mp3 192kbps |

- 공통 옵션: `noplaylist`, `windowsfilenames`, `ffmpeg_location`, `progress_hooks`
- 중지: 사용자가 중지하면 progress hook이 다운로드를 중단하고 작업 폴더를 지움
- 진행 표시: 진행률 막대와 진행 로그. 경고는 `[경고] `, 에러는 `[에러] ` 접두어
- 결과: 성공, 중지, 실패 세 가지로 나눠 표시

## 3. 구조

브라우저는 사용자 PC의 폴더에 직접 쓸 수 없습니다. 그래서 서버가 받은 파일을 **브라우저 다운로드로 내려주는 방식**을 씁니다.

- 서버: Python 표준 라이브러리 `ThreadingHTTPServer` + yt-dlp + ffmpeg. `127.0.0.1`에만 바인딩
- API

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/info` | yt-dlp 버전, 업데이트 필요 여부, ffmpeg·JS 런타임 상태 |
| POST | `/api/jobs` | `{url, mode: "best"\|"1080"\|"720"\|"480"\|"mp3"}` → `{id}` |
| GET | `/api/jobs/{id}?since=n` | 상태, 진행률, n번째 이후 로그 |
| POST | `/api/jobs/{id}/cancel` | 중지 요청 |
| GET | `/api/jobs/{id}/file` | 완료된 파일 다운로드 (UTF-8 파일명) |
| GET | `/api/jobs/{id}/log` | 실패 로그 다운로드 |

## 4. 안전 장치

- 인증서 검증을 끄지 않음 (`nocheckcertificate` 미사용)
- 오류를 삼키지 않음 (`ignoreerrors` 미사용): 실패를 성공처럼 처리하지 않고 정확한 오류를 보여줌
- 주소는 YouTube 도메인(`youtube.com`, `youtu.be`, `music.youtube.com`)만 허용
- Host 헤더 검사로 DNS rebinding 차단, POST는 JSON 요청만 허용
- 동시에 실행되는 작업은 최대 2개
- Node.js가 있으면 yt-dlp의 JS 런타임으로 사용 (`js_runtimes`), `yt-dlp-ejs` 포함

## 5. 실패 분석과 로그 (`diagnose.py`)

- 오류 메시지와 경고 로그를 규칙표로 분류: 비공개, 연령 제한, 봇 확인, 지역 제한, 저작권, 삭제, 라이브, 화질 없음, ffmpeg 없음, 변환 실패, 429, 403, 추출기 오류, 네트워크, 디스크 부족, 파일 잠김, yt-dlp 노후
- 설치된 yt-dlp와 실행 중인 yt-dlp 버전이 다르면 "서버 재시작 필요"로 진단
- 실패마다 `logs/<YYYYMMDD-HHMMSS>_<작업ID>.log` (진단, 환경, 진행 로그, Traceback)를 쓰고 `logs/failures.jsonl`에 한 줄 추가
- 화면에 원인과 해결 방법을 보여주고, 로그 파일을 내려받을 수 있음
- 사용자 중지는 실패로 기록하지 않음

## 6. 화면

- 디자인은 NexaCore 템플릿(hirael.com)을 참고해 어두운 남색 배경과 그라데이션 강조로 만들었습니다.
- 하단 표기는 `제작: yangphago`이며, "교육용 목적에 한함" 주의사항과 화질 선택 주의사항, yt-dlp 업데이트 안내를 화면에 표시합니다.

## 7. 사용 범위

본인이 만든 영상, 허락받은 영상, CC 라이선스 영상 등 정당한 권한이 있는 콘텐츠에만 사용해야 합니다. YouTube 약관상 공개 서버로 배포하는 것은 권장하지 않으며, 로컬 전용으로 설계했습니다.
