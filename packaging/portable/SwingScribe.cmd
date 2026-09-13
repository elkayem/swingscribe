@echo off
rem SwingScribe launcher (the desktop icon points here). Double-click it, or
rem give it a track:  SwingScribe.cmd "C:\Music\Oleo.m4a"
rem
rem Everything runs from this folder's own Python, in isolated mode (-I): a
rem Python already installed on this computer, and whatever libraries it has,
rem is neither seen nor touched. Nothing is written outside this folder and
rem %LOCALAPPDATA%\SwingScribe except the small .swingscribe.json file
rem SwingScribe keeps beside each audio file you open, which holds your span,
rem downbeat and edits.
setlocal
set "ROOT=%~dp0"
set "DATA=%LOCALAPPDATA%\SwingScribe"
if not exist "%DATA%\models" mkdir "%DATA%\models"
if not exist "%DATA%\cache" mkdir "%DATA%\cache"

rem Model weights download on first use into one per-user folder: demucs and
rem beat_this through torch hub, the Roformer through audio-separator, the
rem piano model through SwingScribe itself.
set "TORCH_HOME=%DATA%\models\torch"
set "AUDIO_SEPARATOR_MODEL_DIR=%DATA%\models\audio-separator"
set "SWINGSCRIBE_MODELS_DIR=%DATA%\models"
rem Separated stems and other derived data. Safe to delete; the app's cache
rem panel does so too.
set "SWINGSCRIBE_CACHE_DIR=%DATA%\cache"
rem Where the track picker starts. Set it in swingscribe.yaml (gui.library_dir)
rem to make it permanent.
if not defined SWINGSCRIBE_GUI__LIBRARY_DIR set "SWINGSCRIBE_GUI__LIBRARY_DIR=%USERPROFILE%\Music"
rem ffmpeg, for anything that is not wav or flac. PATH changes here die with
rem this window.
set "PATH=%ROOT%ffmpeg;%PATH%"

"%ROOT%python\python.exe" -I -X utf8 -m swingscribe gui --config "%ROOT%swingscribe.yaml" %*
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" (
    echo.
    echo SwingScribe stopped with an error ^(code %RESULT%^). See README.txt, "If something goes wrong".
    pause
)
exit /b %RESULT%
