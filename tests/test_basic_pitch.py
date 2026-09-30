"""Basic Pitch, the horn's hole-filler (swingscribe/basic_pitch.py, A2).

Three tiers. The vendored graph's identity needs nothing but hashlib, so it
runs in CI. The port's arithmetic -- windowing, unwrapping, frame times, the
note decoder -- runs on synthetic posteriorgrams and needs numpy (the ml
group; CI skips it). One test runs the real graph on a rendered tone and
needs onnxruntime too.

What these cannot hold is the port against the upstream package itself,
which cannot be imported here (librosa, resampy, numba). That was measured
once against the bake-off's WSL run over its 111 regions: from the same
posteriorgrams the decoder reproduced all 37,531 of the upstream decode's
notes exactly (docs/frontend-bakeoff.md, "Shipped").
"""

import hashlib

import pytest

from swingscribe import basic_pitch


def test_the_vendored_graph_is_the_one_the_bake_off_measured():
    """Byte for byte basic-pitch 0.4.0's icassp_2022/nmp.onnx. A different
    graph -- a fine-tune, a re-export -- is a different transcriber and must
    arrive with a config field that moves the horn keys, not by swapping the
    file under a key that promises the old notes."""
    assert basic_pitch.MODEL_PATH.is_file(), "the ONNX graph must ship inside the package"
    digest = hashlib.sha256(basic_pitch.MODEL_PATH.read_bytes()).hexdigest()
    assert digest == basic_pitch.MODEL_SHA256


def test_the_graphs_apache_licence_ships_beside_it():
    """Apache-2.0 section 4(a): whoever receives the graph receives the
    licence. The NOTICE is reproduced in packaging/NOTICES.md."""
    licence = basic_pitch.MODEL_PATH.with_name("basic-pitch-LICENSE.txt")
    text = licence.read_text(encoding="utf-8")
    assert "Copyright 2022 Spotify AB" in text
    assert "Apache License" in text and "Version 2.0" in text


def test_the_module_imports_without_the_ml_group():
    """Everything heavy is imported inside functions: the stage imports this
    lazily, but a test that only wants the constants must not need numpy."""
    assert basic_pitch.SAMPLE_RATE == 22050
    assert basic_pitch.AUDIO_N_SAMPLES == 43844
    assert basic_pitch.HOP_SIZE == 43844 - 30 * 256


def test_the_minimum_length_converts_at_the_float_frame_rate():
    """23 ms is two frames at 86.13 fps, and the decoder keeps a note only
    if it is LONGER than that: three frames, 35 ms. Upstream's 127.7 ms
    default is eleven."""
    assert basic_pitch.min_note_frames(23.0) == 2
    assert basic_pitch.min_note_frames(127.7) == 11


# ── the port's arithmetic (numpy) ─────────────────────────────────────────


@pytest.fixture
def np():
    return pytest.importorskip("numpy", reason="ml dependency group not installed")


def test_the_region_is_heard_with_a_second_either_side(np):
    mono = np.arange(100 * 10, dtype=np.float32)  # 10 s at 100 Hz
    segment, start = basic_pitch.region_audio(mono, 100, (3.0, 5.0))
    assert start == 2.0
    assert segment[0] == 200 and len(segment) == 400  # 2.0 s to 6.0 s


def test_the_margin_stops_at_the_start_and_an_open_region_runs_to_the_end(np):
    mono = np.arange(100 * 10, dtype=np.float32)
    segment, start = basic_pitch.region_audio(mono, 100, (0.5, None))
    assert start == 0.0 and len(segment) == 1000
    whole, start = basic_pitch.region_audio(mono, 100, None)
    assert start == 0.0 and whole is mono


def test_frame_times_are_upstreams_including_the_per_window_correction(np):
    times = basic_pitch.frame_times(400)
    hop = 256 / 22050
    assert times[0] == 0.0
    assert times[171] == pytest.approx(171 * hop)  # still the first 172 frames
    correction = hop * (172 - 43844 / 256) + 0.0018
    assert times[172] == pytest.approx(172 * hop - correction)
    assert times[344] == pytest.approx(344 * hop - 2 * correction)


