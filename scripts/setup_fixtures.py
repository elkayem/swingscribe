"""Fetch the tier-1 rendering toolchain: a soundfont and the FluidSynth CLI.

Plan §12: tier-1 audio is generated at test time, never stored, and the
soundfont it is generated *from* runs to tens of megabytes — so it is fetched
here rather than committed, and must be permissively licensed.

What this fetches, and why each one:

  - **GeneralUser GS** (S. Christian Collins). Its licence permits private and
    commercial use, modification, and redistribution without royalty — the
    permissive-licence requirement in §12. 32MB, which is the small end for a
    full GM bank, and it has usable sax/trumpet patches, which is the whole
    point: additive synthesis scores ≥0.98 on everything (open-issue #4), so
    the suite needs a timbre that is actually hard.
  - **The FluidSynth CLI**, because it is not in winget on this machine and
    there is no other package manager here. We take the FluidSynth project's
    own portable Windows zip and call `fluidsynth.exe` as a SUBPROCESS, the
    way `stages/ingest.py` calls ffmpeg. Deliberately not pyfluidsynth:
    bindings load a native DLL into the Python process, which is exactly the
    class of thing Windows Application Control blocks here (it already cost
    us numba, and therefore librosa — CLAUDE.md).

Everything lands outside the repo tree, under %LOCALAPPDATA%\\swingscribe on
Windows and ~/.cache/swingscribe elsewhere, so a `git clean` can never remove
a 32MB download and a stray checkout can never commit one.

    uv run python scripts/setup_fixtures.py            # fetch what's missing
    uv run python scripts/setup_fixtures.py --force    # re-fetch everything

TLS on this machine is intercepted (CLAUDE.md), so downloads go through the
exported Windows CA bundle named by SSL_CERT_FILE / REQUESTS_CA_BUNDLE /
CURL_CA_BUNDLE. The script says so plainly when the handshake fails, because
the default error ("certificate verify failed") sends you hunting in the
wrong place.
"""

import argparse
import hashlib
import os
import shutil
import ssl
import sys
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

# Pinned to an immutable commit rather than a branch: a moving soundfont would
# silently move every score in the "synthetic_soundfont" baselines.
GENERALUSER_COMMIT = "97049183643d5fc5a9322a69c5b09efb667c6c3a"  # v2.0.3
GENERALUSER_RAW = "https://raw.githubusercontent.com/mrbumpy409/GeneralUser-GS"
SOUNDFONT_URL = f"{GENERALUSER_RAW}/{GENERALUSER_COMMIT}/GeneralUser-GS.sf2"
SOUNDFONT_HOME = "https://www.schristiancollins.com/generaluser.php"

FLUIDSYNTH_VERSION = "2.6.0"
FLUIDSYNTH_URL = (
    f"https://github.com/FluidSynth/fluidsynth/releases/download/v{FLUIDSYNTH_VERSION}"
    f"/fluidsynth-v{FLUIDSYNTH_VERSION}-win10-x64-cpp11.zip"
)


@dataclass(frozen=True)
class Artifact:
    name: str
    url: str
    filename: str
    sha256: str | None
    env_var: str
    # Set for zips: the archive is unpacked and the member whose path ends
    # with this becomes the target. A suffix, not a full path — the release
    # zip nests everything under a versioned directory.
    member: str | None = None


ARTIFACTS = [
    Artifact(
        name="GeneralUser GS v2.0.3 soundfont",
        url=SOUNDFONT_URL,
        filename="GeneralUser-GS.sf2",
        sha256="9575028c7a1f589f5770fccc8cff2734566af40cd26ed836944e9a5152688cfe",
        env_var="SWINGSCRIBE_SOUNDFONT",
    ),
    Artifact(
        name=f"FluidSynth {FLUIDSYNTH_VERSION} CLI (win10-x64)",
        url=FLUIDSYNTH_URL,
        filename=f"fluidsynth-{FLUIDSYNTH_VERSION}.zip",
        sha256="817262deacaa748edb3af6731dffe1766b00146790becfccc949a9f701e76681",
        env_var="SWINGSCRIBE_FLUIDSYNTH",
        member="bin/fluidsynth.exe",
    ),
]


