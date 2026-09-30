"""The benchmark's bookkeeping (swingscribe.evaluation, docs/roadmap.md E1-E3,
E5, E6).

What the harness asks about its scores: is a change more than noise, may a
track be looked at, how far a reference page can be trusted (and whether a
bar-line step is the page's), does confidence point at the errors, and what a
mean is made of. Pure arithmetic and hashing, so all of it runs in CI -- all
but `note_hits`, which asks mir_eval, and `paired_change`, which resamples
with numpy: CI installs neither, and their tests skip there.
"""

import json
import math

import pytest

from swingscribe.evaluation import (
    SILVER_MAX_UNREAD,
    SILVER_MIN_FILLED,
    Split,
    load_split,
    normalize_title,
    page_group,
    page_tier,
    paired_change,
    sign_test,
)

# ── is a change real ─────────────────────────────────────────────────────────


def test_sign_test_matches_the_binomial_by_hand():
    # 7 of 12 up: P(X <= 5) for Binomial(12, 1/2) is 1586/4096, doubled.
    assert sign_test(7, 5) == pytest.approx(2 * 1586 / 4096)
    assert sign_test(12, 0) == pytest.approx(2 / 4096)
    assert sign_test(0, 0) == 1.0
    assert sign_test(3, 3) == 1.0  # capped, never above one
    assert sign_test(5, 7) == sign_test(7, 5)


def _needs_numpy():
    """`paired_change` resamples with numpy, which CI does not install (the
    core dependencies are pydantic and pyyaml); these tests skip there."""
    pytest.importorskip("numpy")


def test_a_noisy_small_change_is_not_decided():
    _needs_numpy()
    # R33's shape: a small mean rise with 7 pages up and 5 down.
    before = [0.80] * 12
    after = [0.83, 0.82, 0.84, 0.81, 0.83, 0.82, 0.83, 0.78, 0.79, 0.77, 0.79, 0.78]
    c = paired_change(before, after, tolerance=0.002)
    assert (c.up, c.down, c.level) == (7, 5, 0)
    assert c.low < 0.0 < c.high
    assert not c.decided
    assert c.p == pytest.approx(sign_test(7, 5))


def test_a_consistent_change_is_decided_and_the_interval_brackets_the_mean():
    _needs_numpy()
    before = [0.5 + 0.01 * i for i in range(20)]
    after = [b + 0.02 + 0.001 * (i % 3) for i, b in enumerate(before)]
    c = paired_change(before, after)
    assert c.decided
    assert c.low <= c.mean <= c.high
    assert c.up == 20 and c.down == 0
    assert c.p < 1e-5


def test_the_interval_resamples_recordings_not_tracks():
    _needs_numpy()
    # Ten solos on one recording moved together; twenty others, one per
    # recording, wobbled. As thirty independent tracks the interval is
    # narrow; as 21 recordings, one of which carries all the change, it is
    # much wider -- the change rests on one recording, and the interval says so.
    before = [0.5] * 30
    after = [0.6] * 10 + [0.51 if i % 2 else 0.49 for i in range(20)]
    labels = ["a"] * 10 + [f"r{i}" for i in range(20)]
    flat = paired_change(before, after)
    clustered = paired_change(before, after, labels, tolerance=0.002)
    assert clustered.recordings == 21 and flat.recordings == 30
    assert clustered.high - clustered.low > 1.5 * (flat.high - flat.low)
    assert flat.decided and not clustered.decided
    # The sign test counts the recording once.
    assert (clustered.up, clustered.down) == (11, 10)
    # And the point estimate is still the mean over TRACKS, as the card prints.
    assert clustered.mean == pytest.approx(1.0 / 30)


def test_the_same_inputs_give_the_same_interval():
    _needs_numpy()
    before = [0.1, 0.4, 0.3, 0.9, 0.5]
    after = [0.2, 0.3, 0.35, 0.95, 0.4]
    assert paired_change(before, after) == paired_change(before, after)


