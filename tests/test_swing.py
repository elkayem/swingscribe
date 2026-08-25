"""SwingModel (plan §5 stage 4, M4).

The stage is pure arithmetic — no CREPE, no torch — so all of this runs in CI,
including the milestone's acceptance criterion. That is deliberate: swing is
the part of the pipeline that is ours rather than a wrapper, so it gets the
tightest guard.

Onsets are injected at a KNOWN beat-upbeat ratio by `generate.swung_phrase`,
which also returns the exact beat grid. Deriving the grid from the notes here
would be assuming the thing under test.
"""

import random

import pytest

from conftest import requires_heavy
from swingscribe.config import Config
from swingscribe.model import BeatGrid, Document, NoteEvent
from swingscribe.stages.swing import (
    beat_phase,
    bur_from_phase,
    dominant_phase,
    offbeat_phases,
    phase_from_bur,
    run,
    swing_spans,
)
from synthetic import generate

# Plan §6 layer 1: parametrize over BUR and tempo.
BURS = [1.0, 1.3, 1.6, 2.0, 2.5]
TEMPOS = [80, 120, 180, 260]

# Plan §5 stage 4 acceptance: "recover it within ±5%".
TOLERANCE = 0.05

# Onset error of the size a real tracker makes.
REALISTIC_JITTER_S = 0.010

# How much error that jitter is ENTITLED to, derived rather than hand-tuned.
#
# The estimator is at its sampling limit: measured phase bias is +0.0002 and
# the spread tracks the standard error of a median, 1.253·σ/√n. So the bound
# comes from the statistics rather than from what happened to pass:
#
#   phase error  ~  1.253 · (jitter / beat_length) / √n_offbeats
#   BUR error    =  phase error / (φ(1−φ))     since d(ln BUR)/dφ = 1/(φ(1−φ))
#
# which is why the same 10ms costs far more at 260bpm (a beat is 231ms) and
# more at extreme ratios (φ(1−φ) is 0.204 at BUR 2.5 against 0.25 at 1.0).
#
# SAFETY covers two things the clean formula omits: measurement runs ~1.5×
# above it at 260bpm, because jitter pushes some offbeats out of the cluster
# and cuts the effective n, and this test takes the WORST of three windows,
# worth roughly another 2×.
SAFETY = 3.0


def _entitled_bur_error(bpm, bur, jitter_s=REALISTIC_JITTER_S, offbeats=16):
    beat = 60.0 / bpm
    phase = bur / (1.0 + bur)
    phase_error = 1.253 * (jitter_s / beat) / (offbeats**0.5)
    return SAFETY * phase_error / (phase * (1.0 - phase))


def test_beat_phase_inside_a_beat():
    beats = [0.0, 1.0, 2.0, 3.0]
    assert beat_phase(1.5, beats) == (1, 0.5)
    assert beat_phase(0.0, beats) == (0, 0.0)
    assert beat_phase(2.25, beats) == (2, 0.25)


def test_beat_phase_outside_the_grid_is_none():
    beats = [1.0, 2.0, 3.0]
    assert beat_phase(0.5, beats) is None  # a pickup before the first beat
    assert beat_phase(3.0, beats) is None  # the grid ends at the last beat
    assert beat_phase(9.0, beats) is None
    assert beat_phase(1.5, [1.0]) is None


def test_beat_phase_handles_an_uneven_grid():
    """Real grids are not metronomic; the phase is relative to each beat."""
    beats = [0.0, 1.0, 3.0]
    assert beat_phase(2.0, beats) == (1, 0.5)


def test_offbeat_phases_filters_the_region():
    beats = [0.0, 1.0, 2.0]
    onsets = [0.0, 0.1, 0.5, 0.67, 0.9, 1.0, 1.67]
    found = offbeat_phases(onsets, beats, 0.35, 0.85)
    assert [round(p, 2) for _, p in found] == [0.5, 0.67, 0.67]
    assert [i for i, _ in found] == [0, 0, 1]


