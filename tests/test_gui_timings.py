"""The separation-time estimate: seeds until this machine has taught it."""

import pytest

from swingscribe.gui import timings


def test_the_seed_predicts_from_audio_length_and_model_load(tmp_path):
    # BS-Roformer-SW: a minute to load, then 2.5x realtime.
    assert timings.estimate(tmp_path, "bsroformer_sw", 60.0) == pytest.approx(60.0 + 150.0)
    # htdemucs has no fixed cost and runs well under realtime.
    assert timings.estimate(tmp_path, "htdemucs", 600.0) == pytest.approx(168.0)
    # An unknown model gets a realtime guess rather than a crash.
    assert timings.estimate(tmp_path, "something_new", 100.0) == pytest.approx(100.0)


def test_two_recorded_runs_replace_the_seed_with_this_machine(tmp_path):
    timings.record(tmp_path, "htdemucs", 100.0, 50.0)
    assert timings.speed(tmp_path, "htdemucs")[0] == pytest.approx(0.28)  # one run: still the seed
    timings.record(tmp_path, "htdemucs", 200.0, 100.0)
    assert timings.speed(tmp_path, "htdemucs")[0] == pytest.approx(0.5)
    assert timings.estimate(tmp_path, "htdemucs", 60.0) == pytest.approx(30.0)


def test_the_fixed_load_cost_is_taken_off_before_measuring_the_rate(tmp_path):
    # A 40 s span through the Roformer that took 160 s: 60 s of that is load.
    timings.record(tmp_path, "bsroformer_sw", 40.0, 160.0)
    timings.record(tmp_path, "bsroformer_sw", 40.0, 160.0)
    per_second, load_s = timings.speed(tmp_path, "bsroformer_sw")
    assert load_s == 60.0
    assert per_second == pytest.approx(2.5)


def test_nonsense_runs_are_not_recorded_and_the_file_is_deletable(tmp_path):
    timings.record(tmp_path, "htdemucs", 0.0, 5.0)
    timings.record(tmp_path, "htdemucs", 100.0, 0.0)
    assert timings.load(tmp_path) == {}
    for _ in range(20):
        timings.record(tmp_path, "htdemucs", 10.0, 3.0)
    assert len(timings.load(tmp_path)["htdemucs"]) == timings.KEEP_SAMPLES
    (tmp_path / "gui" / timings.TIMINGS_FILE).unlink()
    assert timings.speed(tmp_path, "htdemucs")[0] == pytest.approx(0.28)  # seeds are back