def test_paired_change_refuses_what_it_cannot_pair():
    _needs_numpy()
    with pytest.raises(ValueError):
        paired_change([0.1], [0.1, 0.2])
    with pytest.raises(ValueError):
        paired_change([], [])
    with pytest.raises(ValueError):
        paired_change([0.1, 0.2], [0.1, 0.2], ["only one"])


# ── may this track be looked at ──────────────────────────────────────────────


def test_titles_normalise_across_spellings():
    assert normalize_title("Star Dust") == normalize_title("STAR-DUST") == "stardust"
    assert normalize_title("Moody's Mood for Love") == "moodysmoodforlove"
    assert normalize_title("Moody’s Mood for Love") == "moodysmoodforlove"
    assert normalize_title("  ") == ""


def test_the_split_is_stable_grandfathers_dev_and_holds_out_about_its_share():
    split = Split(salt="s", test_share=0.3, dev=frozenset({"bodyandsoul"}))
    titles = [f"tune number {i}" for i in range(2000)]
    held = [t for t in titles if split.is_test(t)]
    assert 0.26 < len(held) / len(titles) < 0.34
    # Deterministic, and blind to spelling.
    assert [split.is_test(t) for t in titles[:50]] == [split.is_test(t) for t in titles[:50]]
    assert split.is_test("Tune Number 7") == split.is_test("tune-number-7")
    # A tune already in the benchmark is dev whatever its hash says.
    assert not split.is_test("Body and Soul")
    assert not split.is_test("")
    # Another salt is another split.
    other = Split(salt="t", test_share=0.3, dev=frozenset())
    assert [split.is_test(t) for t in titles] != [other.is_test(t) for t in titles]


def test_load_split_normalises_the_frozen_list(tmp_path):
    path = tmp_path / "split.json"
    path.write_text(json.dumps({"salt": "x", "test_share": 0.25, "dev": ["Star Dust"]}))
    split = load_split(path)
    assert split.dev == frozenset({"stardust"})
    assert split.test_share == 0.25
    assert not split.is_test("Stardust")


def test_the_committed_split_holds_the_benchmark_as_dev():
    # The frozen file is the source of truth; these are tracks that were in
    # benchmark/ on the day it was frozen and must never turn into test.
    from pathlib import Path

    path = Path(__file__).resolve().parent / "regression" / "split.json"
    split = load_split(path)
    for title in ("Cheese Cake", "Joy Spring", "Embraceable You", "Au_Privave_1", "Blue Train"):
        assert not split.is_test(title), title
    assert 0.0 < split.test_share < 0.5


def test_a_page_is_grouped_by_the_title_on_it():
    title = page_group({"title": "Body and Soul"}, "Coleman-Hawkins-Body-and-Soul")
    assert title == "Body and Soul"
    assert page_group({"title": ""}, "Some-File") == "Some-File"
    assert page_group(None, "Some-File") == "Some-File"


# ── how good is the reference ────────────────────────────────────────────────


def entry(printed=500, unread=5, unprinted=2):
    return {"printed_noteheads": printed, "unread_printed": unread, "unprinted_read": unprinted}


def test_a_clean_vector_page_is_silver():
    assert page_tier(entry(), 0.97) == "silver"


def test_a_scan_is_bronze_however_its_bars_read():
    assert page_tier({"printed_noteheads": 0}, 1.0) == "bronze"
    assert page_tier({}, 1.0) == "bronze"
    assert page_tier(None, 1.0) == "bronze"


def test_each_silver_gate_can_fail_a_page_on_its_own():
    too_many_unread = math.ceil(500 * SILVER_MAX_UNREAD) + 1
    assert page_tier(entry(unread=too_many_unread), 0.99) == "bronze"
    assert page_tier(entry(unprinted=40), 0.99) == "bronze"
    assert page_tier(entry(), SILVER_MIN_FILLED - 0.01) == "bronze"
    assert page_tier(entry(), None) == "bronze"
    # The gates are inclusive.
    assert page_tier(entry(unread=25, unprinted=25), SILVER_MIN_FILLED) == "silver"