def test_bur_and_phase_round_trip():
    for bur in BURS:
        assert abs(bur_from_phase(phase_from_bur(bur)) - bur) < 1e-12
    assert abs(bur_from_phase(0.5) - 1.0) < 1e-12
    assert abs(phase_from_bur(2.0) - 2.0 / 3.0) < 1e-12


def test_dominant_phase_beats_its_own_histogram_resolution():
    """The estimate must be finer than the 0.02 bin, or BUR cannot be within
    5% — dBUR/dφ is 9 at triplet swing."""
    phases = [0.667] * 20
    found = dominant_phase(phases, bin_width=0.02, cluster_width=0.06)
    assert found is not None
    phase, concentration, standard_error = found
    assert abs(phase - 0.667) < 1e-6
    assert concentration == 1.0
    assert standard_error == 0.0  # identical phases pin it exactly


def test_dominant_phase_reports_low_concentration_when_scattered():
    phases = [0.36, 0.45, 0.55, 0.62, 0.70, 0.78, 0.84]
    found = dominant_phase(phases, bin_width=0.02, cluster_width=0.06)
    assert found is not None
    assert found[1] < 0.5  # nothing here is a peak


def test_dominant_phase_is_not_biased_by_histogram_ties():
    """With ~16 samples over 0.02 bins, raw counts are 1-3 and ties decide the
    peak. Breaking them by bin index biased BUR low by ~2% at every tempo;
    smoothing and breaking toward the window median removed it. Guards the
    regression, since the symptom is a small systematic shift, not a failure."""
    rng = random.Random(5)
    deviations = []
    for _ in range(200):
        phases = [0.6 + rng.gauss(0.0, 0.02) for _ in range(16)]
        found = dominant_phase(phases, 0.02, 0.06)
        assert found is not None
        deviations.append(found[0] - 0.6)
    assert abs(sum(deviations) / len(deviations)) < 0.003


def test_dominant_phase_empty():
    assert dominant_phase([], 0.02, 0.06) is None


@pytest.mark.parametrize("bur", BURS)
@pytest.mark.parametrize("bpm", TEMPOS)
def test_recovers_injected_bur(bur, bpm):
    """The M4 acceptance criterion, over the plan's BUR × tempo matrix."""
    notes, beats = generate.swung_phrase([60, 62] * 32, bpm=bpm, bur=bur)
    spans = swing_spans([n.onset for n in notes], beats)
    assert len(spans) >= 1
    for span in spans:
        assert abs(span.bur - bur) / bur < TOLERANCE


@pytest.mark.parametrize("bur", BURS)
@pytest.mark.parametrize("bpm", TEMPOS)
def test_recovers_injected_bur_with_realistic_jitter(bur, bpm):
    """The same, with onsets displaced the way a real tracker displaces them.

    Seeded, so a failure is reproducible rather than a flake.
    """
    rng = random.Random(f"{bur}-{bpm}")
    notes, beats = generate.swung_phrase([60, 62] * 48, bpm=bpm, bur=bur)
    onsets = [n.onset + rng.gauss(0.0, REALISTIC_JITTER_S) for n in notes]
    spans = swing_spans(onsets, beats)
    assert len(spans) >= 1
    worst = max(abs(s.bur - bur) / bur for s in spans)
    assert worst < _entitled_bur_error(bpm, bur)


@pytest.mark.parametrize("bpm", TEMPOS)
def test_confidence_falls_when_the_estimate_is_imprecise(bpm):
    """Confidence must track precision, not just agreement. Sixteen offbeats
    can agree the feel is swung while leaving BUR loose by 10% -- if that does
    not show up in the number, M5 cannot tell a solid estimate from a shaky
    one."""
    rng = random.Random(bpm)
    notes, beats = generate.swung_phrase([60, 62] * 48, bpm=bpm, bur=2.0)
    clean = swing_spans([n.onset for n in notes], beats)
    noisy = swing_spans([n.onset + rng.gauss(0.0, 0.030) for n in notes], beats)
    assert clean and noisy
    assert max(s.confidence for s in clean) > max(s.confidence for s in noisy)


