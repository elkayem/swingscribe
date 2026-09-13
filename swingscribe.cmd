@echo off
rem Launcher for machines where Smart App Control blocks the generated console
rem script. `swingscribe.exe` is built fresh by uv/pip at install time, so it is
rem a unique unsigned binary with no reputation and Windows refuses to spawn it
rem (os error 4551). A .cmd is a script, not a PE binary, so no code-integrity
rem policy applies to it -- it just hands the arguments to an interpreter that
rem is already trusted.
rem
rem Usage from the repo root:  .\swingscribe gui
rem
rem Three routes, tried in order:
rem   1. the venv's python.exe -- uv's 262 KB trampoline, which Smart App
rem      Control ALSO refused on 2026-09-12 (it had run that morning;
rem      reputation is per file and flaps). Probed with a no-op first, so a
rem      refusal is told apart from swingscribe itself exiting non-zero --
rem      re-running on any failure would launch the GUI twice;
rem   2. the base interpreter the venv was made from (`home =` in
rem      .venv\pyvenv.cfg) with PYTHONPATH naming the venv's site-packages
rem      and src/ -- PYTHONPATH does not process the editable install's
rem      .pth, so src must be named;
rem   3. whatever `uv` resolves, for a checkout where `uv sync` has not run.
setlocal
set "ROOT=%~dp0"
set "VENV_PY=%ROOT%.venv\Scripts\python.exe"
if not exist "%VENV_PY%" goto :uv

"%VENV_PY%" -c "pass" >nul 2>&1
if not errorlevel 1 (
    "%VENV_PY%" -m swingscribe %*
    exit /b %ERRORLEVEL%
)

rem The venv launcher is refused: find the interpreter it wraps.
set "BASE_HOME="
for /f "usebackq tokens=1,* delims== " %%A in ("%ROOT%.venv\pyvenv.cfg") do (
    if /i "%%A"=="home" set "BASE_HOME=%%B"
)
if "%BASE_HOME%"=="" goto :uv
set "BASE_PY=%BASE_HOME%\python.exe"
if not exist "%BASE_PY%" goto :uv
set "PYTHONPATH=%ROOT%.venv\Lib\site-packages;%ROOT%src"
"%BASE_PY%" -m swingscribe %*
exit /b %ERRORLEVEL%

:uv
uv run python -m swingscribe %*
exit /b %ERRORLEVEL%
