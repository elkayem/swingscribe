"""The triples instrument's pure parts: placing an annotated solo on a page,
naming what a page disagrees with, and counting written symbols.

Synthetic lines only -- the real triples are WJazzD (ODbL) and pages of
commercial recordings, which never enter the repo (docs/triples.md).
"""

import os
import random
import sys
from collections import Counter
from pathlib import Path

import pytest

from swingscribe.alignment import measured_transposition
from swingscribe.benchmark import score_notation
from swingscribe.model import NotatedBar, NotatedNote, Notation
from swingscribe.mscz import Score, ScoreNote
from swingscribe.triples import (
    CROP_MARGIN,
    POSITION_CLASSES,
    crop,
    decompose,
    disagreements,
    local_shifts,
    locate_solo,
    notation_symbols,
    page_symbols,
    place_name,
    position_class,
    value_name,
)

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _line(seed: int, count: int, low: int = 58, high: int = 82) -> list[int]:
    """A bebop-ish random walk: steps and small leaps in one register."""
    rng = random.Random(seed)
    pitch, out = 70, []
    for _ in range(count):
        step = rng.choice((-4, -3, -2, -1, 1, 2, 3, 5))
        # Reflected at the edges, so no two neighbours share a pitch.
        pitch = pitch + step if low <= pitch + step <= high else pitch - step
        out.append(pitch)
    return out


