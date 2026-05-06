@echo off
REM ArchHub one-click self-hosted Speckle setup.
REM
REM Double-click this file. It will:
REM   1. Make sure Docker Desktop is installed (offers to install if not).
REM   2. Make sure Docker Desktop is running.
REM   3. Clone the official speckle-server repo into ./speckle/ if missing.
REM   4. Run `docker compose up -d` to start Postgres + Redis + Speckle services.
REM   5. Wait for the Speckle frontend to respond on http://localhost:3000.
REM   6. Print the URL + a one-line "point ArchHub here" instruction.
REM
REM Total time, first run: ~10 minutes (most of it is Docker pulling images).
REM Subsequent runs: ~30 seconds.

setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================
echo   ArchHub Speckle setup
echo ============================================
echo Repo:       %~dp0
echo Subfolder:  %~dp0speckle\
echo URL after:  http://localhost:3000
echo.

REM ── 1. Docker installed? ────────────────────────────────────────────────
where docker >nul 2>&1
if errorlevel 1 (
    echo [1/5] Docker Desktop is NOT installed.
    echo.
    echo ArchHub needs Docker Desktop to run a local Speckle server.
    echo It is a one-time install ^(roughly 600 MB^) and may require a reboot.
    echo.
    set /p CONFIRM="Install Docker Desktop now via winget? [Y/n] "
    if /i "!CONFIRM!"=="n" (
        echo Aborted. You can install Docker Desktop manually from
        echo   https://www.docker.com/products/docker-desktop/
        echo and then run this script again.
        pause
        exit /b 1
    )
    echo Installing Docker Desktop. UAC will ask for permission...
    winget install --id Docker.DockerDesktop -e --source winget ^
        --accept-source-agreements --accept-package-agreements
    if errorlevel 1 (
        echo Docker install failed. Open the Microsoft Store or
        echo https://www.docker.com/products/docker-desktop/ and install manually.
        pause
        exit /b 1
    )
    echo.
    echo Docker installed. You may need to reboot Windows once for it to work,
    echo then double-click this script again.
    pause
    exit /b 0
) else (
    echo [1/5] Docker is on PATH:
    docker --version
)

echo.

REM ── 2. Docker daemon running? ───────────────────────────────────────────
echo [2/5] Checking the Docker daemon...
docker info >nul 2>&1
if errorlevel 1 (
    echo Docker is installed but the daemon is not running.
    echo Starting Docker Desktop...
    start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    echo Waiting up to 90 seconds for the daemon to come up...
    set /a tries=0
    :waitdocker
    timeout /t 5 /nobreak >nul
    docker info >nul 2>&1
    if errorlevel 1 (
        set /a tries+=1
        if !tries! lss 18 goto waitdocker
        echo Docker Desktop did not start in time. Open it manually,
        echo wait until it says "Docker Desktop is running", and re-run this script.
        pause
        exit /b 1
    )
)
echo Docker daemon is up.
echo.

REM ── 3. Clone speckle-server if missing ──────────────────────────────────
echo [3/5] Checking the local speckle-server checkout...
if not exist "speckle\.git" (
    if exist "speckle" (
        echo The folder %~dp0speckle exists but is not a git checkout.
        echo Move or delete it, then re-run this script.
        pause
        exit /b 1
    )
    echo Cloning github.com/specklesystems/speckle-server into ./speckle/ ...
    git clone --depth 1 https://github.com/specklesystems/speckle-server.git speckle
    if errorlevel 1 (
        echo Clone failed. Check your network and try again.
        pause
        exit /b 1
    )
) else (
    echo Found existing checkout.  Pulling latest...
    pushd speckle
    git pull --ff-only
    popd
)
echo.

REM ── 4. Bring up the stack ───────────────────────────────────────────────
echo [4/5] Starting Speckle services with docker compose...
echo This will pull a few GB of images on the first run.
pushd speckle
if exist "docker-compose-deps.yml" (
    docker compose -f docker-compose-deps.yml up -d
) else (
    docker compose up -d
)
if errorlevel 1 (
    popd
    echo docker compose failed. Run "docker compose ps" and "docker compose logs"
    echo from %~dp0speckle to see what went wrong.
    pause
    exit /b 1
)
popd
echo.

REM ── 5. Wait for the frontend ────────────────────────────────────────────
echo [5/5] Waiting for the Speckle frontend on http://localhost:3000 ...
set /a tries=0
:waithttp
powershell -NoProfile -Command "try { (Invoke-WebRequest -Uri 'http://localhost:3000' -UseBasicParsing -TimeoutSec 3).StatusCode } catch { exit 1 }" >nul 2>&1
if errorlevel 1 (
    set /a tries+=1
    if !tries! lss 60 (
        timeout /t 5 /nobreak >nul
        goto waithttp
    )
    echo Speckle did not respond in time. It may still be initialising the
    echo database — give it another minute and try http://localhost:3000
    echo in your browser. View logs with:
    echo     docker compose -f speckle\docker-compose-deps.yml logs -f
    pause
    exit /b 1
)
echo Speckle is responding on http://localhost:3000.
echo.

echo ============================================
echo   Done.
echo ============================================
echo   1. Open http://localhost:3000 in your browser.
echo   2. Create your local Speckle account ^(first user becomes admin^).
echo   3. In ArchHub: Settings -^> Speckle -^> Self-hosted, URL =
echo        http://localhost:3000
echo   4. Generate a Personal Access Token from your profile and paste
echo      it into the Speckle PAT field in Settings.
echo.
pause
exit /b 0