@pytest.mark.parametrize("bpm", TEMPOS)
def test_straight_eighths_are_not_called_swung(bpm):
    """'Straight sections must be detected, not assumed' (plan §5). Plenty of
    Shorter is even eighths and must not be warped."""
    notes, beats = generate.swung_phrase([60, 62] * 32, bpm=bpm, bur=1.0)
    spans = swing_spans([n.onset for n in notes], beats)
    assert spans
    assert not any(s.is_swung for s in spans)
    assert all(abs(s.bur - 1.0) < 0.05 for s in spans)


def test_triplet_swing_is_called_swung():
    notes, beats = generate.swung_phrase([60, 62] * 32, bpm=180.0, bur=2.0)
    spans = swing_spans([n.onset for n in notes], beats)
    assert spans and all(s.is_swung for s in spans)
    assert all(s.confidence > 0.9 for s in spans)


def test_a_feel_change_is_seen_as_two_spans():
    """BUR is not constant — a player who straightens out mid-chorus must
    produce different spans, which is why this stage windows at all."""
    swung, beats_a = generate.swung_phrase([60, 62] * 16, bpm=180.0, bur=2.0)
    straight, beats_b = generate.swung_phrase([60, 62] * 16, bpm=180.0, bur=1.0)
    shift = beats_a[-1]
    onsets = [n.onset for n in swung] + [n.onset + shift for n in straight]
    beats = beats_a[:-1] + [b + shift for b in beats_b]

    spans = swing_spans(onsets, beats, window_beats=16)
    assert len(spans) >= 2
    assert spans[0].is_swung and abs(spans[0].bur - 2.0) / 2.0 < TOLERANCE
    assert not spans[-1].is_swung and abs(spans[-1].bur - 1.0) < 0.05


def test_a_window_without_enough_offbeats_gets_no_span():
    """Better an admitted gap than an invented BUR over a rest."""
    beats = [i * 0.33 for i in range(33)]
    onsets = [0.33 * 3 + 0.22, 0.33 * 4 + 0.22]  # two offbeats in 32 beats
    assert swing_spans(onsets, beats, window_beats=16, min_onsets=4) == []


def test_scattered_onsets_never_get_high_confidence():
    """Onsets with no eighth-note grid at all must not look like a solid
    reading — this is the property M5 relies on when it decides what to warp.

    Note what is NOT asserted: that they are classified not-swung. Uniform
    noise over an offbeat region of 0.35-0.85 has median phase 0.60, so it
    genuinely IS above straight, and at this window size no statistic
    separates it from real swing (see the docstring below). Confidence is
    where that uncertainty shows up, and it does: scattered onsets score
    0.22-0.37 against 1.0 for a clean swung line.
    """
    rng = random.Random(11)
    beats = [i * 0.33 for i in range(65)]
    onsets = [beats[i] + rng.uniform(0.36, 0.84) * 0.33 for i in range(64) for _ in range(2)]
    spans = swing_spans(onsets, beats)
    assert spans
    assert max(s.confidence for s in spans) < 0.5
    assert not any(s.is_swung and s.confidence > 0.5 for s in spans)


def test_confidence_separates_a_real_reading_from_noise():
    """The number M5 filters on has to actually mean something."""
    rng = random.Random(4)
    notes, beats = generate.swung_phrase([60, 62] * 32, bpm=180.0, bur=2.0)
    clean = swing_spans([n.onset for n in notes], beats)
    realistic = swing_spans([n.onset + rng.gauss(0.0, 0.010) for n in notes], beats)

    scatter_rng = random.Random(11)
    grid = [i * 0.33 for i in range(65)]
    noise = swing_spans(
        [grid[i] + scatter_rng.uniform(0.36, 0.84) * 0.33 for i in range(64) for _ in range(2)],
        grid,
    )
    assert min(s.confidence for s in clean) > 0.9
    assert min(s.confidence for s in realistic) > 0.6
    assert max(s.confidence for s in noise) < 0.5


