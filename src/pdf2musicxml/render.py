"""Prove a MusicXML file opens in MuseScore by having MuseScore open it.

MuseScore's command line converts a score to another format without the
GUI (`MuseScore4.exe -o out.pdf in.musicxml`). A file it cannot read
gives no output and a non-zero exit, which is the only test of "readable
by MuseScore" that is not an opinion. The PDFs it writes land under
`musicxml/.render/`, one per transcription, and double as a proof sheet
to lay beside the original page.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

CANDIDATES = (
    r"C:\Program Files\MuseScore 4\bin\MuseScore4.exe",
    r"C:\Program Files\MuseScore 4\bin\MuseScore4.exe".replace(
        "Program Files", "Program Files (x86)"
    ),
    "/Applications/MuseScore 4.app/Contents/MacOS/mscore",
    "/usr/bin/mscore",
    "/usr/bin/musescore4",
)


def find_musescore() -> Path | None:
    override = os.environ.get("PDF2MUSICXML_MUSESCORE")
    for candidate in ([override] if override else []) + list(CANDIDATES):
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    return None


def command(musescore: Path, source: Path, target: Path) -> list[str]:
    return [str(musescore), "-o", str(target), str(source)]


@dataclass
class RenderReport:
    rendered: list[Path] = field(default_factory=list)
    failed: list[tuple[Path, str]] = field(default_factory=list)


def render_folder(
    folder: Path, *, limit: int | None = None, timeout: int = 300, log=print
) -> RenderReport:
    """Render every primary .musicxml in `folder` (the check readings are skipped) to PDF."""
    musescore = find_musescore()
    report = RenderReport()
    if musescore is None:
        raise RuntimeError("MuseScore not found; set PDF2MUSICXML_MUSESCORE to MuseScore4.exe")
    out = Path(folder) / ".render"
    out.mkdir(parents=True, exist_ok=True)
    files = sorted(
        p
        for p in Path(folder).glob("*.musicxml")
        if not p.name.endswith((".audiveris.musicxml", ".homr.musicxml"))
    )
    if limit:
        files = files[:limit]
    # A proof sheet whose transcription was superseded (renamed on a re-run)
    # would otherwise sit beside the live ones forever.
    live = {source.stem for source in files}
    for stale in out.glob("*.pdf"):
        if stale.stem not in live and not limit:
            stale.unlink()
    for index, source in enumerate(files, start=1):
        target = out / (source.stem + ".pdf")
        if target.is_file() and target.stat().st_mtime >= source.stat().st_mtime:
            report.rendered.append(target)
            continue
        try:
            process = subprocess.run(
                command(musescore, source, target),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if process.returncode != 0 or not target.is_file():
                report.failed.append((source, (process.stderr or process.stdout).strip()[-300:]))
                log(f"  [{index}/{len(files)}] FAILED {source.name}")
            else:
                report.rendered.append(target)
        except subprocess.TimeoutExpired:
            report.failed.append((source, f"timed out after {timeout} s"))
            log(f"  [{index}/{len(files)}] TIMEOUT {source.name}")
    return report
