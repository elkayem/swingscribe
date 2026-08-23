"""Shared test plumbing: the requires_audio marker and manifest-verified fixtures (plan §12).

Audio never lives in the repo. Tests that need real recordings point
SWINGSCRIBE_FIXTURES at a local directory and resolve files through
fixture_audio, which verifies each file's sha256 against
tests/fixtures/manifest.yaml — the wrong take of a recording fails loudly
instead of silently corrupting an eval.
"""

import hashlib
import os
from pathlib import Path

import pytest
import yaml

FIXTURE_DIR = os.environ.get("SWINGSCRIBE_FIXTURES")

requires_audio = pytest.mark.skipif(
    not FIXTURE_DIR,
    reason="Set SWINGSCRIBE_FIXTURES to a local audio directory (see swingscribe-plan.md §12)",
)

MANIFEST_PATH = Path(__file__).parent / "fixtures" / "manifest.yaml"


def load_manifest() -> list[dict]:
    data = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8")) or {}
    return data.get("fixtures") or []


@pytest.fixture
def fixture_audio():
    """Resolve a manifest fixture id to a checksum-verified local audio path."""

    def _resolve(fixture_id: str) -> Path:
        if not FIXTURE_DIR:
            pytest.skip("SWINGSCRIBE_FIXTURES is not set")
        entries = {entry["id"]: entry for entry in load_manifest()}
        if fixture_id not in entries:
            pytest.fail(f"fixture id {fixture_id!r} not in {MANIFEST_PATH}")
        entry = entries[fixture_id]
        path = Path(FIXTURE_DIR) / entry["filename"]
        if not path.is_file():
            pytest.skip(f"fixture audio not present locally: {path}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != entry["sha256"]:
            pytest.fail(
                f"sha256 mismatch for {fixture_id!r}: expected {entry['sha256']}, "
                f"got {digest}. Wrong take or corrupted file (plan §6, §12)."
            )
        return path

    return _resolve
