"""homr (github.com/liebharc/homr) as a subprocess, one page image at a time.

homr is a pip package: a UNet segmentation model finds the staves and a
transformer reads each one, all through onnxruntime. Its models download
from GitHub on first use into the package's own folder, so a fresh
`uv sync` that reinstalls the package fetches them again (about 100 MB).
Each page runs in a child process with the same interpreter, so a crash
inside the engine loses one page and not the batch, and so the models'
download sees the machine's CA bundle (this machine intercepts TLS;
`requests` trusts only certifi unless REQUESTS_CA_BUNDLE says otherwise).
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

from pdf2musicxml.engines import EngineError

CA_BUNDLE = Path.home() / ".windows-ca-bundle.pem"

RUNNER = "import sys; from homr.main import main; sys.argv = ['homr', sys.argv[1]]; main()"


def is_installed() -> bool:
    return importlib.util.find_spec("homr") is not None


def environment() -> dict[str, str]:
    env = dict(os.environ)
    if CA_BUNDLE.is_file():
        for name in ("REQUESTS_CA_BUNDLE", "SSL_CERT_FILE", "CURL_CA_BUNDLE"):
            env.setdefault(name, str(CA_BUNDLE))
    env.setdefault("PYTHONIOENCODING", "utf-8")
    # The child runs in its own working directory, so a relative PYTHONPATH
    # (the .cmd launcher's ".venv\Lib\site-packages;src") must be made
    # absolute here or the child finds neither homr nor this package.
    if env.get("PYTHONPATH"):
        entries = [p for p in env["PYTHONPATH"].split(os.pathsep) if p]
        env["PYTHONPATH"] = os.pathsep.join(os.path.abspath(p) for p in entries)
    return env


def command(image: Path) -> list[str]:
    return [sys.executable, "-c", RUNNER, str(image)]


def run(
    images: list[Path], out_dir: Path, *, timeout: int = 1800, reuse: bool = True
) -> list[Path]:
    """One MusicXML per page image, in the images' order. homr writes it beside the image.

    A page already read (its .musicxml beside the image, newer than it) is
    not read again unless `reuse` is off: the reading is the slow part, and
    everything done to it afterwards is cheap enough to redo.
    """
    if not is_installed():
        raise EngineError("homr is not installed; `uv sync --group omr` (see docs/pdf2musicxml.md)")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for image in images:
        image = Path(image)
        target = image.with_suffix(".musicxml")
        if target.exists():
            if reuse and target.stat().st_mtime >= image.stat().st_mtime:
                results.append(target)
                continue
            target.unlink()
        log_path = out_dir / f"{image.stem}.homr.log"
        with open(log_path, "w", encoding="utf-8") as log:
            process = subprocess.run(
                command(image),
                stdout=log,
                stderr=subprocess.STDOUT,
                env=environment(),
                timeout=timeout,
                cwd=str(out_dir),
            )
        if not target.is_file():
            raise EngineError(
                f"homr wrote nothing for {image.name} (exit {process.returncode}); see {log_path}"
            )
        results.append(target)
    return results
