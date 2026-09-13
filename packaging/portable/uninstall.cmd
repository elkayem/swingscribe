@echo off
rem Removes SwingScribe from this computer: the icons, the Settings > Apps
rem entry, optionally the per-user data (cache and downloaded model weights),
rem and finally this folder. It never touches the .swingscribe.json files
rem beside your music: those hold your own spans, downbeats and edits.
rem
rem   uninstall.cmd        asks before each step
rem   uninstall.cmd /y     no questions: uninstall, keep the data folder
rem   uninstall.cmd /y /data   no questions: uninstall AND delete the data folder
setlocal
set "YES="
set "WIPE="
for %%A in (%*) do (
    if /i "%%~A"=="/y" set "YES=1"
    if /i "%%~A"=="/data" set "WIPE=1"
)
set "ROOT=%~dp0"
set "ROOT=%ROOT:~0,-1%"
set "DATA=%LOCALAPPDATA%\SwingScribe"

echo This removes SwingScribe:
echo   - the desktop and Start Menu icons
echo   - the entry in Settings ^> Apps
echo   - this folder: %ROOT%
echo It leaves the .swingscribe.json files beside your music alone.
echo.
if not defined YES (
    choice /c YN /n /m "Continue? [Y/N] "
    if errorlevel 2 exit /b 1
)

set "PS=powershell -NoProfile -ExecutionPolicy Bypass -Command"
%PS% "foreach ($dir in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) { $l = Join-Path $dir 'SwingScribe.lnk'; if (Test-Path $l) { Remove-Item $l -Force } }"
echo   icons: removed
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\SwingScribe" /f >nul 2>&1
echo   Settings ^> Apps entry: removed

if exist "%DATA%" (
    if not defined YES (
        echo.
        echo %DATA% holds the cache and the downloaded model weights ^(about 2 GB^).
        echo Deleting it means the next install downloads the weights again.
        choice /c YN /n /m "Delete it too? [Y/N] "
        if not errorlevel 2 set "WIPE=1"
    )
    if defined WIPE (
        rd /s /q "%DATA%"
        echo   data folder: removed
    ) else (
        echo   data folder: kept
    )
)

echo.
echo Removing %ROOT% ...
rem A script cannot delete the folder it is running from, so the last step is
rem handed to a detached command that waits for this window to close.
cd /d "%TEMP%"
start "" /b cmd /c "timeout /t 2 /nobreak >nul & rd /s /q "%ROOT%""
echo Done. SwingScribe is uninstalled.
timeout /t 3 >nul
exit /b 0
