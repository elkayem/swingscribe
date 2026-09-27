"""The package's own version and pyproject's must agree: `swingscribe
--version` prints the first, and the release zip, the Settings > Apps entry
and the release tag all read the second (v0.2.0 found them hand-kept in two
places)."""

import tomllib
from pathlib import Path

import swingscribe


def test_the_package_version_matches_pyproject():
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    declared = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]
    assert swingscribe.__version__ == declared
