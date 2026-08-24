"""Tier-1 synthetic scoring (plan §6 Layer 1, open-issue #4).

Exact ground truth, so a change to the transcriber gets a NUMBER rather than
an opinion. Scores are pinned in tests/regression/baselines.json; a change
that moves them must say so explicitly and explain why (CLAUDE.md).

Deviation from plan §6 worth knowing: these do not run in CI. Layer 1 was
specced before CREPE was the tracker, and CI deliberately does not install
the ml group (a ~200MB torch download plus minutes of inference per commit).
They are gated behind SWINGSCRIBE_HEAVY_TESTS=1 and run locally instead. The
pure-function tests in test_transcribe.py *do* run on every commit.
"""

import json
from pathlib import Path

import pytest

from conftest import requires_heavy
from swingscribe.config import Config
from swingscribe.metrics import notes_to_frames, score_frames, score_notes
from swingscribe.stages import transcribe
from synthetic import generate, soundfont

# Soundfont cases need a 32MB bank and the FluidSynth CLI, neither of which is
# committed (plan §12) and neither of which CI has. They skip rather than fail.
requires_soundfont = pytest.mark.skipif(
    not soundfont.available(), reason=soundfont.missing_reason()
)

BASELINES_PATH = Path(__file__).parent / "regression" / "baselines.json"
# How far below a pinned baseline a score may drift before the test fails.
# Tight enough to catch a regression, loose enough to absorb CPU nondeterminism.
TOLERANCE = 0.05


def load_baselines() -> dict:
    return json.loads(BASELINES_PATH.read_text(encoding="utf-8"))


def transcribe_signal(tmp_path, signal, name="case", **config_overrides):
    """Render → transcribe → (estimated notes, frame diagnostics)."""
    stem = tmp_path / f"{name}.wav"
    generate.write_wav(stem, signal)
    tc = Config().transcribe.model_copy(update=config_overrides)
    return transcribe.analyze(str(stem), tc)


_LINE = generate.phrase([57, 60, 64, 62, 59, 55])
_HELD = generate.held_note_phrase()
# Bebop-speed: 130ms notes, near the 60ms floor. Guards the opposite failure
# from open-issue #1 — onset corroboration must not MERGE fast repeated notes.
_FAST = generate.phrase([57, 59, 60, 62, 64, 62, 60, 59], note_duration=0.13, gap=0.02)

# Comping is rendered at -3dB rather than something politer because at -6dB it
# does not trigger the bug it exists to test: with corroboration disabled the
# held note shatters into 4 (onset F1 0.40) at -3dB, and survives at -6dB. A
# case that passes whether or not the code is correct measures nothing.
COMPING_DB = -3.0
# Sampled comping is a much stronger competitor than sine chords at the same
# nominal level — a real piano chord is broadband and transient where three
# sines are neither. -12dB is the loudest the soundfont held-note case stays
# intact at (see the sweep beside held_note_over_quiet_comping), so it is the
# level at which a floor is worth pinning.
QUIET_COMPING_DB = -12.0

CASES: dict[str, dict] = {
    "clean_line": {"notes": _LINE, "render": {}},
    "vibrato": {
        "notes": generate.phrase([57, 60, 64, 62]),
        "render": {"vibrato_cents": 45.0},
    },
    "noisy": {
        "notes": generate.phrase([57, 60, 64, 62]),
        "render": {"noise_db": -34.0},
    },
    "held_note": {"notes": _HELD, "render": {}},
    "held_note_over_comping": {
        "notes": _HELD,
        "render": {
            "accompaniment": generate.comping_under(_HELD),
            "accompaniment_db": COMPING_DB,
        },
    },
    "line_over_comping": {
        "notes": _LINE,
        "render": {
            "accompaniment": generate.comping_under(_LINE),
            "accompaniment_db": COMPING_DB,
        },
    },
    "fast_line": {"notes": _FAST, "render": {}},
    "fast_line_over_comping": {
        "notes": _FAST,
        "render": {
            "accompaniment": generate.comping_under(_FAST),
            "accompaniment_db": COMPING_DB,
        },
    },
}