# ── is a bar-line step the page's ────────────────────────────────────────────


def _page(fills, bars=48):
    """A 4/4 page whose measure i (numbered from 1) holds fills.get(i, 4) beats."""
    from swingscribe.evaluation import page_bars

    return page_bars([(str(i), float(fills.get(i, 4)), 4.0) for i in range(1, bars + 1)])


def _heard(offset_at, fills, bars=48):
    """A synthetic page run through the REAL trace (`difference_trace`), with
    the matched notes it was built from: (trace, differences, page bars).

    Eight eighth notes to a bar of music. The page's reader places each at
    its bar's start as `_page(fills)` places it, so every note after an
    overfull bar sits later by its overrun, and a short bar holds only the
    notes that fit (on both sides). `offset_at(bar)` is where OUR page puts
    that bar of music, in beats: -1 from a bar on is a beat the grid
    dropped, +0.25 a phrase written a sixteenth late. A note that would land
    on or before the one before it is in the beat a dropped grid beat
    squeezed, and is left out of both sides.
    """
    import random

    from swingscribe.score_bars import _matched_differences, difference_trace

    rng = random.Random(0)
    ours, theirs = [], []
    for number, placed in enumerate(_page(fills, bars), start=1):
        for k in range(int(min(placed.filled, placed.length) / 0.5)):
            pitch = rng.randint(55, 79)
            position = 4.0 * (number - 1) + 0.5 * k + offset_at(number)
            if ours and position <= ours[-1][0]:
                continue
            ours.append((position, pitch))
            theirs.append((placed.start + 0.5 * k, pitch))
    trace = difference_trace(ours, theirs, 4.0)
    assert trace["steady"] and trace["matches"] == len(ours)
    return trace, _matched_differences(ours, theirs), _page(fills, bars)