def _score(notes: list[tuple[float, float, int]], bars: int, beats: float = 4.0) -> Score:
    melody = [
        ScoreNote(position=p, duration=d, pitch=n, bar=int(p // beats) + 1) for p, d, n in notes
    ]
    return Score("synthetic", list(melody), melody, bars, beats, 0)


def _eighths(pitches: list[int], start: float) -> list[tuple[float, float, int]]:
    return [(start + 0.5 * i, 0.5, p) for i, p in enumerate(pitches)]


# ── placing the solo ─────────────────────────────────────────────────────────


def test_the_solo_is_found_after_the_head_on_a_tenor_page():
    """A page written for tenor (+14) opens with a head the annotation does
    not hold; the crop must be the solo's bars and nothing of the head."""
    head, solo = _line(1, 64), _line(2, 128)
    page = _score(
        [(p, d, n + 14) for p, d, n in _eighths(head, 0.0) + _eighths(solo, 32.0)], bars=24
    )
    # The annotation numbers from ITS bar 1, a pickup of two eighths before it.
    annotated = [(-1.0 + 0.5 * i, p) for i, p in enumerate(solo)]
    found = locate_solo(page, annotated)
    assert found["transposition"] == 14
    assert found["same_take"]
    assert found["coverage"] == pytest.approx(1.0)
    assert found["lo"] == pytest.approx(32.0 - CROP_MARGIN)
    assert found["hi"] == pytest.approx(32.0 + 0.5 * 127 + CROP_MARGIN)
    kept = crop(page, found["lo"], found["hi"])
    assert [n.pitch - 14 for n in kept.melody] == solo
    # Positions keep the page's origin, so its bar lines stay where it drew them.
    assert kept.melody[0].position == pytest.approx(32.0)


def test_another_take_of_the_same_tune_is_refused():
    """Two lines in one key and register share pitches by chance; they
    cannot share a clock, and do not cover each other."""
    page = _score(_eighths(_line(3, 128), 0.0), bars=16)
    other = [(0.5 * i, p) for i, p in enumerate(_line(4, 128))]
    found = locate_solo(page, other)
    assert not found["same_take"]
    assert found["coverage"] < 0.5


def test_a_bar_the_page_omits_moves_only_the_far_end():
    """The page drops bar 9 of the solo: the end of the window follows the
    last matches' clock, not the first's."""
    solo = _line(5, 128)
    notes = _eighths(solo, 0.0)
    # Remove the eight eighths of bar 9 (quarters 32-36) and close the gap.
    page_notes = [(p if p < 32 else p - 4.0, d, n) for p, d, n in notes if not 32 <= p < 36]
    page = _score(page_notes, bars=15)
    found = locate_solo(page, [(p, n) for p, _d, n in notes])
    assert found["same_take"]
    assert found["lo"] == pytest.approx(-CROP_MARGIN)
    assert found["hi"] == pytest.approx(63.5 - 4.0 + CROP_MARGIN)
    assert found["clock_share"] > 0.9


def test_local_shifts_follow_a_step():
    shifts = local_shifts([0.1] * 30 + [4.0] * 30)
    assert shifts[:10] == [0] * 10
    assert shifts[-10:] == [4] * 10


# ── naming the disagreements ─────────────────────────────────────────────────


def test_position_classes_name_what_a_reader_sees():
    assert position_class(4.0, 4.0) == "hit"
    assert position_class(4.0, 4.25) == "downbeat written on the e"
    assert position_class(4.0, 3.75) == "downbeat written on the a before"
    assert position_class(4.5, 4.75) == "offbeat written late (dotted figure)"
    assert position_class(4.5, 4.25) == "offbeat written early (sixteenth)"
    assert position_class(4.5, 5.0) == "offbeat written on a beat"
    assert position_class(4.0, 4.5) == "downbeat written on an and"
    assert position_class(4.75, 5.0) == "page sixteenth written on an eighth"
    assert position_class(4.25, 4.75) == "sixteenth moved"
    assert position_class(4 + 2 / 3, 4.5) == "triplet read binary"
    assert position_class(4.5, 4 + 2 / 3) == "binary read as triplet"
    assert position_class(4 + 1 / 3, 4 + 2 / 3) == "triplet moved"
    assert position_class(4.5, 4.625) == "a 32nd apart"
    assert position_class(4.2, 4.25) == "page finer than our lattice"
    assert position_class(4.0, 5.0) == "a beat or more apart"
    assert set(POSITION_CLASSES) >= {position_class(4.0, x / 24) for x in range(96, 120)}


def test_names_for_places_and_lengths():
    assert place_name(7.0) == "beat"
    assert place_name(7.25) == "e"
    assert place_name(7.5) == "and"
    assert place_name(7 + 2 / 3) == "2/3"
    assert place_name(7.2) == "off the lattice"
    assert value_name(0.75) == "eighth."
    assert value_name(1 / 3) == "triplet-8th"
    assert value_name(8.0) == "longer"


def _figures():
    """A page of eighth pairs, and our page with three kinds of mistake."""
    pitches = _line(6, 48)
    theirs = [(0.5 * i, 0.5, p) for i, p in enumerate(pitches)]
    ours = list(theirs)
    ours[8] = (4.25, 0.25, pitches[8])  # the downbeat on the e
    ours[7] = (3.5, 0.75, pitches[7])  # ... and the note before it grows a dot
    ours[13] = (6.75, 0.25, pitches[13])  # the offbeat as a dotted figure
    ours[12] = (6.0, 0.75, pitches[12])
    ours[20] = (10.0, 1.0, pitches[20])  # a note held where the page ...
    ours.pop(21)  # ... has one more note (missing on ours)
    return theirs, ours


def test_disagreements_agree_with_the_scorer_they_explain():
    theirs, ours = _figures()
    kinds = disagreements(ours, theirs)
    offset, aligned = measured_transposition([p for *_, p in theirs], [p for *_, p in ours])
    shifted = [(a, b, p + offset) for a, b, p in ours]
    scored = score_notation(theirs, shifted, aligned.pairs)
    assert kinds["rhythm"] == pytest.approx(scored["rhythm"])
    assert kinds["value"] == pytest.approx(scored["value"])
    assert kinds["matched"] == scored["n_matched"]


def test_disagreements_are_named_and_charged():
    theirs, ours = _figures()
    kinds = disagreements(ours, theirs)
    assert kinds["positions"]["downbeat written on the e"] == 1
    assert kinds["positions"]["offbeat written late (dotted figure)"] == 1
    assert kinds["missing"] == 1 and kinds["extra"] == 0
    # Each misplaced note makes two wrong gaps, both charged to its class.
    assert kinds["rhythm_blame"]["downbeat written on the e"] == 2
    assert kinds["rhythm_blame"]["offbeat written late (dotted figure)"] == 2
    assert kinds["intervals_wrong"] == 4
    # The dotted notes sit beside a moved note: rhythm wearing a value.
    assert kinds["values"]["beside a note or position that differs"] >= 2
    assert kinds["value_pairs"][("eighth.", "eighth")] == 2
    assert kinds["crosstab"][("beat", "e")] == 1
    assert len(kinds["per_note"]) == kinds["matched"]
    # Each match carries its class and both positions, on the page's clock.
    late = [n for n in kinds["per_note"] if n[2] == "downbeat written on the e"]
    assert [(page, ours) for *_i, _c, page, ours in late] == [(4.0, 4.25)]


def test_a_value_between_two_agreeing_notes_is_a_choice_of_length():
    pitches = _line(7, 16)
    theirs = [(1.0 * i, 1.0, p) for i, p in enumerate(pitches)]  # quarters
    ours = [(1.0 * i, 0.5, p) for i, p in enumerate(pitches)]  # eighth + eighth rest
    kinds = disagreements(ours, theirs)
    assert kinds["rhythm"] == 1.0
    assert kinds["values"]["we rest where the page holds"] == 15
    assert kinds["values"]["last note"] == 1
    reverse = disagreements(theirs, ours)
    assert reverse["values"]["we hold where the page rests"] == 15


def test_a_page_a_bar_behind_reads_as_one_slip_not_as_every_note_wrong():
    pitches = _line(8, 64)
    theirs = [(0.5 * i, 0.5, p) for i, p in enumerate(pitches)]
    ours = [(0.5 * i + (4.0 if i >= 32 else 0.0), 0.5, p) for i, p in enumerate(pitches)]
    kinds = disagreements(ours, theirs)
    assert kinds["positions"]["hit"] == 64
    assert kinds["rhythm_blame"]["a beat or more apart"] == 1


def test_nothing_to_compare_is_empty_not_a_crash():
    kinds = disagreements([], [(0.0, 0.5, 60)])
    assert kinds["matched"] == 0 and kinds["missing"] == 1


# ── written symbols ──────────────────────────────────────────────────────────


def test_our_symbols_are_counted_over_the_sounding_bars():
    third = 1 / 3
    notation = Notation(
        bars=[
            NotatedBar(
                number=0,
                time_signature=(4, 4),
                notes=[NotatedNote(beat=0, duration=4, is_rest=True)],
            ),
            NotatedBar(
                number=1,
                time_signature=(4, 4),
                notes=[
                    NotatedNote(beat=0, duration=0.5, is_rest=True),
                    NotatedNote(beat=0.5, duration=0.75, pitch=60),
                    NotatedNote(beat=1.25, duration=0.25, pitch=62, tie_start=True),
                    NotatedNote(beat=1.5, duration=0.5, pitch=62, tie_stop=True),
                    NotatedNote(beat=2, duration=third, pitch=64, tuplet=(3, 2)),
                    NotatedNote(beat=2 + third, duration=third, pitch=65, tuplet=(3, 2)),
                    NotatedNote(beat=2 + 2 * third, duration=third, pitch=67, tuplet=(3, 2)),
                    NotatedNote(beat=3, duration=0.25, is_rest=True),
                    NotatedNote(beat=3.25, duration=0.75, pitch=69, voice=2),
                ],
            ),
            NotatedBar(
                number=2,
                time_signature=(4, 4),
                notes=[NotatedNote(beat=0, duration=4, is_rest=True)],
            ),
        ]
    )
    symbols = notation_symbols(notation)
    assert symbols["notes"] == 6
    assert symbols["rests"] == 2
    assert symbols["tie_starts"] == 1
    assert symbols["tuplet_notes"] == 3
    assert symbols["dotted_notes"] == 1
    assert symbols["sub_eighth_rests"] == 1
    assert symbols["rest_kinds"] == Counter({"eighth": 1, "16th": 1})


def _xml_note(inner: str, voice: int = 1, duration: int | None = None) -> str:
    length = f"<duration>{duration}</duration>" if duration is not None else ""
    return f"<note>{inner}{length}<voice>{voice}</voice></note>"


def _pitch(step: str, octave: int = 5) -> str:
    return f"<pitch><step>{step}</step><octave>{octave}</octave></pitch>"


TRIPLET = (
    "<time-modification><actual-notes>3</actual-notes>"
    "<normal-notes>2</normal-notes></time-modification>"
)
PAGE = (
    '<?xml version="1.0"?><score-partwise><part id="P1">'
    '<measure number="1">'
    + _xml_note("<rest/><type>whole</type>", duration=4)
    + '</measure><measure number="2">'
    + _xml_note("<rest/><type>eighth</type>", duration=1)
    + _xml_note(_pitch("C") + "<type>eighth</type><dot/>", duration=3)
    + _xml_note(_pitch("E") + "<type>eighth</type><dot/><chord/>", duration=3)
    + _xml_note("<grace/>" + _pitch("F") + "<type>16th</type>")
    + _xml_note(_pitch("D") + '<type>16th</type><tie type="start"/>', duration=1)
    + _xml_note(_pitch("D") + '<type>eighth</type><tie type="stop"/>', duration=2)
    + _xml_note(_pitch("E") + "<type>eighth</type>" + TRIPLET, duration=1)
    + _xml_note("<rest/><type>16th</type>", duration=1)
    + _xml_note(_pitch("G", 4) + "<type>quarter</type>", voice=2, duration=2)
    + '</measure><measure number="3">'
    + _xml_note('<rest measure="yes"/>', duration=4)
    + "</measure></part></score-partwise>"
)


def test_page_symbols_read_the_page_the_same_way(tmp_path):
    path = tmp_path / "page.musicxml"
    path.write_text(PAGE, encoding="utf-8")
    symbols = page_symbols(path, 2, 3)
    assert symbols["notes"] == 4  # the chord tone, the grace note and voice 2 left out
    assert symbols["rests"] == 3
    assert symbols["tie_starts"] == 1
    assert symbols["tuplet_notes"] == 1
    assert symbols["dotted_notes"] == 1
    assert symbols["sub_eighth_rests"] == 1
    assert symbols["rest_kinds"] == Counter({"eighth": 1, "16th": 1, "whole bar": 1})
    assert page_symbols(path, 1, 1)["rests"] == 1


def test_the_three_parts_add_up_to_the_whole_distance():
    a = {"rhythm": 0.8, "value": 0.7}
    b = {"rhythm": 0.75, "value": 0.72}
    c = {"rhythm": 0.7, "value": 0.6}
    parts = decompose(a, b, c)
    assert parts["rhythm"]["writing"] == pytest.approx(0.2)
    assert parts["rhythm"]["grid"] == pytest.approx(0.05)
    assert parts["rhythm"]["hearing"] == pytest.approx(0.05)
    assert parts["value"]["grid"] == pytest.approx(-0.02)
    for field in parts.values():
        assert field["writing"] + field["grid"] + field["hearing"] == pytest.approx(field["total"])
    assert "coverage" not in parts


# ── the script's bookkeeping ─────────────────────────────────────────────────


def _script():
    sys.path.insert(0, str(SCRIPTS))
    return pytest.importorskip("triples", reason="scripts/triples.py")


def test_the_script_writes_aggregates_only():
    script = _script()
    theirs, ours = _figures()
    kinds = disagreements(ours, theirs)
    result = {
        "name": "x",
        "phases": {"hit": [(0.5, 2)]},
        "page_symbols": {"notes": 1, "rest_kinds": Counter({"eighth": 1})},
        "inputs": {
            "a": {
                "rhythm": 0.9,
                "value": 0.8,
                "coverage": 0.9,
                "on_the_bar": 0.9,
                "beat_offset": 0.0,
                "n_matched": 10.0,
                "written": 10,
                "kinds": kinds,
                "symbols": {"notes": 1, "rest_kinds": Counter()},
            }
        },
    }
    out = script.aggregate_only(result)
    assert "phases" not in out
    assert "per_note" not in out["inputs"]["a"]["kinds"]
    assert out["inputs"]["a"]["kinds"]["crosstab"]["beat -> e"] == 1
    names = [t[0] for t in script.TRIPLES] + [c[0] for c in script.CONTROLS]
    assert len(names) == len(set(names))


def test_an_override_is_undone_after_the_run():
    script = _script()
    key = "SWINGSCRIBE_QUANTIZE__FIGURE_PRIOR_WEIGHT"
    before = os.environ.get(key)
    with script.environment({key: "0"}):
        assert os.environ[key] == "0"
    assert os.environ.get(key) == before