# ── Soundfont cases (plan §6, open-issue #4) ────────────────────────────
#
# The additive cases above all score ≥0.98, which makes them a regression
# guard and not a quality measure. These render the SAME ground truth through
# a sampled tenor sax, so any score difference is attributable to timbre
# alone — breath noise, a moving harmonic series, real attacks and release
# tails. Their baselines live in a separate "synthetic_soundfont" section
# precisely because they are expected to be lower: mixing them into the
# additive numbers would hide both.
SOUNDFONT_CASES: dict[str, dict] = {
    "clean_line": {"notes": _LINE, "render": {}},
    "held_note": {"notes": _HELD, "render": {}},
    # The direct mirror of the additive case, at the same -3dB. It scores
    # ZERO, and that is the measurement, not a bug in the harness: a sampled
    # piano at -3dB under a sampled sax pulls CREPE off the melody outright,
    # where sine chords at the same level never did. Its baseline is a record
    # of where we are, not a floor worth defending — see
    # `held_note_over_quiet_comping` for the floor.
    "held_note_over_comping": {
        "notes": _HELD,
        "render": {
            "accompaniment": generate.comping_under(_HELD),
            "accompaniment_db": COMPING_DB,
        },
    },
    # The same case at a level where onset corroboration still holds. Measured
    # sweep of the held note under sampled comping (frame pitch accuracy /
    # notes estimated against 1 in the truth):
    #     -3dB 0.66/4   -6dB 0.79/3   -9dB 0.95/2   -12dB 0.97/1   -18dB 0.98/1
    # The additive renderer scores 1.000/1 at every one of those levels, so
    # this is the first synthetic case with any dynamic range at all.
    "held_note_over_quiet_comping": {
        "notes": _HELD,
        "render": {
            "accompaniment": generate.comping_under(_HELD),
            "accompaniment_db": QUIET_COMPING_DB,
        },
    },
    "fast_line": {"notes": _FAST, "render": {}},
    # Mod wheel drives the GM vibrato LFO, so this is the patch's own wobble
    # rather than a frequency modulation we imposed — a closer analogue of
    # what a player does than generate.render's vibrato_cents.
    "vibrato": {
        "notes": generate.phrase([57, 60, 64, 62]),
        "render": {"vibrato": 100},
    },
    # A second timbre family. Brass has a much stronger upper harmonic series
    # than a reed, and octave errors are the failure mode that costs us.
    "trumpet_line": {
        "notes": _LINE,
        "render": {"program": soundfont.TRUMPET},
    },
}


def _score_case(tmp_path, name: str, notes, signal) -> dict[str, float]:
    truth = generate.to_note_events(notes)
    estimate, diag = transcribe_signal(tmp_path, signal, name=name)

    scores = score_notes(truth, estimate)
    reference_hz = notes_to_frames(truth, diag.times)
    estimate_hz = [0.0 if p is None else 440.0 * 2.0 ** ((p - 69) / 12.0) for p in diag.pitch]
    scores.update(score_frames(reference_hz, estimate_hz, diag.times))
    return scores


def run_case(tmp_path, name: str) -> dict[str, float]:
    case = CASES[name]
    return _score_case(
        tmp_path, name, case["notes"], generate.render(case["notes"], **case["render"])
    )


def run_soundfont_case(tmp_path, name: str) -> dict[str, float]:
    case = SOUNDFONT_CASES[name]
    signal = soundfont.render(case["notes"], **case["render"])
    return _score_case(tmp_path, f"sf_{name}", case["notes"], signal)


def assert_meets_baseline(name: str, scores: dict[str, float], pinned: dict[str, float]) -> None:
    regressions = []
    for metric, expected in pinned.items():
        if metric.startswith(("n_", "voicing_false_alarm")):
            continue  # counts and false-alarm are informational, not floors
        actual = scores.get(metric)
        if actual is None:
            continue
        if actual < expected - TOLERANCE:
            regressions.append(f"{metric}: {actual:.3f} < {expected:.3f} - {TOLERANCE}")
    assert not regressions, f"{name} regressed:\n  " + "\n  ".join(regressions)