def _runs(medians):
    """A trace of explicit runs, ten bars each, every matched note of run i at
    `medians[i]` and the run labelled as the trace would label it: for
    checking the verdict at a given residual, without a page to make it."""
    segments, differences = [], []
    for i, median in enumerate(medians):
        start = 40.0 * i
        positions = [start + 0.5 * k for k in range(80)]
        differences += [(p, median) for p in positions]
        segments.append(
            {"from": positions[0], "to": positions[-1], "offset": round(2 * median) / 2}
        )
    steps = [
        {
            "at": after["from"],
            "bar": int(after["from"] // 4) + 1,
            "change": after["offset"] - before["offset"],
        }
        for before, after in zip(segments, segments[1:], strict=False)
    ]
    return {"segments": segments, "steps": steps}, differences


def test_page_bars_are_placed_as_the_score_reader_places_them():
    """A short bar is padded to its signature and an overfull one keeps its
    beats (mscz.parse_musicxml), so the page's positions after bar 3 are two
    beats later than a full page's."""
    bars = _page({2: 3, 3: 6})
    assert [b.start for b in bars[:5]] == [0.0, 4.0, 8.0, 14.0, 18.0]
    assert not bars[1].fills and not bars[2].fills and bars[3].fills


def _xml_note(step, quarters, chord=False):
    return (
        f"<note>{'<chord/>' if chord else ''}<pitch><step>{step}</step><octave>4</octave>"
        f"</pitch><duration>{int(quarters * 2)}</duration></note>"
    )


def _xml_rest(quarters):
    return f"<note><rest/><duration>{int(quarters * 2)}</duration></note>"


def _xml_backup(quarters):
    return f"<backup><duration>{int(quarters * 2)}</duration></backup>"


def test_reader_bars_advance_where_the_score_reader_advances(tmp_path):
    """The step check must place the page's bars where `mscz.parse_musicxml`
    placed the notes the trace compared -- and that reader advances through
    a bar to where its LAST voice ends. Bar 2's first voice holds six beats
    and its last four: the reader moves nothing, though the fullest voice
    overruns (the figure prior's `filled` says 6, which would explain a step
    the reader never made). Bar 3's last voice holds six: that one moves every
    later note two beats. A chord tone and a rest behave as the reader has
    them, and a 3/4 bar is padded to three."""
    from swingscribe import mscz
    from swingscribe.evaluation import reader_bars

    bars = [
        _xml_note("C", 1) + _xml_note("E", 1, chord=True) + _xml_note("D", 1) + _xml_rest(2),
        _xml_note("E", 2) + _xml_note("F", 4) + _xml_backup(6) + _xml_note("G", 4),
        _xml_note("A", 4) + _xml_backup(4) + _xml_note("B", 6),
        "<attributes><time><beats>3</beats><beat-type>4</beat-type></time></attributes>"
        + _xml_note("C", 1),
        _xml_note("D", 3),
    ]
    measures = "".join(
        f'<measure number="{i}">'
        + ("<attributes><divisions>2</divisions></attributes>" if i == 1 else "")
        + body
        + "</measure>"
        for i, body in enumerate(bars, start=1)
    )
    path = tmp_path / "page.musicxml"
    path.write_text(f'<score-partwise><part id="P1">{measures}</part></score-partwise>')

    placed = reader_bars(path)
    assert [b.start for b in placed] == [0.0, 4.0, 8.0, 14.0, 17.0]
    assert [b.filled for b in placed] == [4.0, 4.0, 6.0, 1.0, 3.0]
    assert placed[1].fills and not placed[2].fills and not placed[3].fills
    # ...and the reader itself puts each bar's first note there.
    first = {}
    for note in mscz.parse_musicxml(path).notes:
        first.setdefault(note.bar, note.position)
    assert [first[i] for i in range(1, 6)] == [b.start for b in placed]


EMBRACEABLE = {26: 4.25, 28: 4.125}


def _verdicts(found):
    return [item["verdict"] for item in found]


def test_a_step_on_an_overfull_page_bar_is_the_pages():
    """Gingerbread Boy, 2026-09-29: the OMR read six beats into the page's
    bar 102 and the trace stepped -2 there -- every later note sits two beats
    later on the page than in the music. Nothing is left once the page's
    overrun is taken out."""
    from swingscribe.evaluation import describe_page_steps, page_steps

    trace, differences, page = _heard(lambda bar: 0.0, {11: 6})
    assert [(s["bar"], s["change"]) for s in trace["steps"]] == [(12, -2.0)]
    found = page_steps(trace, page, 4.0, differences)
    assert _verdicts(found) == ["page"]
    assert [b.number for b in found[0]["bars"]] == ["11"]
    assert found[0]["overrun"] == 2.0
    assert found[0]["residual"] == pytest.approx(0.0)
    assert describe_page_steps(found) == (
        "-2.0 at bar 12: page bar 11 holds 6 of 4 beats -- the page's step (residual +0.00)"
    )


def test_a_whole_beat_step_with_no_overrun_is_the_grids():
    """Cheese Cake, 2026-09-29: its whole-beat step has no overfull bar
    behind it -- the page's only unfilled bars are two short ones far from
    it -- and WJazzD's annotation of the same solo steps there too: ours."""
    from swingscribe.evaluation import describe_page_steps, page_steps

    trace, differences, page = _heard(lambda bar: 1.0 if bar >= 21 else 0.0, {8: 3.5, 16: 3.5})
    found = page_steps(trace, page, 4.0, differences)
    assert _verdicts(found) == ["grid"]
    assert found[0]["bars"] == [] and found[0]["overrun"] == 0.0
    assert found[0]["residual"] == 1.0
    assert describe_page_steps(found) == ""


def test_the_embraceable_you_flicker_is_the_pages_every_time():
    """Embraceable You, 2026-09-30: the OMR read 4.25 beats into page bar 26
    and 4.125 into bar 28, so every later note sits 0.375 of a beat late on
    the page, and our line wobbles a sixteenth either side of that -- its
    runs sit at -0.375, -0.125 and -0.375 of a beat, which the trace labels
    -0.5, 0, -0.5: three steps no grid made. These are that page's own
    numbers. The first is where the page's overrun crosses (it sits inside
    the run before, whose last notes are after it); the other two move
    nothing the trace can resolve -- a quarter of a beat, which the trace's
    own rounding labels zero -- on a page running a fraction late."""
    from swingscribe.evaluation import describe_page_steps, page_steps

    trace, differences, page = _heard(lambda bar: 0.25 if bar in (31, 32) else 0.0, EMBRACEABLE)
    assert [s["change"] for s in trace["steps"]] == [-0.5, 0.5, -0.5]
    found = page_steps(trace, page, 4.0, differences)
    assert [item["after"] for item in found] == [-0.375, -0.125, -0.375]
    assert [item["residual"] for item in found] == [0.0, 0.25, -0.25]
    assert _verdicts(found) == ["page", "page", "page"]
    # The first step is where the page's overrun crosses: both bars, summed.
    assert [b.number for b in found[0]["bars"]] == ["26", "28"]
    assert found[0]["overrun"] == pytest.approx(0.375)
    # The other two move nothing across them; the page runs 0.375 late.
    assert found[1]["overrun"] == found[2]["overrun"] == 0.0
    assert found[2]["standing_overrun"] == pytest.approx(0.375)
    note = describe_page_steps(found)
    assert (
        "-0.5 at bar 29: page bar 26 holds 4.25 of 4 beats, page bar 28 holds 4.125 of 4 beats"
        " -- the page's step (residual +0.00)" in note
    )
    assert (
        "+0.5 at bar 31: nothing the trace resolves moved across it (residual +0.25); the page"
        " runs 0.375 of a beat late since page bars 26, 28, which the trace rounds to half beats"
        " -- the page's step" in note
    )
    assert "Undecided" not in note


def test_a_grid_beat_under_a_fractional_page_offset_is_the_grids():
    """The review of 2026-09-30: the same page, and then the grid drops a
    beat at bar 36 while our line sits a 32nd later there. On the half-beat
    labels that is -0.5 -> -1.0, a change of HALF a beat, and the rule
    before this one gave it to the page (half a beat being "what no grid
    makes"). The unrounded runs moved -0.875 with nothing on the page
    between them: the grid's beat, a 32nd short."""
    from swingscribe.evaluation import describe_page_steps, page_steps

    trace, differences, page = _heard(lambda bar: -0.875 if bar >= 36 else 0.0, EMBRACEABLE)
    assert [s["change"] for s in trace["steps"]] == [-0.5, -0.5]
    assert [s["offset"] for s in trace["segments"]] == [0.0, -0.5, -1.0]
    found = page_steps(trace, page, 4.0, differences)
    assert _verdicts(found) == ["page", "grid"]
    assert found[1]["overrun"] == 0.0
    assert found[1]["residual"] == -0.875
    # The page's step is still named; the grid's, with no page bar near it, is not.
    assert describe_page_steps(found).count("at bar") == 1


def test_a_half_beat_step_with_no_overrun_is_undecided():
    """WJazzD's annotation of Hancock's Gingerbread Boy -- no OMR reader
    anywhere -- traces +0.5 at bar 6: half-beat steps are not the page's by
    construction. With no overfull bar, half a beat left over is neither a
    grid's beat nor the page's, and is not counted; the annotation says so
    on its own."""
    from swingscribe.evaluation import describe_page_steps, page_steps

    trace, differences, page = _heard(lambda bar: 0.5 if bar >= 20 else 0.0, {})
    found = page_steps(trace, page, 4.0, differences)
    assert _verdicts(found) == ["undecided"]
    assert found[0]["residual"] == 0.5
    assert describe_page_steps(found) == (
        "Undecided: +0.5 at bar 20: residual +0.50 with the page's overrun out: not a whole"
        " beat, so not the grid's, and not what the page moved"
    )


def test_a_flicker_where_the_page_runs_no_fraction_late_is_not_the_pages():
    """Our line alone sitting on a label's edge -- a quarter of a beat late,
    then three eighths -- flickers the trace too. Nothing moved, but the
    page has no overrun there to have made the offset, so it is not the
    page's step either."""
    from swingscribe.evaluation import describe_page_steps, page_steps

    trace, differences, page = _heard(lambda bar: -0.375 if bar >= 20 else -0.25, {})
    assert [s["change"] for s in trace["steps"]] == [-0.5]
    found = page_steps(trace, page, 4.0, differences)
    assert _verdicts(found) == ["undecided"]
    assert found[0]["residual"] == -0.125
    assert describe_page_steps(found) == (
        "Undecided: -0.5 at bar 19: nothing the trace resolves moved across it (residual -0.12),"
        " and the trace would step here without the page's overruns: rounding an offset that"
        " is not the page's"
    )


def test_the_tolerance_is_the_traces_own_label_arithmetic():
    """A residual is read the way the trace reads an offset: to the half
    beat, a quarter-beat tie going to the whole number, because Python
    rounds a tie to the even count of half beats. A quarter from a whole
    number is that number; anything further is a half beat."""
    from swingscribe.evaluation import STEP_MATCH, page_steps

    assert STEP_MATCH == 0.25
    for value, whole in ((0.25, 0.0), (-0.25, 0.0), (0.75, 1.0), (-0.75, -1.0), (1.25, 1.0)):
        assert round(2 * value) / 2 == whole
    cases = {
        (0.0, 0.75): "grid",
        (0.0, 0.74): "undecided",
        (0.0, 0.26): "undecided",
        (0.125, 0.375): "undecided",  # nothing moved, and no page to have made it
        (0.0, -1.25): "grid",
    }
    for medians, verdict in cases.items():
        trace, differences = _runs(medians)
        assert _verdicts(page_steps(trace, _page({}), 4.0, differences)) == [verdict], medians
    # A page running an eighth late since its bar 2 does not make this step:
    # with its 0.125 added back the runs read 0.25 and 0.5, labelled 0 and
    # 0.5 -- the step stands without the page, so it is our line's.
    trace, differences = _runs((0.125, 0.375))
    assert _verdicts(page_steps(trace, _page({2: 4.125}), 4.0, differences)) == ["undecided"]
    assert _verdicts(page_steps(trace, _page({2: 4.5}), 4.0, differences)) == ["undecided"]


def test_a_near_zero_step_is_the_pages_only_if_it_vanishes_without_the_page():
    """The counterfactual, on the three cases a review built through the real
    trace (2026-09-30). A: a page an eighth late since bar 2 while our line
    moves from a sixteenth to an eighth late -- our line's. B: a page a half
    beat late since bar 2 while our line moves from on the page to a
    sixteenth late -- the half beat pushes an exact-quarter tie across a
    label, so the page made the step. C: an eighth's overrun between the
    runs while our line moves a sixteenth -- our line's."""
    from swingscribe.evaluation import page_steps

    for offset_at, fills, expected in (
        (lambda b: 0.5 if b >= 20 else 0.25, {2: 4.125}, "undecided"),
        (lambda b: 0.25 if b >= 20 else 0.0, {2: 4.5}, "page"),
        (lambda b: 0.5 if b >= 21 else 0.25, {20: 4.125}, "undecided"),
    ):
        trace, differences, page = _heard(offset_at, fills)
        if not trace["steps"]:
            continue  # the page's rounding made no step at all: nothing to judge
        verdicts = _verdicts(page_steps(trace, page, 4.0, differences))
        assert expected in verdicts, (fills, verdicts)
        assert "page" not in verdicts or expected == "page", (fills, verdicts)


def test_a_step_is_summed_over_every_overfull_bar_the_page_crossed_between_the_runs():
    """Four bars that each overrun by a quarter beat move the page a whole
    beat. The runs between them are too short to stand (under TRACE_MIN_RUN
    matches, folded into the run before), so the trace reads ONE step of -1
    -- the page's, though no single bar at the step holds a beat of it."""
    from swingscribe.evaluation import page_steps

    trace, differences, page = _heard(lambda bar: 0.0, {10: 4.25, 11: 4.25, 12: 4.25, 13: 4.25})
    assert [s["change"] for s in trace["steps"]] == [-1.0]
    found = page_steps(trace, page, 4.0, differences)
    assert _verdicts(found) == ["page"]
    assert [b.number for b in found[0]["bars"]] == ["10", "11", "12", "13"]
    assert found[0]["overrun"] == pytest.approx(1.0)


def test_a_short_bar_at_a_step_is_named_but_never_explains_it():
    """The reader pads a short bar to its signature, so it cannot move a
    note after it: reported, never the page's step."""
    from swingscribe.evaluation import describe_page_steps, page_steps

    trace, differences, page = _heard(lambda bar: 1.0 if bar >= 12 else 0.0, {11: 3})
    found = page_steps(trace, page, 4.0, differences)
    assert _verdicts(found) == ["grid"]
    assert [b.number for b in found[0]["bars"]] == ["11"]
    assert describe_page_steps(found) == (
        "+1.0 at bar 12: page bar 11 holds 3 of 4 beats -- not this step"
        " (residual +1.00, a whole beat: the grid's)"
    )


def test_an_overfull_bar_whose_excess_is_not_the_step_does_not_explain_it():
    """Page bar 11 moves two beats; a step of -1 there leaves a whole beat
    over (a beat the grid doubled beside the page's slip), and a step of +2
    leaves four."""
    from swingscribe.evaluation import page_steps

    for shift, left in ((1.0, 1.0), (4.0, 4.0)):
        trace, differences, page = _heard(lambda bar, s=shift: s if bar >= 12 else 0.0, {11: 6})
        found = page_steps(trace, page, 4.0, differences)
        assert _verdicts(found) == ["grid"]
        assert found[0]["residual"] == left


def test_a_trace_without_steps_has_nothing_to_check():
    from swingscribe.evaluation import page_steps

    trace, differences, page = _heard(lambda bar: 0.0, {})
    assert trace["steps"] == []
    assert page_steps(trace, page, 4.0, differences) == []
    assert page_steps({"segments": [], "steps": []}, [], 4.0, []) == []


def test_differences_that_are_not_the_traces_are_refused():
    """A run with no matched note in it means the differences came from some
    other alignment; a median of nothing would be a verdict on nothing."""
    from swingscribe.evaluation import page_steps

    trace, differences = _runs((0.0, 1.0))
    with pytest.raises(ValueError, match="not this trace's"):
        page_steps(trace, _page({}), 4.0, differences[:80])


# ── does confidence point at the errors ──────────────────────────────────────


def test_a_confidence_that_ranks_every_error_lowest_reads_one():
    from swingscribe.evaluation import confidence_ranking

    confidence = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95]
    wrong = [True] + [False] * 9
    ranking = confidence_ranking(confidence, wrong)
    assert ranking.auc == 1.0
    assert ranking.low_10 == 1.0 and ranking.low_20 == 1.0
    assert (ranking.n, ranking.flagged) == (10, 1)
    # ...and one that ranks it highest reads zero, and finds none of it.
    upside_down = confidence_ranking(confidence, list(reversed(wrong)))
    assert upside_down.auc == 0.0 and upside_down.low_20 == 0.0


