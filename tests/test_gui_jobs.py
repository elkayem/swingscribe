"""The job runner's kind handling and progress mapping. No ml dependencies —
the worker body is stubbed out, so nothing heavy ever runs.
"""

import threading

import pytest

from swingscribe.config import Config
from swingscribe.gui import jobs
from swingscribe.progress import ProgressEvent


def test_submit_rejects_an_unknown_kind(tmp_path):
    runner = jobs.JobRunner()
    runner._run = lambda job, config, model: None
    with pytest.raises(ValueError):
        runner.submit("x.wav", Config(cache_dir=tmp_path), "htdemucs_ft", "transmogrify")


def test_submit_deduplicates_per_kind(tmp_path):
    """A double-click must not queue the same work twice — but a beats job and
    a separation job on the same track+model are different work."""
    runner = jobs.JobRunner()
    release = threading.Event()
    runner._run = lambda job, config, model: release.wait(5)
    try:
        config = Config(cache_dir=tmp_path)
        first = runner.submit("x.wav", config, "htdemucs_ft", "separate")
        again = runner.submit("x.wav", config, "htdemucs_ft", "separate")
        beats = runner.submit("x.wav", config, "htdemucs_ft", "beats")
        assert first.id == again.id
        assert beats.id != first.id
        assert beats.kind == "beats"
    finally:
        release.set()


def test_progress_maps_stage_fractions_onto_the_kind_weights():
    """Halfway through separation inside a separate job is not 50% of the job —
    the weights say what share of the wall clock each stage actually takes."""
    runner = jobs.JobRunner()
    job = jobs.Job(id="j", path="x", model="m", kind="separate")

    runner._on_progress(job, ProgressEvent(stage="ingest", fraction=0.5))
    assert job.fraction == pytest.approx(0.04 * 0.5)

    runner._on_progress(job, ProgressEvent(stage="separate", fraction=0.5))
    assert job.fraction == pytest.approx(0.04 + 0.96 * 0.5)


def test_a_beats_job_does_not_wait_on_a_separation():
    """Beat tracking reads the mix, not a stem, so a beats job that queued a
    separation would spend minutes on output it never looks at. The weights are
    the visible half of that: separation is not one of this kind's stages, so
    its progress must not move this bar at all."""
    assert [name for name, _ in jobs.JOB_STAGES["beats"]] == ["ingest", "beats"]

    runner = jobs.JobRunner()
    job = jobs.Job(id="j", path="x", model="m", kind="beats")
    runner._on_progress(job, ProgressEvent(stage="separate", fraction=0.5))
    assert job.fraction == 0.0

    runner._on_progress(job, ProgressEvent(stage="beats", fraction=0.5))
    assert job.fraction == pytest.approx(0.25 + 0.75 * 0.5)


def test_progress_never_walks_backwards():
    runner = jobs.JobRunner()
    job = jobs.Job(id="j", path="x", model="m", kind="separate")
    runner._on_progress(job, ProgressEvent(stage="separate", fraction=0.8))
    high = job.fraction
    runner._on_progress(job, ProgressEvent(stage="ingest", fraction=0.1))
    assert job.fraction == high


def test_every_kind_weights_sum_to_one():
    for kind, stages in jobs.JOB_STAGES.items():
        assert sum(share for _name, share in stages) == pytest.approx(1.0), kind


def test_transcribe_progress_ignores_foreign_stages():
    """A transcribe job runs a cached ingest as a precondition. That ingest
    emits progress, but it is not part of this bar — letting it through pushed
    the fraction past 100%."""
    runner = jobs.JobRunner()
    job = jobs.Job(id="j", path="x", model="m", kind="transcribe")

    runner._on_progress(job, ProgressEvent(stage="ingest", fraction=1.0, cached=True))
    assert job.fraction == 0.0  # foreign stage left the bar alone

    runner._on_progress(job, ProgressEvent(stage="transcribe", fraction=0.75))
    assert job.fraction == pytest.approx(0.75)


def test_transcribe_jobs_of_different_spans_do_not_dedupe():
    runner = jobs.JobRunner()
    release = threading.Event()
    runner._run = lambda job, config, model: release.wait(5)
    try:
        config = Config(cache_dir="unused")
        a = runner.submit("x.wav", config, "htdemucs_ft", "transcribe", variant="span-a")
        again = runner.submit("x.wav", config, "htdemucs_ft", "transcribe", variant="span-a")
        b = runner.submit("x.wav", config, "htdemucs_ft", "transcribe", variant="span-b")
        assert a.id == again.id  # same span dedupes
        assert b.id != a.id  # different span does not
    finally:
        release.set()


def test_a_beats_job_does_not_queue_behind_a_separation():
    """The reason "Beats is slow" outlived making beat tracking fast: one
    worker, so an 8-second beats job sat behind an 11-minute demucs run. They
    are different lanes now, and a new job kind is heavy unless it says
    otherwise."""
    runner = jobs.JobRunner()
    assert runner._pool_for("beats") is not runner._pool_for("separate")
    assert runner._pool_for("transcribe") is runner._pool_for("beats")
    assert runner._pool_for("some-future-kind") is runner._pool_for("separate")
