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
from synthetic import generate

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


def run_case(tmp_path, name: str) -> dict[str, float]:
    case = CASES[name]
    truth = generate.to_note_events(case["notes"])
    signal = generate.render(case["notes"], **case["render"])
    estimate, diag = transcribe_signal(tmp_path, signal, name=name)

    scores = score_notes(truth, estimate)
    reference_hz = notes_to_frames(truth, diag.times)
    estimate_hz = [0.0 if p is None else 440.0 * 2.0 ** ((p - 69) / 12.0) for p in diag.pitch]
    scores.update(score_frames(reference_hz, estimate_hz, diag.times))
    return scores


@requires_heavy
@pytest.mark.parametrize("name", sorted(CASES))
def test_scores_meet_baseline(tmp_path, name):
    baselines = load_baselines().get("synthetic", {})
    if name not in baselines:
        pytest.skip(f"no pinned baseline for {name!r} — run tools/pin_baselines.py")
    scores = run_case(tmp_path, name)
    pinned = baselines[name]
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
def test_comping_does_not_shatter_a_held_note(tmp_path):
    """Open-issue #1, measured rather than eyeballed: chords underneath a
    held note must not multiply the note count."""
    clean = run_case(tmp_path, "held_note")
    comped = run_case(tmp_path, "held_note_over_comping")
    assert comped["n_estimate"] <= clean["n_estimate"] + 2, (
        f"comping inflated the note count {clean['n_estimate']} -> {comped['n_estimate']}"
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
    a = generate.render(generate.phrase([60, 62]), noise_db=-30.0)
    b = generate.render(generate.phrase([60, 62]), noise_db=-30.0)
    assert (a == b).all()


def test_ground_truth_matches_the_notes_asked_for():
    notes = generate.phrase([57, 60, 64])
    events = generate.to_note_events(notes)
    assert [e.pitch for e in events] == [57, 60, 64]
    assert all(e.confidence == 1.0 for e in events)