def test_unwrap_drops_half_the_overlap_from_each_window_and_trims(np):
    windows = np.stack([np.full((172, 88), float(i)) for i in range(3)])
    samples = 3 * 36164  # three hops of audio
    out = basic_pitch.unwrap(windows, samples)
    assert out.shape == (int(np.floor(samples * 86 / 22050)), 88)
    assert (out[:142] == 0).all() and (out[142:284] == 1).all()


def test_posteriorgrams_window_the_audio_as_upstream_does(np):
    """Leading zeros of half the overlap, 2 s windows every HOP_SIZE, the
    last one zero-padded; the output trimmed to the audio's length."""
    seen = []

    class Model:
        def run(self, names, feeds):
            x = feeds[basic_pitch.INPUT_NAME]
            seen.append(x)
            n = x.shape[0]
            return [np.zeros((n, 172, 88), np.float32), np.ones((n, 172, 88), np.float32)]

    audio = np.ones(22050 * 5, dtype=np.float32)
    note, onset = basic_pitch.posteriorgrams(audio, Model(), batch=2)
    x = np.concatenate(seen)
    assert x.shape[1:] == (43844, 1)
    assert len(x) == len(range(0, len(audio) + 3840, 36164))
    assert (x[0, :3840, 0] == 0).all() and (x[0, 3840:, 0] == 1).all()
    assert note.shape == onset.shape == (int(np.floor(len(audio) * 86 / 22050)), 88)


def test_local_maxima_is_argrelmax_in_time(np):
    values = np.array([[0.9, 0.1], [0.5, 0.2], [0.8, 0.2], [0.3, 0.4], [0.3, 0.9]])
    mask = basic_pitch.local_maxima(values)
    # The first and last frames are never peaks ("clip" compares them with
    # themselves); a plateau is not a strict maximum either.
    assert mask.tolist() == [
        [False, False],
        [False, False],
        [True, False],
        [False, False],
        [False, False],
    ]
    scipy_signal = pytest.importorskip("scipy.signal")
    rng = np.random.default_rng(0)
    noise = rng.random((200, 88))
    expected = np.zeros(noise.shape, dtype=bool)
    expected[scipy_signal.argrelmax(noise, axis=0)] = True
    assert (basic_pitch.local_maxima(noise) == expected).all()


def test_a_jump_in_the_frames_is_an_onset_scaled_to_the_onset_maximum(np):
    frames = np.zeros((10, 88), np.float32)
    frames[5:, 40] = 0.8
    onsets = np.zeros((10, 88), np.float32)
    onsets[2, 10] = 0.5
    inferred = basic_pitch.inferred_onsets(onsets, frames)
    assert inferred[5, 40] == pytest.approx(0.5)  # rescaled to the onset map's max
    assert inferred[2, 10] == pytest.approx(0.5)


def test_silence_infers_nothing_rather_than_nan(np):
    """Upstream divides by the largest frame jump unguarded."""
    frames = np.zeros((10, 88), np.float32)
    onsets = np.zeros((10, 88), np.float32)
    assert not np.isnan(basic_pitch.inferred_onsets(onsets, frames)).any()
    assert basic_pitch.output_to_notes(frames, onsets, 0.8, 0.3, 2) == []


def grams(np, n=60):
    return np.zeros((n, 88), np.float32), np.zeros((n, 88), np.float32)


def test_a_note_runs_from_its_onset_peak_to_where_the_frames_fall_away(np):
    frames, onsets = grams(np)
    onsets[9:12, 39] = [0.5, 0.9, 0.5]  # a peak at frame 10
    frames[10:31, 39] = 0.6
    notes = basic_pitch.output_to_notes(frames, onsets, 0.8, 0.3, 2, infer_onsets=False)
    assert notes == [(10, 31, 60, pytest.approx(0.6))]


def test_an_onset_under_the_threshold_is_no_note(np):
    frames, onsets = grams(np)
    onsets[9:12, 39] = [0.5, 0.79, 0.5]
    frames[10:31, 39] = 0.6
    assert basic_pitch.output_to_notes(frames, onsets, 0.8, 0.3, 2, infer_onsets=False) == []


