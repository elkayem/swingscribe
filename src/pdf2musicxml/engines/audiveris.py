"""Audiveris 5.11 as a subprocess.

The Windows release is an MSI built with jpackage: a launcher exe, the
jars under app/, and a Java runtime under runtime/. The launcher is a
freshly built unsigned binary that Smart App Control refuses, so it is
never run; the bundled `runtime\\bin\\java.exe` (Azul's, signed) is, with
the jars on the classpath -- `audiveris.jar` FIRST, because Audiveris
locates its `res/` folder from the first classpath entry and otherwise
looks for it under the working directory. `msiexec /a` unpacks the MSI
into a folder without installing anything; no admin rights, no registry.

Audiveris keeps its config (the Tesseract language files) under %APPDATA%.
The tool points APPDATA at its own folder for the run, so that state lives
beside the engine and not in a packaged shell's redirected AppData.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

from pdf2musicxml import paths
from pdf2musicxml.engines import EngineError

MSI_URL = (
    "https://github.com/Audiveris/audiveris/releases/download/"
    f"{paths.AUDIVERIS_VERSION}/Audiveris-{paths.AUDIVERIS_VERSION}-windowsConsole-x86_64.msi"
)
MSI_SHA256 = "5f1b4e96a12c53c7da426814b76e599363c4181e291855996e0a6878dda95f71"
TESSDATA_URL = "https://github.com/tesseract-ocr/tessdata/raw/main/eng.traineddata"

# Audiveris' music-font families (org.audiveris.omr.ui.symbol.MusicFamily).
# Its glyph classifier is trained per family; a handwritten-style page reads
# better with FinaleJazz, an engraved one with Bravura.
MUSIC_FAMILY = {"standard": "Bravura", "jazz": "FinaleJazz"}
TEXT_FAMILY = {"standard": "SansSerif", "jazz": "FinaleJazzText"}

JVM_OPTIONS = (
    "--add-exports=java.desktop/sun.awt.image=ALL-UNNAMED",
    "--enable-native-access=ALL-UNNAMED",
    "-Dfile.encoding=UTF-8",
)


def java_exe() -> Path:
    return paths.audiveris_dir() / "runtime" / "bin" / "java.exe"


def jar() -> Path:
    return paths.audiveris_dir() / "app" / "audiveris.jar"


def is_installed() -> bool:
    return java_exe().is_file() and jar().is_file()


def ocr_installed() -> bool:
    return (paths.tessdata_dir() / "eng.traineddata").is_file()


def command(pdf: Path, out_dir: Path, *, font: str = "standard", xmx: str = "4G") -> list[str]:
    """The exact command line, so a test can hold it."""
    app = paths.audiveris_dir() / "app"
    classpath = f"{app / 'audiveris.jar'}{os.pathsep}{app / '*'}"
    cmd = [str(java_exe()), "-cp", classpath, *JVM_OPTIONS, f"-Xmx{xmx}", "Audiveris"]
    cmd += ["-batch", "-export"]
    cmd += ["-constant", "org.audiveris.omr.sheet.BookManager.useCompression=false"]
    if font != "standard":
        cmd += [
            "-constant",
            f"org.audiveris.omr.ui.symbol.MusicFont.defaultMusicFamily={MUSIC_FAMILY[font]}",
            "-constant",
            f"org.audiveris.omr.ui.symbol.TextFont.defaultTextFamily={TEXT_FAMILY[font]}",
        ]
    cmd += ["-output", str(out_dir), "--", str(pdf)]
    return cmd


def exported(out_dir: Path, stem: str) -> list[Path]:
    """The files Audiveris wrote for a book: `<stem>.xml`, or `<stem>.mvt<N>.xml` per movement."""
    pattern = re.compile(re.escape(stem) + r"(?:\.mvt(\d+))?\.xml$")
    found = []
    for path in out_dir.iterdir():
        match = pattern.fullmatch(path.name)
        if match:
            found.append((int(match.group(1) or 0), path))
    return [path for _, path in sorted(found)]


def warnings(log_path: Path) -> list[str]:
    if not log_path.is_file():
        return []
    lines = []
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if ("WARN" in line or "ERROR" in line) and "Caller+0" not in line:
            lines.append(line.strip())
    return lines


def run(
    pdf: Path, out_dir: Path, *, font: str = "standard", timeout: int = 3600, reuse: bool = True
) -> list[Path]:
    """Transcribe one book (a PDF of staff pages only) and return its MusicXML files.

    Audiveris refuses to export a book in which any sheet failed, and a
    page with no staves fails ("No regularly spaced lines found"), so the
    caller gives it staff pages only. A page it renders above 20 megapixels
    is refused too, which is why the caller rasterises the pages itself.
    """
    if not is_installed():
        raise EngineError("Audiveris is not installed; run `pdf2musicxml setup`")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    already = exported(out_dir, Path(pdf).stem)
    if reuse and already and all(f.stat().st_mtime >= Path(pdf).stat().st_mtime for f in already):
        return already
    for stale in already:
        stale.unlink()
    env = dict(os.environ, APPDATA=str(paths.audiveris_appdata()))
    paths.audiveris_appdata().mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "audiveris.log"
    with open(log_path, "w", encoding="utf-8") as log:
        process = subprocess.run(
            command(Path(pdf), out_dir, font=font),
            stdout=log,
            stderr=subprocess.STDOUT,
            env=env,
            timeout=timeout,
            cwd=str(out_dir),
        )
    files = exported(out_dir, Path(pdf).stem)
    if not files:
        raise EngineError(f"Audiveris exported nothing (exit {process.returncode}); see {log_path}")
    return files


# ---------------------------------------------------------------- install


def _download(url: str, target: Path, log=print) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    log(f"downloading {url}")
    request = urllib.request.Request(url, headers={"User-Agent": "pdf2musicxml"})
    with urllib.request.urlopen(request) as response, open(target, "wb") as handle:
        shutil.copyfileobj(response, handle)
    log(f"  -> {target} ({target.stat().st_size // 1024} KB)")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def install(log=print, force: bool = False) -> None:
    """Fetch the Audiveris MSI and the English OCR data into the tool's folder. Windows only."""
    if is_installed() and not force:
        log(f"Audiveris {paths.AUDIVERIS_VERSION} already at {paths.audiveris_dir()}")
    else:
        if sys.platform != "win32":
            raise EngineError(
                "automatic Audiveris setup is Windows-only; install Audiveris yourself and set "
                "PDF2MUSICXML_HOME so that <home>/audiveris-<version>/Audiveris holds app/ "
                "and runtime/"
            )
        msi = paths.downloads_dir() / MSI_URL.rsplit("/", 1)[1]
        if not msi.is_file():
            _download(MSI_URL, msi, log)
        digest = sha256(msi)
        if MSI_SHA256 != "PLACEHOLDER" and digest != MSI_SHA256:
            raise EngineError(
                f"{msi} has sha256 {digest}, expected {MSI_SHA256}; delete it and retry"
            )
        with tempfile.TemporaryDirectory(dir=paths.tool_home()) as scratch:
            log(f"unpacking {msi.name} (msiexec /a, no installation)")
            result = subprocess.run(
                ["msiexec", "/a", str(msi), "/qn", f"TARGETDIR={scratch}"],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                raise EngineError(
                    f"msiexec /a failed with exit {result.returncode}: {result.stdout}"
                )
            unpacked = Path(scratch) / "Audiveris"
            target = paths.audiveris_dir()
            if target.exists():
                shutil.rmtree(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(unpacked), str(target))
        log(f"  -> {paths.audiveris_dir()}")
    if not ocr_installed():
        _download(TESSDATA_URL, paths.tessdata_dir() / "eng.traineddata", log)
    else:
        log(f"OCR data present at {paths.tessdata_dir()}")
