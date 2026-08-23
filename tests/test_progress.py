"""Progress side channel and the separate stage's demucs adapter.

Both are plain Python with no ml dependencies, so this runs in CI.
"""

import threading

from swingscribe import progress
from swingscribe.stages.separate import _progress_callback


def test_no_sink_is_a_noop():
    # The CLI's normal case: nobody listening, nothing raised.
    progress.report("separate", 0.5, "hello")


def test_sink_receives_events_and_is_reset():
    seen = []
    with progress.sink(seen.append):
        progress.report("separate", 0.25, "quarter")
    progress.report("separate", 0.9, "after")  # outside the block: dropped

    assert len(seen) == 1
    assert seen[0].stage == "separate"
    assert seen[0].fraction == 0.25
    assert seen[0].message == "quarter"
    assert seen[0].cached is False


def test_fraction_is_clamped_and_none_passes_through():
    seen = []
    with progress.sink(seen.append):
        progress.report("a", 5.0)
        progress.report("b", -1.0)
        progress.report("c", None)
    assert [event.fraction for event in seen] == [1.0, 0.0, None]


def test_broken_sink_never_breaks_the_pipeline():
    def explode(_event):
        raise RuntimeError("reporter is broken")

    with progress.sink(explode):
        progress.report("separate", 0.5)  # must not raise


def test_sinks_are_isolated_per_thread():
    """The GUI runs jobs on worker threads; one job's progress must not land in
    another's bar. ContextVars give us that, but only if we don't leak a sink."""
    main_events = []
    thread_events = []

    def worker():
        with progress.sink(thread_events.append):
            progress.report("separate", 0.7)

    with progress.sink(main_events.append):
        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()
        progress.report("ingest", 1.0)

    assert [event.stage for event in main_events] == ["ingest"]
    assert [event.stage for event in thread_events] == ["separate"]


def test_pipeline_reports_cached_stages(tmp_path):
    from swingscribe.config import Config
    from swingscribe.model import Document
    from swingscribe.pipeline import run

    audio = tmp_path / "fake.wav"
    audio.write_bytes(b"not really audio, but the cache only hashes bytes")
    config = Config(cache_dir=tmp_path / "cache")
    stages = [("ingest", lambda doc, _cfg: doc.model_copy(update={"sample_rate": 22050}))]

    first, second = [], []
    with progress.sink(first.append):
        run(audio, config, stages=stages)
    with progress.sink(second.append):
        run(audio, config, stages=stages)

    assert [event.message for event in first] == ["started", "done"]
    assert [(event.message, event.cached) for event in second] == [("cached", True)]
    assert isinstance(Document(audio_path=str(audio), sample_rate=44100), Document)


# ── the demucs adapter ──────────────────────────────────────────────────────


def _events_from(payloads):
    seen = []
    callback = _progress_callback()
    with progress.sink(seen.append):
        for payload in payloads:
            callback(payload)
    return [event.fraction for event in seen]


def test_demucs_callback_spans_the_bag_of_models():
    """htdemucs_ft is a bag of four models, each walked over the whole track.
    Halfway through the second model is 3/8 of the job, not 1/2."""
    fractions = _events_from(
        [
            {"models": 4, "model_idx_in_bag": 0, "segment_offset": 0, "audio_length": 100},
            {"models": 4, "model_idx_in_bag": 1, "segment_offset": 50, "audio_length": 100},
            {"models": 4, "model_idx_in_bag": 3, "segment_offset": 100, "audio_length": 100},
        ]
    )
    assert fractions == [0.0, 0.375, 1.0]


def test_demucs_callback_is_monotonic():
    # Segments complete out of order with jobs>0, and the callback fires on both
    # start and end. A bar that walks backwards reads as a bug.
    fractions = _events_from(
        [
            {"models": 1, "model_idx_in_bag": 0, "segment_offset": 80, "audio_length": 100},
            {"models": 1, "model_idx_in_bag": 0, "segment_offset": 20, "audio_length": 100},
        ]
    )
    assert fractions == [0.8, 0.8]


def test_demucs_callback_survives_a_sparse_payload():
    assert _events_from([{}]) == [0.0]