def test_a_note_must_be_longer_than_the_minimum(np):
    frames, onsets = grams(np)
    onsets[9:12, 39] = [0.5, 0.9, 0.5]
    frames[10:12, 39] = 0.6  # two frames: not longer than 2
    onsets[29:32, 50] = [0.5, 0.9, 0.5]
    frames[30:33, 50] = 0.6  # three frames: kept
    notes = basic_pitch.output_to_notes(frames, onsets, 0.8, 0.3, 2, infer_onsets=False)
    assert [(n[0], n[1], n[2]) for n in notes] == [(30, 33, 71)]


def test_a_repeated_note_is_two_notes_and_the_later_one_claims_first(np):
    """Onsets are taken latest first and each note zeroes the energy it
    claims, so the earlier note of a repeat ends where the later begins."""
    frames, onsets = grams(np)
    for peak in (10, 25):
        onsets[peak - 1 : peak + 2, 39] = [0.5, 0.9, 0.5]
    frames[10:40, 39] = 0.6
    notes = basic_pitch.output_to_notes(frames, onsets, 0.8, 0.3, 2, infer_onsets=False)
    assert [(n[0], n[1]) for n in notes] == [(25, 40), (10, 25)]


def test_transcribe_reports_whole_track_seconds_inside_the_region_only(np):
    """The model hears the region and a second either side; a note heard in
    the margin is not reported, and every onset is in track time."""

    class Model:
        def run(self, names, feeds):
            n = feeds[basic_pitch.INPUT_NAME].shape[0]
            note = np.zeros((n, 172, 88), np.float32)
            onset = np.zeros((n, 172, 88), np.float32)
            # Window 0's frame 15 is output frame 0 (half the overlap is cut).
            for frame in (15 + 20, 15 + 100):  # 0.23 s and 1.16 s into the audio heard
                onset[0, frame - 1 : frame + 2, 45] = [0.5, 0.95, 0.5]
                note[0, frame : frame + 10, 45] = 0.7
            return [note, onset]

    rate = basic_pitch.SAMPLE_RATE
    mono = np.zeros(rate * 10, np.float32)
    notes = basic_pitch.transcribe(
        mono,
        rate,
        (5.0, 7.0),
        onset_threshold=0.8,
        frame_threshold=0.3,
        min_note_ms=23,
        model=Model(),
    )
    # Heard from 4.0 s: the first onset (4.23 s) is in the margin, the second is in.
    assert len(notes) == 1
    note = notes[0]
    assert note["pitch"] == 66
    assert note["onset"] == pytest.approx(4.0 + 100 * 256 / 22050)
    assert note["duration"] == pytest.approx(10 * 256 / 22050)
    assert note["confidence"] == pytest.approx(0.7)
    assert "velocity" not in note  # fill_gaps would read it as MIDI velocity


# ── the real graph (onnxruntime) ─────────────────────────────────────────


def test_the_graph_hears_two_rendered_notes(np):
    pytest.importorskip("onnxruntime", reason="onnxruntime is in the ml group")
    rate = basic_pitch.SAMPLE_RATE

    def tone(midi, seconds=0.4):
        t = np.arange(int(rate * seconds)) / rate
        f = 440.0 * 2 ** ((midi - 69) / 12)
        envelope = np.minimum(1.0, t / 0.005) * np.exp(-3 * t)
        return sum((0.5 / k) * np.sin(2 * np.pi * f * k * t) for k in range(1, 6)) * envelope

    gap = np.zeros(rate // 10)
    signal = np.concatenate([np.zeros(rate // 2), tone(60), gap, tone(64), np.zeros(rate)])
    notes = basic_pitch.transcribe(
        signal.astype(np.float32),
        rate,
        None,
        onset_threshold=0.8,
        frame_threshold=0.3,
        min_note_ms=23,
    )
    assert [n["pitch"] for n in notes] == [60, 64]
    assert notes[0]["onset"] == pytest.approx(0.5, abs=0.02)
    assert notes[1]["onset"] == pytest.approx(1.0, abs=0.02)


def test_the_graph_hears_nothing_in_silence(np):
    pytest.importorskip("onnxruntime", reason="onnxruntime is in the ml group")
    note, onset = basic_pitch.posteriorgrams(np.zeros(22050 * 3, np.float32))
    assert note.shape == onset.shape == (258, 88)
    assert basic_pitch.output_to_notes(note, onset, 0.8, 0.3, 2) == []
