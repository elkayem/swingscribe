"""Pipeline orchestration: cache reuse and chained invalidation, using dummy stages.

No real stage logic exists in M0; these tests inject fake stages to prove the
cache-aware run loop behaves per plan §3.
"""

import pytest

from swingscribe import pipeline
from swingscribe.config import Config


def make_config(tmp_path) -> Config:
    return Config(cache_dir=tmp_path / "cache")


def write_audio(tmp_path) -> str:
    path = tmp_path / "input.audio"
    path.write_bytes(b"fake audio bytes")
    return str(path)


def test_run_with_no_stages_raises(tmp_path):
    with pytest.raises(NotImplementedError):
        pipeline.run(write_audio(tmp_path), make_config(tmp_path), stages=[])


def test_cache_version_bump_invalidates(tmp_path):
    import sys
    import types

    module = types.ModuleType("fake_stage_module")
    sys.modules["fake_stage_module"] = module
    try:
        calls = []

        def separate(doc, config):
            calls.append("separate")
            return doc

        separate.__module__ = "fake_stage_module"
        stages = [("separate", separate)]
        audio = write_audio(tmp_path)
        config = make_config(tmp_path)

        pipeline.run(audio, config, stages=stages)
        pipeline.run(audio, config, stages=stages)
        assert calls == ["separate"]  # same version → cache hit

        module.CACHE_VERSION = 2  # stage behavior changed without config change
        pipeline.run(audio, config, stages=stages)
        assert calls == ["separate", "separate"]  # version bump → recompute
    finally:
        del sys.modules["fake_stage_module"]


def test_registered_stages_are_current():
    assert [name for name, _ in pipeline.STAGES] == [
        "ingest",
        "separate",
        "beats",
        "transcribe",
        "meter",
    ]


def test_meter_runs_below_transcribe():
    """Order is a caching decision, not a taste one. Meter belongs with beats
    conceptually, but chained keys mean anything above transcribe invalidates
    it — so moving a downbeat would re-run CREPE (docs/meter-plan.md)."""
    names = [name for name, _ in pipeline.STAGES]
    assert names.index("meter") > names.index("transcribe")


def test_registered_stage_names_have_config_sections():
    config = Config()
    for name, _ in pipeline.STAGES:
        assert isinstance(config.stage_config(name), dict)


def test_second_run_hits_cache(tmp_path):
    calls = []

    def separate(doc, config):
        calls.append("separate")
        return doc.model_copy(update={"stems": {"drums": "drums.wav"}})

    stages = [("separate", separate)]
    audio = write_audio(tmp_path)
    config = make_config(tmp_path)

    first = pipeline.run(audio, config, stages=stages)
    second = pipeline.run(audio, config, stages=stages)

    assert first.stems == {"drums": "drums.wav"}
    assert second.stems == {"drums": "drums.wav"}
    assert calls == ["separate"]  # the second run never re-ran the stage


def test_upstream_config_change_reruns_downstream(tmp_path):
    calls = []

    def separate(doc, config):
        calls.append("separate")
        return doc.model_copy(update={"stems": {"other": config.separate.model}})

    def transcribe(doc, config):
        calls.append("transcribe")
        return doc

    stages = [("separate", separate), ("transcribe", transcribe)]
    audio = write_audio(tmp_path)

    config_a = make_config(tmp_path)
    pipeline.run(audio, config_a, stages=stages)

    config_b = config_a.model_copy(
        update={"separate": config_a.separate.model_copy(update={"model": "bs_roformer"})}
    )
    doc = pipeline.run(audio, config_b, stages=stages)

    # Both stages re-ran under the new separation config — no stale transcribe hit.
    assert calls == ["separate", "transcribe", "separate", "transcribe"]
    assert doc.stems == {"other": "bs_roformer"}


def test_downstream_config_change_reuses_upstream(tmp_path):
    calls = []

    def separate(doc, config):
        calls.append("separate")
        return doc

    def quantize(doc, config):
        calls.append("quantize")
        return doc

    stages = [("separate", separate), ("quantize", quantize)]
    audio = write_audio(tmp_path)

    config_a = make_config(tmp_path)
    pipeline.run(audio, config_a, stages=stages)

    config_b = config_a.model_copy(
        update={"quantize": config_a.quantize.model_copy(update={"resolution": 32})}
    )
    pipeline.run(audio, config_b, stages=stages)

    # Tweaking only the quantizer must not re-run separation (plan §3).
    assert calls == ["separate", "quantize", "quantize"]


def test_cached_document_peeks_without_executing(tmp_path):
    """The GUI's "is the beat grid free?" question: answered from the cache
    alone, never by running a stage."""
    calls = []

    def stage(doc, config):
        calls.append("ran")
        return doc.model_copy(update={"sample_rate": 999})

    stages = [("ingest", stage)]
    audio = write_audio(tmp_path)
    config = make_config(tmp_path)

    # Nothing cached: a peek returns None and runs nothing.
    assert pipeline.cached_document(audio, config, stages) is None
    assert calls == []

    document = pipeline.run(audio, config, stages=stages)
    assert calls == ["ran"]

    # Cached: the peek returns the same document, still without executing.
    peeked = pipeline.cached_document(audio, config, stages)
    assert peeked is not None
    assert peeked.sample_rate == document.sample_rate
    assert calls == ["ran"]

    # A config change re-keys the chain, so the peek honestly says "not ready".
    moved = config.model_copy(
        update={"ingest": config.ingest.model_copy(update={"sample_rate": 22050})}
    )
    assert pipeline.cached_document(audio, moved, stages) is None


def test_cached_document_with_no_stages_is_none(tmp_path):
    assert pipeline.cached_document(write_audio(tmp_path), make_config(tmp_path), []) is None
