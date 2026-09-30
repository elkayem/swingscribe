"""The Rhythm Perceiver's beat signature (swingscribe.beat_signature), on lines
small enough to tokenize by hand, and the script's corpus count on one
synthetic MusicXML page.

Pure arithmetic and the standard library, like the module: runs in CI. The
script's bootstrap summaries need numpy and are not exercised here.
"""

import importlib.util
import sys
from collections import Counter
from pathlib import Path

import pytest

from swingscribe import beat_signature as bs
from swingscribe.model import NotatedBar, NotatedNote, Notation
from swingscribe.mscz import Score, ScoreNote

EIGHTHS = "OTTTTTOTTTTT"
TRIPLET = "OTTTOTTTOTTT"
QUARTER = "OTTTTTTTTTTT"
HELD = "TTTTTTTTTTTT"
REST = "RRRRRRRRRRRR"


def sig(notes, beat=0, onsets_only=False):
    return bs.beat_signature(bs.line_events(notes), beat, onsets_only)


# ── the tokens ──────────────────────────────────────────────────────────────


def test_common_figures_tokenize_as_the_paper_draws_them():
    assert sig([(0, 0.5), (0.5, 0.5)]) == EIGHTHS
    third = 1 / 3  # a float, as a triplet arrives
    assert sig([(0, third), (third, third), (2 * third, third)]) == TRIPLET
    assert sig([(0, 1)]) == QUARTER
    assert sig([(0, 0.25), (0.25, 0.25), (0.5, 0.25), (0.75, 0.25)]) == "OTTOTTOTTOTT"
    # The sixteenth-triplet turn and an eighth (the paper's Confirmation example).
    sixth = 1 / 6
    assert sig([(0, sixth), (sixth, sixth), (2 * sixth, sixth), (0.5, 0.5)]) == "OTOTOTOTTTTT"


def test_rests_ties_and_notes_held_across_the_beat():
    assert sig([(0, 0.5)]) == "OTTTTTRRRRRR"  # an eighth and an eighth rest
    assert sig([(0.5, 0.5)]) == "RRRRRROTTTTT"
    assert sig([], 3) == REST
    # A dotted quarter from beat 0: beat 1 opens on the held half, then rests.
    line = [(0, 1.5), (2, 1)]
    assert sig(line, 0) == QUARTER
    assert sig(line, 1) == "TTTTTTRRRRRR"
    # A note tied over the beat line and an eighth after it.
    assert sig([(0, 1.5), (1.5, 0.5)], 1) == "TTTTTTOTTTTT"
    assert sig([(0, 4)], 2) == HELD


def test_a_chord_is_one_onset_and_a_held_note_ends_at_the_next():
    events = bs.line_events([(0, 0.5), (0, 1.0), (0.5, 0.5)])
    assert events == [(0.0, 0.5), (0.5, 1.0)]
    assert bs.beat_signature(events, 0) == EIGHTHS


def test_what_twelve_bins_cannot_hold_is_unsupported():
    # A 32nd (1.5 bins) and a dotted sixteenth (4.5 bins).
    assert sig([(0, 0.125), (0.125, 0.875)]) == bs.UNSUPPORTED
    assert sig([(0, 0.125), (0.125, 0.875)], onsets_only=True) == bs.UNSUPPORTED
    # Only the END is off the bins: the onset pattern is still readable.
    dotted = [(0, 0.375), (0.5, 0.5)]
    assert sig(dotted) == bs.UNSUPPORTED
    assert sig(dotted, onsets_only=True) == "O-----O-----"
    # A quintuplet.
    assert sig([(i / 5, 0.2) for i in range(5)]) == bs.UNSUPPORTED
    # ...and a note ending off the bins in the NEXT beat spoils that beat.
    assert sig([(0.75, 0.375)], 1) == bs.UNSUPPORTED
    assert sig([(0.75, 0.375)], 0) == "RRRRRRRRROTT"


def test_bar_events_read_a_filled_bar_with_a_tie_in_and_rests():
    # Tied in to beat 1, rest on the "and" of 2, notes on 2 1/2 .. 4.
    events = bs.bar_events(4, [1.5, 3], [(1, 0.5)])
    assert events == [(-1.0, 1.0), (1.5, 3.0), (3.0, 4.0)]
    assert bs.beat_signature(events, 0) == HELD
    assert bs.beat_signature(events, 1) == "RRRRRROTTTTT"
    assert bs.beat_signature(events, 3) == QUARTER
    assert bs.bar_events(4, [0, 2], [(3, 1)]) == [(0.0, 2.0), (2.0, 3.0)]


def test_classes_and_inventory():
    counts = Counter({EIGHTHS: 50, QUARTER: 40, REST: 40, TRIPLET: 5, bs.UNSUPPORTED: 99})
    inventory = bs.build_inventory(counts, classes=3)
    assert inventory == frozenset({EIGHTHS, QUARTER, REST})
    assert bs.signature_class(TRIPLET, inventory) == bs.RARE
    assert bs.signature_class(bs.UNSUPPORTED, inventory) == bs.UNSUPPORTED
    assert bs.signature_class(TRIPLET, None) == TRIPLET


