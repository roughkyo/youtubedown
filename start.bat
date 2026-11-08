@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title 유튜브 다운로더 (교육용)

echo.
echo  유튜브 다운로더 (교육용 · 로컬 전용)
echo  ------------------------------------------------

rem 1) Python (the Microsoft Store alias "python" exists but fails, so run it)
python --version >nul 2>nul
if errorlevel 1 (
  echo  [오류] Python을 찾지 못했습니다.
  echo         https://www.python.org/downloads/ 에서 설치하고
  echo         설치 화면의 "Add python.exe to PATH"를 꼭 체크하세요.
  pause
  exit /b 1
)
for /f "delims=" %%v in ('python --version') do echo  [확인] %%v

rem 2) ffmpeg (needed for merging video+audio and MP3 conversion)
where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo  [경고] ffmpeg를 찾지 못했습니다. MP3 변환과 고화질 영상 합치기가 실패합니다.
  echo         설치: 명령 프롬프트에서  winget install Gyan.FFmpeg  실행 후 이 창을 다시 여세요.
) else (
  echo  [확인] ffmpeg
)

rem 3) yt-dlp: install or update on every start so YouTube changes do not break downloads
echo  [진행] yt-dlp 설치/업데이트 확인 중...
python -m pip install --disable-pip-version-check --no-warn-script-location -q -U -r requirements.txt
if errorlevel 1 (
  python -c "import yt_dlp" >nul 2>nul
  if errorlevel 1 (
    echo  [오류] yt-dlp를 설치하지 못했습니다. 인터넷 연결을 확인하세요.
    pause
    exit /b 1
  )
  echo  [경고] 업데이트에 실패해 설치된 yt-dlp로 실행합니다.
)
for /f "delims=" %%v in ('python -c "import yt_dlp;print(yt_dlp.version.__version__)"') do echo  [확인] yt-dlp %%v

if /i "%~1"=="--check" (
  echo  [완료] 준비 상태 확인만 했습니다.
  exit /b 0
)

rem 4) Start the server and open the browser once it has had a moment to listen
echo.
echo  브라우저에서 http://127.0.0.1:8765 이 열립니다. 이 창을 닫으면 서버가 꺼집니다.
echo.
start "" cmd /c "timeout /t 2 >nul & start http://127.0.0.1:8765"
python server.py
pause
