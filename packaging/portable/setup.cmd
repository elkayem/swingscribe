@echo off
rem Run once after extracting: a SwingScribe icon on the desktop and in the
rem Start Menu, and an entry in Settings > Apps so it can be uninstalled from
rem there. Per-user; no administrator prompt. Re-run it after moving the
rem folder. Everything it does, uninstall.cmd undoes.
setlocal
set "ROOT=%~dp0"
set "ROOT=%ROOT:~0,-1%"
set "VERSION=0"
if exist "%ROOT%\VERSION" for /f "usebackq delims=" %%V in ("%ROOT%\VERSION") do set "VERSION=%%V"

echo Setting up SwingScribe %VERSION% from
echo   %ROOT%
echo.

rem The shortcuts. Minimized: the console window that stays behind the
rem browser tab is where a problem would show, and the Quit button in the
rem page closes it.
set "PS=powershell -NoProfile -ExecutionPolicy Bypass -Command"
%PS% "$d=[Environment]::GetFolderPath('Desktop'); $p=[Environment]::GetFolderPath('Programs'); foreach ($dir in @($d, $p)) { $s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $dir 'SwingScribe.lnk')); $s.TargetPath='%ROOT%\SwingScribe.cmd'; $s.WorkingDirectory='%ROOT%'; $s.IconLocation='%ROOT%\swingscribe.ico,0'; $s.WindowStyle=7; $s.Description='SwingScribe: jazz audio to swing-aware notation'; $s.Save() }"
if errorlevel 1 (
    echo Could not create the shortcuts.
    pause
    exit /b 1
)
echo   desktop and Start Menu icons: done

rem The Settings > Apps entry. HKCU, so it is this user's and needs no
rem elevation; EstimatedSize is in KB.
set "KEY=HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\SwingScribe"
reg add "%KEY%" /v DisplayName /t REG_SZ /d "SwingScribe" /f >nul
reg add "%KEY%" /v DisplayVersion /t REG_SZ /d "%VERSION%" /f >nul
reg add "%KEY%" /v Publisher /t REG_SZ /d "SwingScribe project" /f >nul
reg add "%KEY%" /v DisplayIcon /t REG_SZ /d "%ROOT%\swingscribe.ico" /f >nul
reg add "%KEY%" /v InstallLocation /t REG_SZ /d "%ROOT%" /f >nul
reg add "%KEY%" /v UninstallString /t REG_SZ /d "\"%ROOT%\uninstall.cmd\"" /f >nul
reg add "%KEY%" /v NoModify /t REG_DWORD /d 1 /f >nul
reg add "%KEY%" /v NoRepair /t REG_DWORD /d 1 /f >nul
reg add "%KEY%" /v EstimatedSize /t REG_DWORD /d 1600000 /f >nul
if errorlevel 1 (
    echo Could not register the Settings ^> Apps entry ^(the icons still work^).
) else (
    echo   Settings ^> Apps entry: done
)
echo.
echo Done. Double-click the SwingScribe icon on the desktop to start.
echo The first run of each step downloads its model weights ^(about half a
echo gigabyte all told, once^) into %LOCALAPPDATA%\SwingScribe.
echo.
pause
exit /b 0