def test_describe_and_onset_pattern():
    assert bs.describe(EIGHTHS) == "8 8"
    assert bs.describe(TRIPLET) == "8t 8t 8t"
    assert bs.describe("TTTTTTOTTTTT") == "~8 8"
    assert bs.describe("RRRRRROTTTTT") == "r8 8"
    assert bs.describe("OTTTTTTTTOTT") == "8. 16"
    assert bs.describe("OTTTTOTTTTTT") == "5/12 7/12"
    assert bs.describe(bs.UNSUPPORTED) == bs.UNSUPPORTED
    assert bs.onset_pattern("OTTTTTRRRRRR") == "O-----------"
    assert bs.onset_pattern(bs.UNSUPPORTED) == bs.UNSUPPORTED


# ── pairing and scoring ─────────────────────────────────────────────────────

# A line whose pitches never repeat in a short window, so the alignment is
# unambiguous: eighth pairs, a quarter every fourth beat.
PITCHES = [60, 62, 64, 65, 67, 69, 71, 72, 74, 72, 71, 69, 67, 65, 64, 62, 61, 63, 66, 68]


def line(beats: int, shift: float = 0.0) -> list[tuple[float, float, int]]:
    out = []
    k = 0
    for beat in range(beats):
        if beat % 4 == 3:
            out.append((beat + shift, 1.0, PITCHES[k % len(PITCHES)]))
            k += 1
            continue
        for half in (0.0, 0.5):
            out.append((beat + half + shift, 0.5, PITCHES[k % len(PITCHES)]))
            k += 1
    return out


def test_an_identical_page_four_beats_later_scores_one():
    theirs = line(40)
    ours = line(40, shift=4.0)  # our bar 1 is their bar 2: a whole bar of pickup
    result = bs.accuracy(ours, theirs)
    assert result["shift"] == 4
    assert result["clock_share"] == 1.0
    for view in bs.VIEWS:
        assert result[view]["accuracy"] == 1.0
        assert result[view]["beats"] == 40
    assert result["onset_f1"]["f1"] == 1.0


def test_a_slipped_beat_costs_only_its_neighbourhood_when_paired_locally():
    theirs = line(64)
    # Our grid dropped a beat at beat 32: every note after it sits one beat
    # early on our page.
    ours = [(p - 1.0 if p >= 32 else p, d, n) for p, d, n in theirs]
    local = bs.accuracy(ours, theirs, local=True)
    strict = bs.accuracy(ours, theirs, local=False)
    assert local["clock_share"] < 1.0
    assert local["exact"]["accuracy"] > 0.9
    # One commonest shift for the whole page: half the page compared a beat off.
    assert strict["exact"]["accuracy"] < 0.8


def test_a_value_is_wrong_in_the_full_view_and_right_in_the_onset_view():
    theirs = line(40)
    # Every quarter written as an eighth and an eighth rest.
    ours = [(p, 0.5 if d == 1.0 else d, n) for p, d, n in theirs]
    result = bs.accuracy(ours, theirs)
    assert result["exact"]["accuracy"] == pytest.approx(30 / 40)
    assert result["onsets"]["accuracy"] == 1.0
    assert result["onset_f1"]["f1"] == 1.0
    wrong = {pair: n for pair, n in result["exact"]["confusion"].items() if pair[0] != pair[1]}
    assert wrong == {(QUARTER, "OTTTTTRRRRRR"): 10}


def test_a_triplet_read_as_eighths_is_one_wrong_beat():
    theirs = line(40)
    third = 1 / 3
    # Beat 5 becomes a triplet on the reference; we still write two eighths.
    theirs = [n for n in theirs if not 5 <= n[0] < 6] + [
        (5.0, third, 50),
        (5 + third, third, 51),
        (5 + 2 * third, third, 52),
    ]
    theirs.sort()
    ours = line(40)
    result = bs.accuracy(ours, theirs)
    assert result["exact"]["beats"] == 40
    assert result["exact"]["correct"] == 39
    assert result["exact"]["confusion"][(TRIPLET, EIGHTHS)] == 1
    counts = result["onset_f1"]
    assert (counts["tp"], counts["ours"], counts["theirs"]) == (69, 70, 71)


def test_rare_classes_agree_as_rare():
    theirs = [(0.0, 5 / 12, 60), (5 / 12, 7 / 12, 62), (1.0, 1.0, 64), (2.0, 1.0, 65)]
    ours = [(0.0, 1 / 12, 60), (1 / 12, 11 / 12, 62), (1.0, 1.0, 64), (2.0, 1.0, 65)]
    inventory = frozenset({QUARTER})
    result = bs.accuracy(ours, theirs, inventory)
    assert result["exact"]["correct"] == 2
    assert result["classes"]["correct"] == 3


