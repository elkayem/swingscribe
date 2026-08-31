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
rem Prefers the project venv and falls back to whatever `uv` resolves, so this
rem still works before `uv sync` has built .venv.
setlocal
set "VENV_PY=%~dp0.venv\Scripts\python.exe"
if exist "%VENV_PY%" (
    "%VENV_PY%" -m swingscribe %*
) else (
    uv run python -m swingscribe %*
)
exit /b %ERRORLEVEL%