def fixture_home() -> Path:
    """Where fetched fixtures live — always outside the repo tree (§12)."""
    override = os.environ.get("SWINGSCRIBE_FIXTURE_HOME")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "swingscribe" / "fixtures"


def ssl_context() -> ssl.SSLContext:
    """A context that trusts the exported Windows CA bundle when one is named.

    Without this every fetch here fails on the intercepting proxy's
    certificate — the single most time-expensive trap on this machine.
    """
    for var in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
        bundle = os.environ.get(var)
        if bundle and Path(bundle).is_file():
            return ssl.create_default_context(cafile=bundle)
    return ssl.create_default_context()


def download(url: str, dest: Path) -> bytes:
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(url, context=ssl_context(), timeout=300) as response:
            data = response.read()
    except ssl.SSLError as error:
        raise SystemExit(
            f"TLS failure fetching {url}: {error}\n"
            "TLS is intercepted on this machine (CLAUDE.md). Point SSL_CERT_FILE, "
            "REQUESTS_CA_BUNDLE and CURL_CA_BUNDLE at %USERPROFILE%\\.windows-ca-bundle.pem "
            "and retry."
        ) from error
    tmp = dest.with_suffix(dest.suffix + ".partial")
    tmp.write_bytes(data)
    tmp.replace(dest)  # atomic: a killed download never leaves a valid-looking file
    return data


def verify(artifact: Artifact, path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if artifact.sha256 and digest != artifact.sha256:
        raise SystemExit(
            f"sha256 mismatch for {artifact.name}:\n"
            f"  expected {artifact.sha256}\n  got      {digest}\n"
            f"Delete {path} and retry; if it keeps mismatching, upstream moved and the "
            "pin in scripts/setup_fixtures.py needs updating deliberately."
        )
    return digest


def extract(archive: Path, member: str, dest_dir: Path) -> Path:
    """Unpack one zip whole, and return the path to `member` inside it.

    The whole archive, not just the exe: fluidsynth.exe needs the DLLs that
    ship beside it in bin/.
    """
    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
        matches = [n for n in names if n.endswith(member)]
        if not matches:
            raise SystemExit(f"{member} not found in {archive} (contains {len(names)} entries)")
        zf.extractall(dest_dir)
    return dest_dir / matches[0]


def installed_path(artifact: Artifact, home: Path) -> Path | None:
    """Where this artifact already sits, or None if it isn't fetched yet."""
    raw = home / artifact.filename
    if not artifact.member:
        return raw if raw.is_file() else None
    unpacked = home / raw.stem
    if not unpacked.is_dir():
        return None
    return next((p for p in unpacked.rglob(Path(artifact.member).name) if p.is_file()), None)


def fetch(artifact: Artifact, home: Path, force: bool) -> Path:
    raw = home / artifact.filename

    existing = installed_path(artifact, home)
    if existing and not force:
        print(f"  already present: {existing}")
        return existing

    print(f"  downloading {artifact.url}")
    download(artifact.url, raw)
    digest = verify(artifact, raw)
    size_mb = raw.stat().st_size / 1e6
    print(f"  {size_mb:.1f} MB, sha256 {digest}")
    if artifact.sha256 is None:
        print(f"  (unpinned — pin this digest in {Path(__file__).name} to lock the version)")

    if not artifact.member:
        return raw
    unpacked = home / raw.stem
    if unpacked.exists():
        shutil.rmtree(unpacked)
    target = extract(raw, artifact.member, unpacked)
    raw.unlink()  # nothing needs the zip once it is unpacked
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true", help="re-fetch even if present")
    args = parser.parse_args()

    home = fixture_home()
    print(f"fixture home: {home}\n")

    resolved: dict[str, Path] = {}
    for artifact in ARTIFACTS:
        print(artifact.name)
        resolved[artifact.env_var] = fetch(artifact, home, args.force)
        print()

    print(f"GeneralUser GS is used under its own permissive licence — see {SOUNDFONT_HOME}")
    print("\nPoint the tests at these (PowerShell):\n")
    for var, path in resolved.items():
        print(f'  $env:{var} = "{path}"')
    print('  $env:SWINGSCRIBE_HEAVY_TESTS = "1"')
    print("\nThen: uv run pytest tests/test_synthetic.py -k soundfont")
    print(
        "\nThe defaults above are also where the tests look on their own, so the env "
        "vars are only needed if you moved something."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
