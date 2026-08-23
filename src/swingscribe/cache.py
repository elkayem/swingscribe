"""Disk cache for stage outputs, keyed by chained content hashes (plan §3).

Key scheme:

    root_key  = sha256(audio_bytes)
    stage_key = sha256(upstream_key + stage_name + canonical_json(stage_config))

Each stage's key folds in the key of the stage that produced its input, so a
key transitively encodes the audio and every upstream stage's config. A flat
sha256(audio_bytes + stage_name + stage_config) scheme would keep serving
stale downstream hits after an upstream config change; chaining closes that
hole while still letting a downstream-only tweak reuse all upstream work.
"""

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_HEX_DIGITS = set("0123456789abcdef")


def canonical_json(config: Mapping[str, Any]) -> str:
    """Deterministic serialization — key order and whitespace never affect the hash."""
    return json.dumps(config, sort_keys=True, separators=(",", ":"))


def root_key(audio_bytes: bytes) -> str:
    """Key for the pipeline's root input: the raw audio bytes."""
    return hashlib.sha256(audio_bytes).hexdigest()


def stage_key(upstream_key: str, stage_name: str, stage_config: Mapping[str, Any]) -> str:
    """Key for one stage's output, chained onto its upstream stage's key."""
    h = hashlib.sha256()
    h.update(upstream_key.encode("ascii"))
    h.update(b"\x00")
    h.update(stage_name.encode("utf-8"))
    h.update(b"\x00")
    h.update(canonical_json(stage_config).encode("utf-8"))
    return h.hexdigest()


class StageCache:
    """Content-addressed byte store on disk. Callers own serialization; the
    *_json helpers cover the common pydantic/JSON payload case."""

    def __init__(self, cache_dir: str | Path) -> None:
        self.cache_dir = Path(cache_dir)

    def _path(self, key: str) -> Path:
        if len(key) != 64 or not set(key) <= _HEX_DIGITS:
            raise ValueError(f"not a sha256 hex key: {key!r}")
        # Two-level fan-out keeps directory listings sane after thousands of runs.
        return self.cache_dir / key[:2] / f"{key[2:]}.bin"

    def has(self, key: str) -> bool:
        return self._path(key).is_file()

    def get(self, key: str) -> bytes | None:
        try:
            return self._path(key).read_bytes()
        except FileNotFoundError:
            return None

    def put(self, key: str, payload: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write-then-replace so a crash mid-write never leaves a torn entry.
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(payload)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def get_json(self, key: str) -> Any | None:
        payload = self.get(key)
        return None if payload is None else json.loads(payload)

    def put_json(self, key: str, obj: Any) -> None:
        self.put(key, json.dumps(obj).encode("utf-8"))