def test_the_auc_is_the_mann_whitney_statistic_with_ties_half():
    from swingscribe.evaluation import confidence_ranking

    confidence = [0.2, 0.5, 0.5, 0.9]
    wrong = [True, True, False, False]
    # Pairs (wrong, right): (0.2,0.5) below, (0.2,0.9) below, (0.5,0.5) tie,
    # (0.5,0.9) below: 3.5 of 4.
    assert confidence_ranking(confidence, wrong).auc == pytest.approx(3.5 / 4)


def test_a_tie_across_the_cut_is_counted_in_proportion():
    """The piano model's confidence takes about fifty values, so a sort order
    would otherwise decide which tied notes fall inside the lowest tenth."""
    from swingscribe.evaluation import share_in_lowest

    # Twenty notes at one confidence, four of them wrong: the lowest 10% is
    # two of those twenty, expected to hold 2 * 4/20 of a wrong note.
    confidence = [0.5] * 20
    wrong = [True] * 4 + [False] * 16
    assert share_in_lowest(confidence, wrong, 0.1) == pytest.approx(0.1)
    assert share_in_lowest(confidence, wrong, 0.2) == pytest.approx(0.2)


def test_a_ranking_with_nothing_to_find_says_so_rather_than_inventing_it():
    from swingscribe.evaluation import confidence_ranking

    empty = confidence_ranking([0.1, 0.9], [False, False])
    assert empty.auc is None and empty.low_10 is None and empty.flagged == 0
    assert confidence_ranking([0.1, 0.9], [True, True]).auc is None
    with pytest.raises(ValueError):
        confidence_ranking([0.1], [True, False])


