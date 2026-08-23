"""Pipeline orchestration — wiring only, never stage logic (plan §3).

Runs the registered stages in order, threading one Document through them and
caching each stage's output under its chained key. STAGES stays empty in M0;
stages register here milestone by milestone.
"""

from collections.abc import Callable, Sequence
from pathlib import Path

from swingscribe.cache import StageCache, root_key, stage_key
from swingscribe.config import Config
from swingscribe.model import Document
from swingscribe.stages import beats, ingest, separate

Stage = Callable[[Document, Config], Document]

# Ordered (name, stage) pairs. Names must match Config sections — they feed
# the cache keys. Grows milestone by milestone (transcribe at M3, ...).
STAGES: list[tuple[str, Stage]] = [
    ("ingest", ingest.run),
    ("separate", separate.run),
    ("beats", beats.run),
]


def run(
    audio_path: str | Path,
    config: Config,
    stages: Sequence[tuple[str, Stage]] | None = None,
) -> Document:
    """Run the pipeline on one audio file, reusing cached stage outputs.

    `stages` defaults to the global registry; tests inject their own.
    """
    stages = STAGES if stages is None else stages
    if not stages:
        raise NotImplementedError(
            "No pipeline stages are implemented yet — M0 is the skeleton milestone (plan §7)."
        )

    audio_bytes = Path(audio_path).read_bytes()
    cache = StageCache(config.cache_dir)
    doc = Document(audio_path=str(audio_path), sample_rate=config.ingest.sample_rate)

    key = root_key(audio_bytes)
    for name, stage in stages:
        key = stage_key(key, name, config.stage_config(name))
        cached = cache.get(key)
        if cached is not None:
            doc = Document.model_validate_json(cached)
        else:
            doc = stage(doc, config)
            cache.put(key, doc.model_dump_json().encode("utf-8"))
    return doc