def test_concentration_alone_cannot_classify_at_this_window_size():
    """Documents a measured limit, so nobody re-derives it the hard way.

    14 offbeats of uniform noise cluster about as tightly as a real solo does
    — small samples clump whatever they are drawn from. Measured separation
    needs ~224 offbeats (64 bars) by concentration, or ~56 by phase spread,
    both far too long to track a feel change. That is why `is_swung` is a
    z-test against straight and concentration survives only as a weak floor.
    """
    rng = random.Random(2)
    real, noise = [], []
    for _ in range(200):
        window = [min(0.849, max(0.351, rng.gauss(0.64, 0.12))) for _ in range(14)]
        real.append(dominant_phase(window, 0.02, 0.06)[1])
        window = [rng.uniform(0.35, 0.85) for _ in range(14)]
        noise.append(dominant_phase(window, 0.02, 0.06)[1])
    real.sort()
    noise.sort()
    # The 10th percentile of real sits BELOW the 90th percentile of noise:
    # the distributions overlap, which is the whole point of this test.
    assert real[len(real) // 10] < noise[len(noise) * 9 // 10]


def test_swing_spans_degenerate_inputs():
    assert swing_spans([], []) == []
    assert swing_spans([1.0], [0.0, 1.0]) == []
    assert swing_spans([0.5], [0.0, 1.0], window_beats=0) == []


def test_spans_tile_the_grid_without_overlapping():
    notes, beats = generate.swung_phrase([60, 62] * 64, bpm=180.0, bur=2.0)
    spans = swing_spans([n.onset for n in notes], beats, window_beats=16)
    assert len(spans) >= 3
    for earlier, later in zip(spans, spans[1:], strict=False):
        assert earlier.end_beat == later.start_beat


def _document(notes, beats, stem="other"):
    return Document(
        audio_path="x.wav",
        sample_rate=16000,
        beat_grid=BeatGrid(beats=beats, downbeats=[], beats_per_bar=4),
        notes={stem: notes},
    )


def test_run_populates_the_document():
    notes, beats = generate.swung_phrase([60, 62] * 32, bpm=180.0, bur=2.0)
    events = [
        NoteEvent(onset=n.onset, duration=n.duration, pitch=n.pitch, confidence=0.9, source="t")
        for n in notes
    ]
    document = run(_document(events, beats), Config())
    assert document.swing
    assert all(abs(s.bur - 2.0) / 2.0 < TOLERANCE for s in document.swing)


def test_run_requires_beats():
    with pytest.raises(ValueError, match="beats to have run first"):
        run(Document(audio_path="x.wav", sample_rate=16000), Config())


def test_run_names_the_missing_stem():
    document = _document([], [0.0, 1.0, 2.0], stem="vocals")
    with pytest.raises(ValueError, match="needs notes for the 'other' stem"):
        run(document, Config())


def test_run_follows_the_configured_stem():
    notes, beats = generate.swung_phrase([60, 62] * 32, bpm=180.0, bur=2.0)
    events = [
        NoteEvent(onset=n.onset, duration=n.duration, pitch=n.pitch, confidence=0.9, source="t")
        for n in notes
    ]
    config = Config()
    config = config.model_copy(update={"swing": config.swing.model_copy(update={"stem": "piano"})})
    document = run(_document(events, beats, stem="piano"), config)
    assert document.swing


@requires_heavy
def test_swing_survives_the_real_transcriber(tmp_path):
    """End-to-end: render swung audio, transcribe it, recover the BUR.

    The pure tests above feed exact onsets. This one feeds the onsets our own
    tracker actually produces, which is the number that matters — and it is
    scored loosely, because the transcriber's timing error is the binding
    constraint here, not the estimator's.
    """
    pytest.importorskip("torch", reason="ml dependency group not installed")
    from swingscribe.stages import transcribe

    bur = 2.0
    notes, beats = generate.swung_phrase([57, 60, 64, 62] * 16, bpm=140.0, bur=bur)
    path = tmp_path / "swung.wav"
    generate.write_wav(path, generate.render(notes))
    estimated, _ = transcribe.analyze(str(path), Config().transcribe)

    spans = swing_spans([n.onset for n in estimated], beats)
    assert spans, "no window had enough offbeats"
    best = max(spans, key=lambda s: s.confidence)
    assert best.is_swung
    assert abs(best.bur - bur) / bur < 0.20
