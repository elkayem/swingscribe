"""Pipeline orchestration — wiring only, never stage logic (plan §3).

Runs the registered stages in order, threading one Document through them and
caching each stage's output under its chained key. STAGES stays empty in M0;
stages register here milestone by milestone.
"""

import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from swingscribe import progress
from swingscribe.cache import StageCache, root_key, stage_key
from swingscribe.config import Config
from swingscribe.model import Document
from swingscribe.stages import beats, ingest, meter, separate, transcribe

Stage = Callable[[Document, Config], Document]

# Ordered (name, stage) pairs. Names must match Config sections — they feed
# the cache keys. Grows milestone by milestone (swing at M4, ...).
STAGES: list[tuple[str, Stage]] = [
    ("ingest", ingest.run),
    ("separate", separate.run),
    ("beats", beats.run),
    ("transcribe", transcribe.run),
    # Meter sits BELOW transcribe on purpose, though it belongs with beats
    # conceptually. Chained keys invalidate everything downstream of a changed
    # stage, so this placement makes moving a downbeat re-run only
    # swing/quantize (milliseconds) instead of CREPE (docs/meter-plan.md).
    ("meter", meter.run),
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
    return _run_stages(audio_bytes, audio_path, config, stages)


def cached_document(
    audio_path: str | Path,
    config: Config,
    stages: Sequence[tuple[str, Stage]],
) -> Document | None:
    """The Document `run` would produce for these stages, but only if the final
    stage is already cached — never executes anything.

    Exists for the GUI: "show me the beat grid if it's free, otherwise tell me
    it isn't" must not be answerable only by a call that might block for
    minutes. Only the last key needs checking — chained keys transitively
    encode the audio and every upstream stage's config (plan §3), so a hit on
    the final stage proves the whole chain was computed with this exact config.
    """
    if not stages:
        return None
    cache = StageCache(config.cache_dir)
    key = root_key(Path(audio_path).read_bytes())
    for name, stage in stages:
        key = stage_key(key, _cache_name(name, stage), config.stage_config(name))
    payload = cache.get(key)
    return None if payload is None else Document.model_validate_json(payload)


def _cache_name(name: str, stage: Stage) -> str:
    """Stage name as it feeds the cache key, folding in the stage module's
    CACHE_VERSION. A stage whose behavior changes without a config change
    must bump CACHE_VERSION, or cached grids from the old code keep being
    served. Version 1 (the default) keeps the bare name, so existing cache
    entries for unversioned stages stay valid."""
    module = sys.modules.get(getattr(stage, "__module__", ""), None)
    version = getattr(module, "CACHE_VERSION", 1)
    return name if str(version) == "1" else f"{name}@v{version}"


def _run_stages(
    audio_bytes: bytes,
    audio_path: str | Path,
    config: Config,
    stages: Sequence[tuple[str, Stage]],
) -> Document:
    cache = StageCache(config.cache_dir)
    doc = Document(audio_path=str(audio_path), sample_rate=config.ingest.sample_rate)

    key = root_key(audio_bytes)
    for name, stage in stages:
        key = stage_key(key, _cache_name(name, stage), config.stage_config(name))
        cached = cache.get(key)
        if cached is not None:
            # Report cache hits too: a UI must be able to tell "finished in
            # 20ms because it was cached" from "still thinking".
            progress.report(name, 1.0, "cached", cached=True)
            doc = Document.model_validate_json(cached)
        else:
            progress.report(name, 0.0, "started")
            doc = stage(doc, config)
            progress.report(name, 1.0, "done")
            cache.put(key, doc.model_dump_json().encode("utf-8"))
    return doc
