@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
if errorlevel 1 exit /b 1
where git >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Git is not installed or not on PATH.
    exit /b 1
)
git rev-parse --show-toplevel >nul 2>&1
if errorlevel 1 (
    echo [ERROR] This directory is not a Git working tree.
    exit /b 1
)
git rev-parse --verify HEAD >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Create a reviewed commit before syncing.
    exit /b 1
)
set "BRANCH="
for /f "delims=" %%B in ('git symbolic-ref --quiet --short HEAD 2^>nul') do set "BRANCH=%%B"
if not defined BRANCH (
    echo [ERROR] Detached HEAD. Switch to a named branch first.
    exit /b 1
)
git status --porcelain --untracked-files=all >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Cannot inspect working tree status.
    exit /b 1
)
set "DIRTY="
for /f "delims=" %%L in ('git status --porcelain --untracked-files^=all 2^>nul') do set "DIRTY=1"
if defined DIRTY (
    echo [ERROR] Uncommitted or untracked changes found. Nothing was pushed.
    echo Review sensitive files, then stage and commit the intended changes yourself.
    git status --short
    exit /b 1
)
set "GITHUB_URL="
set "GITEE_URL="
set "URL_COUNT=0"
for /f "delims=" %%U in ('git remote get-url --push --all github 2^>nul') do (
    set /a URL_COUNT+=1 >nul
    set "GITHUB_URL=%%U"
)
if not "%URL_COUNT%"=="1" (
    echo [ERROR] Remote github must have exactly one push URL.
    exit /b 1
)
set "URL_COUNT=0"
for /f "delims=" %%U in ('git remote get-url --push --all gitee 2^>nul') do (
    set /a URL_COUNT+=1 >nul
    set "GITEE_URL=%%U"
)
if not "%URL_COUNT%"=="1" (
    echo [ERROR] Remote gitee must have exactly one push URL.
    exit /b 1
)
if /i "%GITHUB_URL%"=="%GITEE_URL%" (
    echo [ERROR] GitHub and Gitee must be independent repositories.
    exit /b 1
)
for /f %%H in ('git rev-parse HEAD') do set "LOCAL_HEAD=%%H"
echo Syncing committed branch "%BRANCH%" at %LOCAL_HEAD%
call :push_one github
set "GITHUB_RESULT=%errorlevel%"
call :push_one gitee
set "GITEE_RESULT=%errorlevel%"
echo.
if "%GITHUB_RESULT%"=="0" (echo [GitHub] SUCCESS - remote commit verified.) else (echo [GitHub] FAILED.)
if "%GITEE_RESULT%"=="0" (echo [Gitee] SUCCESS - remote commit verified.) else (echo [Gitee] FAILED.)
if not "%GITHUB_RESULT%"=="0" goto :failed
if not "%GITEE_RESULT%"=="0" goto :failed
echo [SUCCESS] Both repositories contain the committed branch at the verified commit.
exit /b 0

:failed
echo [ERROR] Dual-platform sync is incomplete. Resolve the failed push and rerun.
echo Existing remote commits were not force-overwritten by this script.
exit /b 1

:push_one
echo.
echo [%~1] Pushing branch "%BRANCH%"...
git -c push.followTags=false push --no-force --no-mirror "%~1" "HEAD:refs/heads/%BRANCH%"
if errorlevel 1 (
    echo [%~1] ERROR: Push failed. Check authentication, connection and remote history.
    exit /b 1
)
set "VERIFY_URL="
for /f "delims=" %%U in ('git remote get-url --push "%~1" 2^>nul') do set "VERIFY_URL=%%U"
set "REMOTE_HEAD="
for /f "tokens=1" %%H in ('git ls-remote --exit-code --heads "%VERIFY_URL%" "refs/heads/%BRANCH%" 2^>nul') do set "REMOTE_HEAD=%%H"
if not "%REMOTE_HEAD%"=="%LOCAL_HEAD%" (
    echo [%~1] ERROR: Remote commit could not be verified against local HEAD.
    exit /b 1
)
echo [%~1] Verified %REMOTE_HEAD%.
exit /b 0