@requires_heavy
@pytest.mark.parametrize("name", sorted(CASES))
def test_scores_meet_baseline(tmp_path, name):
    baselines = load_baselines().get("synthetic", {})
    if name not in baselines:
        pytest.skip(f"no pinned baseline for {name!r} — run tools/pin_baselines.py")
    assert_meets_baseline(name, run_case(tmp_path, name), baselines[name])


@requires_heavy
@requires_soundfont
@pytest.mark.parametrize("name", sorted(SOUNDFONT_CASES))
def test_soundfont_scores_meet_baseline(tmp_path, name):
    baselines = load_baselines().get("synthetic_soundfont", {})
    if name not in baselines:
        pytest.skip(f"no pinned baseline for {name!r} — run tools/pin_baselines.py --soundfont")
    assert_meets_baseline(name, run_soundfont_case(tmp_path, name), baselines[name])


@requires_heavy
@requires_soundfont
def test_soundfont_is_harder_than_additive(tmp_path):
    """Guards the measurement, like test_the_suite_can_actually_see_the_bug:
    if a sampled sax ever scores as well as stacked sines, the soundfont path
    has stopped rendering what we think it renders and its baselines mean
    nothing. Frame pitch accuracy is the comparison — note counts move for
    segmentation reasons that are their own story."""
    additive = run_case(tmp_path, "clean_line")
    sampled = run_soundfont_case(tmp_path, "clean_line")
    assert sampled["raw_pitch_accuracy"] < additive["raw_pitch_accuracy"], (
        "the soundfont case is no harder than additive synthesis "
        f"({sampled['raw_pitch_accuracy']:.3f} vs {additive['raw_pitch_accuracy']:.3f}) — "
        "check that fluidsynth is actually rendering the sax patch"
    )


@requires_heavy
def test_comping_does_not_shatter_a_held_note(tmp_path):
    """Open-issue #1, measured rather than eyeballed: chords underneath a
    held note must not multiply the note count."""
    clean = run_case(tmp_path, "held_note")
    comped = run_case(tmp_path, "held_note_over_comping")
    assert comped["n_estimate"] <= clean["n_estimate"] + 2, (
        f"comping inflated the note count {clean['n_estimate']} -> {comped['n_estimate']}"
    )


@requires_heavy
@requires_soundfont
def test_sampled_comping_does_not_shatter_a_held_note(tmp_path):
    """The same guard with real instruments, at the level where the open-issue
    #1 fix actually holds. Deliberately NOT the -3dB case: at -3dB a sampled
    piano wins the frame outright and the held note becomes 4, which is a
    tracking failure rather than a segmentation one and is recorded in the
    baselines instead of asserted here."""
    comped = run_soundfont_case(tmp_path, "held_note_over_quiet_comping")
    assert comped["n_estimate"] <= 2, (
        f"sampled comping shattered the held note into {comped['n_estimate']:.0f}"
    )


@requires_heavy
def test_the_suite_can_actually_see_the_bug(tmp_path):
    """Guards the measurement, not the code: disabling onset corroboration
    must visibly wreck the held-note-over-comping score. If this ever passes
    trivially, the case has gone too easy and the baseline means nothing."""
    case = CASES["held_note_over_comping"]
    truth = generate.to_note_events(case["notes"])
    signal = generate.render(case["notes"], **case["render"])

    fixed, _ = transcribe_signal(tmp_path, signal, name="fixed", onset_rise_db=3.0)
    broken, _ = transcribe_signal(tmp_path, signal, name="broken", onset_rise_db=0.0)

    assert score_notes(truth, fixed)["onset_f1"] > score_notes(truth, broken)["onset_f1"] + 0.3


@requires_heavy
def test_corroboration_does_not_merge_fast_repeated_notes(tmp_path):
    """The opposite failure: requiring a harmonic attack must not swallow
    genuinely separate notes in a fast line."""
    scores = run_case(tmp_path, "fast_line")
    assert scores["n_estimate"] >= scores["n_reference"] - 1
    assert scores["onset_f1"] > 0.8


