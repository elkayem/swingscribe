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
from swingscribe.stages import (
    beats,
    export,
    ingest,
    meter,
    notate,
    quantize,
    separate,
    swing,
    transcribe,
)

Stage = Callable[[Document, Config], Document]

# Ordered (name, stage) pairs. Names must match Config sections — they feed
# the cache keys. Grows milestone by milestone (swing at M4, ...).
STAGES: list[tuple[str, Stage]] = [
    ("ingest", ingest.run),
    # Beats sits ABOVE separate: measured over 11 WJazzD-matched solos, the
    # full mix tracks better than the separated drum stem (mean beat F1 0.929
    # vs 0.816 -- see stages/beats.py). So the grid needs no stems, and making
    # that explicit in the chain means it costs seconds instead of the minutes
    # a separation costs, and survives a change of separation model instead of
    # being thrown away with it.
    ("beats", beats.run),
    ("separate", separate.run),
    ("transcribe", transcribe.run),
    # Meter sits BELOW transcribe on purpose, though it belongs with beats
    # conceptually. Chained keys invalidate everything downstream of a changed
    # stage, so this placement makes moving a downbeat re-run only
    # swing/quantize (milliseconds) instead of CREPE (docs/meter-plan.md).
    ("meter", meter.run),
    # swing after meter for the same reason meter is after transcribe: it is
    # cheap, and anything above transcribe in the chain re-runs CREPE.
    ("swing", swing.run),
    ("quantize", quantize.run),
    ("notate", notate.run),
    ("export", export.run),
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
    return None if payload is None else _for_path(payload, audio_path)


def _for_path(payload: bytes, audio_path: str | Path) -> Document:
    """A cached Document, re-pointed at the file it was just asked about.

    A cache key is content plus config, never the path (cache.py), and that is
    the design working: the same bytes under a new name are legitimately the
    same entry, so renaming a track must not throw away its separation. But the
    cached PAYLOAD is a whole Document with `audio_path` inside it, so a hit
    restores whatever path was true the first time those bytes were ingested.
    That name may since have been renamed away — or, where byte-identical
    copies are filed under different names, may belong to a different track
    entirely (docs/benchmark-deficiencies.md D18).

    Every reader downstream takes `audio_path` to mean "the file this Document
    is about": `beat_times` re-derives a cache key from it (gui/musicxml.py)
    and `export` takes the part name from it. Neither can be right if the field
    outlives the name it was stored under, so the caller's path wins. Stamping
    it invalidates nothing, because the path reaches no key.
    """
    document = Document.model_validate_json(payload)
    document.audio_path = str(audio_path)
    return document


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
            doc = _for_path(cached, audio_path)
        else:
            progress.report(name, 0.0, "started")
            doc = stage(doc, config)
            progress.report(name, 1.0, "done")
            cache.put(key, doc.model_dump_json().encode("utf-8"))
    return doc