def test_note_hits_are_mir_evals_match_and_reproduce_its_precision():
    """The flags must be the very match the note precision beside them is
    computed from, not a second opinion about it."""
    pytest.importorskip("mir_eval")
    from swingscribe.evaluation import note_hits
    from swingscribe.metrics import score_notes
    from swingscribe.model import NoteEvent

    def note(onset, pitch):
        return NoteEvent(onset=onset, duration=0.2, pitch=pitch, confidence=0.5, source="t")

    reference = [note(0.0, 60), note(0.5, 62), note(1.0, 64), note(1.5, 65)]
    estimate = [
        note(0.01, 60),  # a hit
        note(0.52, 63),  # the right time, the wrong pitch
        note(0.80, 60),  # nothing there
        note(1.02, 64),  # a hit
        note(1.60, 65),  # 100 ms late: outside the 50 ms onset tolerance
    ]
    hits = note_hits(reference, estimate)
    assert hits == [True, False, False, True, False]
    assert sum(hits) / len(estimate) == pytest.approx(
        score_notes(reference, estimate)["note_precision"]
    )
    assert note_hits([], estimate) == [False] * 5


# ── what a mean is made of ───────────────────────────────────────────────────


def test_tempo_classes_are_wjazzds_own_bands():
    """Measured off the database: SLOW tops out at 79.2 bpm, MEDIUM SLOW
    starts at 81.8, MEDIUM at 112.0, MEDIUM UP at 140.5, UP at 180.0."""
    from swingscribe.evaluation import TEMPO_CLASS_ORDER, tempo_class

    bpms = (79.2, 81.8, 108.6, 112.0, 139.5, 140.5, 179.3, 180.0)
    assert [tempo_class(b) for b in bpms] == [
        "SLOW",
        "MEDIUM SLOW",
        "MEDIUM SLOW",
        "MEDIUM",
        "MEDIUM",
        "MEDIUM UP",
        "MEDIUM UP",
        "UP",
    ]
    assert tempo_class(None) is None and tempo_class(0.0) is None
    assert TEMPO_CLASS_ORDER[0] == "SLOW" and TEMPO_CLASS_ORDER[-1] == "UP"


def test_strata_keep_each_fields_own_n_and_skip_rows_without_a_stratum():
    from swingscribe.evaluation import strata

    rows = [
        {"tempoclass": "UP", "note_f1": 0.9, "beat_f1": 0.95},
        {"tempoclass": "UP", "note_f1": 0.7},  # note-scored, no beat grid
        {"tempoclass": "SLOW", "note_f1": 0.5, "beat_f1": 0.6},
        {"tempoclass": None, "note_f1": 0.1},  # no class: in no stratum
        {"tempoclass": "SLOW", "note_f1": "n/a"},  # not a number: not counted
    ]
    table = strata(rows, "tempoclass", ("note_f1", "beat_f1"))
    assert table["UP"] == {"note_f1": 0.8, "note_f1_n": 2.0, "beat_f1": 0.95, "beat_f1_n": 1.0}
    assert table["SLOW"]["note_f1_n"] == 1.0
    assert set(table) == {"UP", "SLOW"}
