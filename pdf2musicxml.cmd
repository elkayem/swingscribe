@echo off
rem Launcher for pdf2musicxml, the PDF-transcription-to-MusicXML tool that
rem lives in src/pdf2musicxml. Same three routes as swingscribe.cmd, for the
rem same reason: Smart App Control refuses uv's generated console-script
rem stubs and, some days, the venv's python.exe trampoline, so a .cmd hands
rem the arguments to an interpreter that is already trusted.
rem
rem Usage from the repo root:
rem   .\pdf2musicxml setup                          (once: fetches Audiveris)
rem   .\pdf2musicxml convert benchmark\Transcriptions_Other
rem   .\pdf2musicxml doctor
setlocal
set "ROOT=%~dp0"
set "VENV_PY=%ROOT%.venv\Scripts\python.exe"
if not exist "%VENV_PY%" goto :uv

"%VENV_PY%" -c "pass" >nul 2>&1
if not errorlevel 1 (
    "%VENV_PY%" -m pdf2musicxml %*
    exit /b %ERRORLEVEL%
)

set "BASE_HOME="
for /f "usebackq tokens=1,* delims== " %%A in ("%ROOT%.venv\pyvenv.cfg") do (
    if /i "%%A"=="home" set "BASE_HOME=%%B"
)
if "%BASE_HOME%"=="" goto :uv
set "BASE_PY=%BASE_HOME%\python.exe"
if not exist "%BASE_PY%" goto :uv
set "PYTHONPATH=%ROOT%.venv\Lib\site-packages;%ROOT%src"
"%BASE_PY%" -m pdf2musicxml %*
exit /b %ERRORLEVEL%

:uv
uv run python -m pdf2musicxml %*
exit /b %ERRORLEVEL%