def test_generator_is_deterministic():
    # numpy is not in the default dependency closure — plain `uv sync`, and so
    # CI, installs neither it nor the ml group that pulls it in.
    pytest.importorskip("numpy")
    a = generate.render(generate.phrase([60, 62]), noise_db=-30.0)
    b = generate.render(generate.phrase([60, 62]), noise_db=-30.0)
    assert (a == b).all()


def test_ground_truth_matches_the_notes_asked_for():
    notes = generate.phrase([57, 60, 64])
    events = generate.to_note_events(notes)
    assert [e.pitch for e in events] == [57, 60, 64]
    assert all(e.confidence == 1.0 for e in events)


# ── Soundfont plumbing (no ml group, no soundfont needed) ───────────────


def test_soundfont_discovery_prefers_an_explicit_override(tmp_path, monkeypatch):
    fake = tmp_path / "fake.sf2"
    fake.write_bytes(b"sfbk")
    monkeypatch.setenv(soundfont.SOUNDFONT_ENV, str(fake))
    assert soundfont.find_soundfont() == str(fake)


def test_soundfont_discovery_rejects_an_override_that_is_not_there(tmp_path, monkeypatch):
    """A typo'd path must skip the tests, not silently fall back to a
    different soundfont — the scores would be from a bank nobody chose."""
    monkeypatch.setenv(soundfont.SOUNDFONT_ENV, str(tmp_path / "nope.sf2"))
    assert soundfont.find_soundfont() is None
    assert not soundfont.available()


def test_missing_reason_names_the_fix(monkeypatch, tmp_path):
    monkeypatch.setenv(soundfont.SOUNDFONT_ENV, str(tmp_path / "nope.sf2"))
    reason = soundfont.missing_reason()
    assert "setup_fixtures.py" in reason
    assert soundfont.SOUNDFONT_ENV in reason


def test_written_midi_is_the_ground_truth_verbatim(tmp_path):
    """The whole premise is that only the timbre changes, so the MIDI handed
    to fluidsynth must carry the answer key unmodified."""
    pretty_midi = pytest.importorskip("pretty_midi")
    notes = generate.phrase([57, 60, 64, 62])
    path = soundfont.write_midi(notes, tmp_path / "truth.mid", program=soundfont.TENOR_SAX)

    pm = pretty_midi.PrettyMIDI(path)
    (instrument,) = pm.instruments
    assert instrument.program == soundfont.TENOR_SAX
    assert [n.pitch for n in instrument.notes] == [n.pitch for n in notes]
    for written, truth in zip(instrument.notes, notes, strict=True):
        assert written.start == pytest.approx(truth.onset, abs=1e-3)
        assert written.end == pytest.approx(truth.onset + truth.duration, abs=1e-3)


def test_vibrato_is_written_as_a_mod_wheel_message(tmp_path):
    pretty_midi = pytest.importorskip("pretty_midi")
    path = soundfont.write_midi(generate.phrase([57]), tmp_path / "vib.mid", vibrato=100)
    (instrument,) = pretty_midi.PrettyMIDI(path).instruments
    assert [(cc.number, cc.value) for cc in instrument.control_changes] == [
        (soundfont.VIBRATO_CC, 100)
    ]


@requires_soundfont
def test_soundfont_render_is_the_expected_shape_and_rate(tmp_path):
    """Cheap enough to run without the heavy gate: it renders audio but never
    touches CREPE."""
    pytest.importorskip("soundfile")
    notes = generate.phrase([57, 60], note_duration=0.3)
    signal = soundfont.render(notes, program=soundfont.TENOR_SAX)
    expected = int(generate.SAMPLE_RATE * (notes[-1].onset + notes[-1].duration + 0.5))
    assert signal.shape == (expected,)
    assert signal.dtype == "float32"
    assert 0.6 < abs(signal).max() <= 0.7001  # peak-normalized, like generate.render


@requires_soundfont
def test_soundfont_render_actually_differs_from_additive(tmp_path):
    """Same notes, same length, different samples. If these ever matched, the
    soundfont path would be silently falling through to the sine renderer."""
    pytest.importorskip("soundfile")
    notes = generate.phrase([57, 60], note_duration=0.3)
    sampled = soundfont.render(notes)
    additive = generate.render(notes)
    assert sampled.shape == additive.shape
    assert not (sampled == additive).all()
