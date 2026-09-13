<#
.SYNOPSIS
Put a SwingScribe icon on the desktop that launches the GUI (docs/packaging-plan.md, piece 2).

.DESCRIPTION
Creates (or refreshes) a Windows shortcut to the repo's swingscribe.cmd
launcher with the `gui` argument, and draws assets/swingscribe.ico first if
it is missing. Re-run it after moving the repo.

Three choices in the shortcut are deliberate:

- Start-in is the repo root. `cache_dir` (.swingscribe-cache) and the file
  picker's first folder are both relative to the working directory, so any
  other folder would start from an empty cache.
- The window is MINIMIZED, not hidden. On this machine a process with no
  console window HANGS when Application Control refuses a DLL instead of
  raising the error the transcribe shim catches (CLAUDE.md, 2026-09-08). A
  minimized console is out of the way and still a window; the Quit button
  in the page closes it.
- The target is the .cmd, never a python.exe. The .cmd is what survives a
  Smart App Control reputation flap (it falls back to the base interpreter
  when the venv's launcher is refused).

.PARAMETER Where
Directory to put the shortcut in. Default: the desktop.
#>
param(
    [string]$Where = [Environment]::GetFolderPath("Desktop")
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$launcher = Join-Path $root "swingscribe.cmd"
$icon = Join-Path $root "assets\swingscribe.ico"
if (-not (Test-Path $launcher)) { throw "no launcher at $launcher" }

if (-not (Test-Path $icon)) {
    # The brand mark from the page header: an amber rounded square with a
    # beamed pair of notes. Drawn here with System.Drawing so the icon needs
    # no dependency and no binary in git that cannot be regenerated.
    Add-Type -AssemblyName System.Drawing
    New-Item -ItemType Directory -Force (Split-Path $icon) | Out-Null
    $sizes = 256, 48, 32, 16
    $pngs = foreach ($size in $sizes) {
        $bmp = New-Object System.Drawing.Bitmap $size, $size
        $g = [System.Drawing.Graphics]::FromImage($bmp)
        $g.SmoothingMode = "AntiAlias"
        $g.Clear([System.Drawing.Color]::Transparent)
        $r = $size * 0.22
        $path = New-Object System.Drawing.Drawing2D.GraphicsPath
        $d = $r * 2
        $w = $size - 1
        $path.AddArc(0, 0, $d, $d, 180, 90)
        $path.AddArc($w - $d, 0, $d, $d, 270, 90)
        $path.AddArc($w - $d, $w - $d, $d, $d, 0, 90)
        $path.AddArc(0, $w - $d, $d, $d, 90, 90)
        $path.CloseFigure()
        $brush = New-Object System.Drawing.Drawing2D.LinearGradientBrush(
            (New-Object System.Drawing.Point 0, 0), (New-Object System.Drawing.Point $size, $size),
            [System.Drawing.Color]::FromArgb(255, 255, 196, 96), [System.Drawing.Color]::FromArgb(255, 217, 138, 42))
        $g.FillPath($brush, $path)
        $ink = [System.Drawing.Color]::FromArgb(255, 27, 19, 5)
        $pen = New-Object System.Drawing.Pen $ink, ([Math]::Max(1, $size * 0.1))
        $pen.StartCap = "Round"; $pen.EndCap = "Round"; $pen.LineJoin = "Round"
        $s = $size / 16.0
        # Stems and beam: (5.5,12.2)->(5.5,3.6)->(12.5,2.0)->(12.5,10.4)
        $g.DrawLines($pen, [System.Drawing.PointF[]]@(
            (New-Object System.Drawing.PointF (5.5 * $s), (12.2 * $s)),
            (New-Object System.Drawing.PointF (5.5 * $s), (3.6 * $s)),
            (New-Object System.Drawing.PointF (12.5 * $s), (2.0 * $s)),
            (New-Object System.Drawing.PointF (12.5 * $s), (10.4 * $s))))
        $head = New-Object System.Drawing.SolidBrush $ink
        $rad = 1.9 * $s
        $g.FillEllipse($head, (3.9 * $s - $rad), (12.3 * $s - $rad), 2 * $rad, 2 * $rad)
        $g.FillEllipse($head, (10.9 * $s - $rad), (10.6 * $s - $rad), 2 * $rad, 2 * $rad)
        $g.Dispose()
        $stream = New-Object System.IO.MemoryStream
        $bmp.Save($stream, [System.Drawing.Imaging.ImageFormat]::Png)
        $bmp.Dispose()
        , $stream.ToArray()
    }
    # An .ico is a header, one directory entry per image, then the PNG bytes
    # (PNG-compressed entries are valid from Vista on).
    $out = New-Object System.IO.MemoryStream
    $bw = New-Object System.IO.BinaryWriter $out
    $bw.Write([UInt16]0); $bw.Write([UInt16]1); $bw.Write([UInt16]$sizes.Count)
    $offset = 6 + 16 * $sizes.Count
    for ($i = 0; $i -lt $sizes.Count; $i++) {
        $dim = if ($sizes[$i] -ge 256) { 0 } else { $sizes[$i] }
        $bw.Write([Byte]$dim); $bw.Write([Byte]$dim); $bw.Write([Byte]0); $bw.Write([Byte]0)
        $bw.Write([UInt16]1); $bw.Write([UInt16]32)
        $bw.Write([UInt32]$pngs[$i].Length); $bw.Write([UInt32]$offset)
        $offset += $pngs[$i].Length
    }
    foreach ($png in $pngs) { $bw.Write($png) }
    $bw.Flush()
    [System.IO.File]::WriteAllBytes($icon, $out.ToArray())
    Write-Host "drew $icon"
}

$link = Join-Path $Where "SwingScribe.lnk"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($link)
$shortcut.TargetPath = $launcher
$shortcut.Arguments = "gui"
$shortcut.WorkingDirectory = $root
$shortcut.IconLocation = "$icon,0"
$shortcut.WindowStyle = 7   # minimized -- see above; never 0 (hidden)
$shortcut.Description = "Launch the SwingScribe GUI (quit from the button in the page)"
$shortcut.Save()
Write-Host "shortcut: $link -> $launcher gui (start in $root)"