def test_against_a_score_and_against_a_notation():
    notes = [
        NotatedNote(beat=0.0, duration=0.5, pitch=60),
        NotatedNote(beat=0.5, duration=0.5, pitch=62),
        NotatedNote(beat=1.0, duration=1.0, pitch=64),
        NotatedNote(beat=2.0, duration=0.5, pitch=65),
        NotatedNote(beat=2.5, duration=0.5, is_rest=True),
        NotatedNote(beat=3.0, duration=1.0, pitch=67, tie_start=True),
    ]
    bars = [
        NotatedBar(number=1, time_signature=(4, 4), notes=notes),
        NotatedBar(
            number=2,
            time_signature=(4, 4),
            notes=[
                NotatedNote(beat=0.0, duration=1.0, pitch=67, tie_stop=True),
                NotatedNote(beat=1.0, duration=3.0, pitch=69),
            ],
        ),
    ]
    ours = Notation(bars=bars)
    melody = [
        ScoreNote(position=0.0, duration=0.5, pitch=60, bar=1),
        ScoreNote(position=0.5, duration=0.5, pitch=62, bar=1),
        ScoreNote(position=1.0, duration=1.0, pitch=64, bar=1),
        ScoreNote(position=2.0, duration=0.5, pitch=65, bar=1),
        ScoreNote(position=3.0, duration=2.0, pitch=67, bar=1),
        ScoreNote(position=5.0, duration=3.0, pitch=69, bar=2),
    ]
    score = Score("t", melody, melody, 2, 4.0, 0)
    result = bs.against_score(ours, score)
    assert result["exact"]["beats"] == 6  # the first matched note to the last
    assert result["exact"]["accuracy"] == 1.0
    assert bs.against_notation(ours, ours)["exact"]["accuracy"] == 1.0
    # The tied pair is one note: beat 4 (the second bar's downbeat) is held.
    events = bs.line_events([(p, d) for p, d, _ in bs.notation_rhythm(ours)])
    assert bs.beat_signature(events, 4) == HELD


def test_double_time_pages_are_read_in_true_quarters():
    bar = NotatedBar(
        number=1,
        time_signature=(4, 4),
        notes=[NotatedNote(beat=float(i), duration=1.0, pitch=60 + i) for i in range(4)],
    )
    page = Notation(bars=[bar], double_time=True)
    rhythm = bs.notation_rhythm(page)
    assert [p for p, _, _ in rhythm] == [0.0, 0.5, 1.0, 1.5]
    events = bs.line_events([(p, d) for p, d, _ in rhythm])
    assert bs.beat_signature(events, 0) == EIGHTHS


# ── the script's corpus count ───────────────────────────────────────────────

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def load_script():
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(
        "beat_signature_script", SCRIPTS / "beat_signature.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["beat_signature_script"] = module
    spec.loader.exec_module(module)
    return module


def xml_note(step, duration, kind, *extra):
    return (
        f"<note><pitch><step>{step}</step><octave>4</octave></pitch>"
        f"<duration>{duration}</duration><voice>1</voice><type>{kind}</type>{''.join(extra)}</note>"
    )


def xml_rest(duration, kind):
    return f"<note><rest/><duration>{duration}</duration><voice>1</voice><type>{kind}</type></note>"


PAGE = f"""<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
  <part-list><score-part id="P1"><part-name>Alto</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>2</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
      {xml_note("C", 1, "eighth")}{xml_note("D", 1, "eighth")}
      {xml_note("E", 2, "quarter")}
      {xml_rest(1, "eighth")}{xml_note("F", 1, "eighth")}
      {xml_note("G", 2, "quarter", '<tie type="start"/>')}
    </measure>
    <measure number="2">
      {xml_note("G", 1, "eighth", '<tie type="stop"/>')}{xml_note("A", 1, "eighth")}
      {xml_rest(6, "half")}
    </measure>
    <measure number="3">
      {xml_note("C", 1, "eighth")}{xml_note("D", 1, "eighth")}
    </measure>
  </part>
</score-partwise>
"""


def test_the_corpus_count_reads_filled_bars_only(tmp_path):
    script = load_script()
    (tmp_path / "Tune - Player Solo.musicxml").write_text(PAGE, encoding="utf-8")
    counts, stats = script.corpus_counts(tmp_path, tmp_path / "no-split.json")
    # Bar 3 does not fill its signature and is left out, as the prior does.
    assert stats["pages"] == 1
    assert stats["beats"] == 8
    assert counts == Counter(
        {
            EIGHTHS: 1,
            QUARTER: 2,  # beat 2, and beat 4 (the note tied over the bar line)
            "RRRRRROTTTTT": 1,
            "TTTTTTOTTTTT": 1,  # bar 2 opens on the tied-in half of that note
            REST: 3,
        }
    )


def test_confusion_tables_split_placement_from_value():
    script = load_script()
    rows = [
        {
            "confusion": {
                (EIGHTHS, EIGHTHS): 6,
                (QUARTER, "OTTTTTRRRRRR"): 3,  # a value only
                (TRIPLET, EIGHTHS): 1,  # placement
            }
        }
    ]
    table = script.confusion_tables(rows)
    assert table["beats"] == 10
    assert table["wrong"] == 4
    assert table["wrong_onsets_right"] == pytest.approx(0.75)
    assert table["figures"][0]["signature"] == EIGHTHS
    assert table["figures"][0]["right"] == 1.0
