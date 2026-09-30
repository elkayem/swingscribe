"""The routing suggestion, on synthetic stem levels.

The one property that matters above all: a span a horn leads is never
suggested trio. The worst horn spans measured on the benchmark's Roformer
stems (docs/routing.md) are pinned here as levels, so a threshold moved
toward them fails a test before it can send a saxophone to the piano model.
"""

import importlib.util
import math
import sys
from pathlib import Path

import pytest

from swingscribe import routing
from swingscribe.routing import StemLevels, suggest

ROFORMER = "bsroformer_sw"


def levels(share, db, active_s=60.0):
    """StemLevels from a piano share and per-stem dB, the rest of the melodic
    share going to the first non-piano stem listed in `db`."""
    rivals = [s for s in routing.MELODIC_STEMS if s in db and s != "piano"]
    lead_share = {s: 0.0 for s in routing.MELODIC_STEMS if s in db}
    lead_share["piano"] = share
    if rivals:
        lead_share[rivals[0]] = 1.0 - share
    return StemLevels(dict(db), lead_share, active_s, active_s)


def band(other, piano, bass=-26.0, drums=-32.0, guitar=-110.0, vocals=-115.0):
    return {
        "other": other,
        "piano": piano,
        "bass": bass,
        "drums": drums,
        "guitar": guitar,
        "vocals": vocals,
    }


# --- summarize --------------------------------------------------------------


def test_summarize_counts_who_is_loudest_each_second():
    loud, soft, silent = 1e-2, 1e-4, 0.0
    power = {
        "piano": [loud, loud, loud, soft, silent],
        "other": [soft, soft, soft, loud, silent],
        "bass": [soft] * 5,
    }
    got = routing.summarize(power)
    # The fifth second is silence in every melodic stem: it votes for nobody.
    assert got.active_s == 4.0
    assert got.span_s == 5.0
    assert got.lead_share == {"other": 0.25, "piano": 0.75}
    assert got.level_db["bass"] == pytest.approx(-40.0, abs=1e-6)
    assert got.level_db["piano"] == pytest.approx(10 * math.log10((3 * loud + soft) / 5))


def test_summarize_ignores_bleed_far_under_the_span_loud_level():
    # Between phrases the horn's stem holds bleed 50 dB down: those seconds
    # are not the piano "leading", they are nobody playing.
    power = {"other": [1e-2] * 8 + [1e-7] * 2, "piano": [1e-4] * 8 + [1e-8] * 2}
    got = routing.summarize(power)
    assert got.active_s == 8.0
    assert got.lead_share["other"] == 1.0


def test_summarize_cuts_stems_to_the_shortest():
    got = routing.summarize({"piano": [1e-2] * 12, "other": [1e-6] * 10})
    assert got.span_s == 10.0


def test_summarize_ignores_a_summed_stem():
    # "other+vocals+guitar+piano" holds the piano too: counted as a stem it
    # would be the loudest one and make every piano look like a comp.
    power = {"piano": [1e-2] * 5, "other": [1e-6] * 5, "other+vocals+guitar+piano": [4e-2] * 5}
    got = routing.summarize(power)
    assert set(got.level_db) == {"piano", "other"}
    assert set(got.lead_share) == {"other", "piano"}


def test_percentile_matches_numpy_linear_interpolation():
    values = [3.0, 1.0, 4.0, 1.0, 5.0, 9.0, 2.0, 6.0]
    np = pytest.importorskip("numpy")
    for q in (0, 5, 50, 95, 100):
        assert routing._percentile(values, q) == pytest.approx(float(np.percentile(values, q)))


# --- the piano call -----------------------------------------------------------


def test_a_piano_solo_with_the_rhythm_section_is_trio():
    s = suggest(levels(0.99, band(other=-45.0, piano=-25.0)), ROFORMER)
    assert s.ensemble == "trio"
    assert s.stem == "piano"
    assert 0.5 < s.confidence <= 1.0
    assert "piano" in s.reason and "trio" in s.reason


def test_no_bass_and_no_drums_is_solo_piano():
    s = suggest(levels(1.0, band(other=-90.0, piano=-25.0, bass=-60.0, drums=-70.0)), ROFORMER)
    assert s.ensemble == "solo-piano"
    assert s.stem == "piano"


def test_quiet_drums_alone_do_not_make_solo_piano():
    # Sonny Clark's brushes sit 31 dB under his piano with the bass right
    # there: that is a trio.
    s = suggest(levels(1.0, band(other=-90.0, piano=-21.0, bass=-25.0, drums=-52.0)), ROFORMER)
    assert s.ensemble == "trio"


def test_nothing_is_suggested_off_the_measured_separator():
    # htdemucs_6s, held out, failed both ways: piano solos under `guitar`, and
    # Coltrane's soprano on My Favorite Things read as below -- passing the
    # share test and 0.9 dB short of the level test.
    piano_solo = levels(0.99, band(other=-39.0, piano=-21.0, bass=-26.0))
    soprano = [
        levels(0.933, band(other=-24.0, piano=-24.0 + 4.87), active_s=15.0),
        levels(0.867, band(other=-24.0, piano=-24.0 + 5.14), active_s=15.0),
    ]
    assert suggest(piano_solo, ROFORMER).ensemble == "trio"
    for model in ("htdemucs_6s", "some_new_model", None):
        for lv in (piano_solo, *soprano):
            s = suggest(lv, model)
            assert s.ensemble is None and s.stem is None
            assert "bsroformer_sw" in s.reason
            assert "piano_share" in s.evidence  # a survey can still see why


def test_a_piano_comping_under_a_bass_solo_is_no_suggestion():
    # Soul Station 390-455 s traced this way: piano 11.5 dB under the bass.
    s = suggest(levels(1.0, band(other=-120.0, piano=-38.0, bass=-26.5, drums=-45.0)), ROFORMER)
    assert s.ensemble is None and s.stem is None
    assert "bass" in s.reason


def test_piano_trading_with_the_drums_is_still_a_piano_call():
    # Flanagan trading fours: 6-8 dB under the drums over 20 s windows.
    s = suggest(levels(1.0, band(other=-120.0, piano=-30.0, bass=-25.5, drums=-23.0)), ROFORMER)
    assert s.ensemble == "trio"


# --- the horn call --------------------------------------------------------------


def test_a_horn_over_comping_is_horn_led_on_its_stem():
    s = suggest(levels(0.05, band(other=-20.0, piano=-33.0)), ROFORMER)
    assert s.ensemble == "horn-led"
    assert s.stem == "other"
    assert s.confidence > 0.9


def test_a_guitar_lead_names_the_guitar_stem():
    # Metheny's Nothing Personal: guitar 0.99 of the seconds, piano 11 dB
    # over `other` but far under the guitar.
    db = band(other=-48.3, piano=-37.4, guitar=-24.0)
    lv = StemLevels(db, {"other": 0.01, "vocals": 0.0, "guitar": 0.99, "piano": 0.0}, 60.0, 60.0)
    s = suggest(lv, ROFORMER)
    assert s.ensemble == "horn-led"
    assert s.stem == "guitar"


def test_a_silent_piano_stem_is_said_so():
    s = suggest(levels(0.0, band(other=-21.0, piano=-117.0)), ROFORMER)
    assert s.ensemble == "horn-led"
    assert "silent" in s.reason


def test_a_horn_solo_selected_with_the_piano_solo_stays_horn_led():
    # Shorter's Dolores solo straight into Hancock's: 58% of the span piano,
    # read share 0.568 at +1.8 dB. A horn is in it, so it must not be trio,
    # and the reason must not claim the horn "carries" it.
    s = suggest(levels(0.568, band(other=-24.0, piano=-22.2)), ROFORMER)
    assert s.ensemble == "horn-led"
    assert "select that part alone" in s.reason
    assert s.confidence < 0.6


def test_the_horn_call_is_withheld_where_a_piano_can_hide_in_guitar():
    # htdemucs_6s filed Hancock's Dolores under `guitar`: guitar-led, a quiet
    # piano stem, and a PIANO solo. Only the Roformer earns the horn call.
    db = band(other=-52.6, piano=-27.4, guitar=-26.3, bass=-72.0)
    lv = StemLevels(db, {"other": 0.0, "vocals": 0.0, "guitar": 0.65, "piano": 0.35}, 90.0, 90.0)
    for model in ("htdemucs_6s", None):
        s = suggest(lv, model)
        assert s.ensemble is None and s.stem is None
        assert "bsroformer_sw" in s.reason
    assert suggest(lv, ROFORMER).ensemble == "horn-led"


# --- unsure ---------------------------------------------------------------------


def test_between_the_bands_there_is_no_suggestion():
    s = suggest(levels(0.75, band(other=-24.0, piano=-20.0)), ROFORMER)
    assert s.ensemble is None and s.confidence == 0.0
    assert "horn" in s.reason


def test_a_short_selection_is_no_suggestion():
    s = suggest(levels(1.0, band(other=-90.0, piano=-25.0), active_s=6.0), ROFORMER)
    assert s.ensemble is None
    assert f"at least {routing.MIN_ACTIVE_S:.0f} s" in s.reason


def test_the_floor_is_on_active_seconds_and_inclusive():
    piano = band(other=-90.0, piano=-25.0)
    at = suggest(levels(1.0, piano, active_s=routing.MIN_ACTIVE_S), ROFORMER)
    under = suggest(levels(1.0, piano, active_s=routing.MIN_ACTIVE_S - 1.0), ROFORMER)
    assert at.ensemble == "trio"
    assert under.ensemble is None


# Horn windows from inside labelled horn spans that PASS the share test,
# measured at 1 s steps (docs/routing.md): (piano share, margin dB, active s).
# Only the level test stood between them and the piano model; the floor is
# what refuses them now.
UNDER_THE_FLOOR = [
    (0.900, 3.56, 10.0),  # Wayne Shorter, Adam's Apple, 51-61 s: the loudest
    (0.909, 2.46, 11.0),  # Kenny Dorham, In 'n Out, 23-34 s: the highest share
]


@pytest.mark.parametrize(("share", "margin", "active_s"), UNDER_THE_FLOOR)
def test_short_horn_windows_that_pass_the_share_test_are_refused(share, margin, active_s):
    assert share >= routing.PIANO_SHARE_MIN
    assert active_s < routing.MIN_ACTIVE_S
    lv = levels(share, band(other=-24.0, piano=-24.0 + margin), active_s=active_s)
    s = suggest(lv, ROFORMER)
    assert s.ensemble is None
    assert "at least" in s.reason


def test_a_separation_with_no_piano_stem_cannot_suggest():
    lv = StemLevels(
        {"other": -20.0, "bass": -25.0, "drums": -30.0, "vocals": -90.0},
        {"other": 1.0, "vocals": 0.0},
        60.0,
        60.0,
    )
    s = suggest(lv, "htdemucs")
    assert s.ensemble is None
    assert "no piano stem" in s.reason


@pytest.mark.parametrize(
    "absent",
    [
        ("other", "vocals", "guitar"),  # the piano is the only melodic stem: 100% by default
        ("bass",),  # the lead guard cannot see a bass solo
        ("drums",),
        ("guitar",),
    ],
)
def test_a_partial_stem_set_is_no_suggestion_even_where_the_piano_would_pass(absent):
    # One stem copied across from another cache is a legitimate state
    # (CLAUDE.md). With the other melodic stems gone the piano "leads" every
    # second whatever is playing, which is the horn-called-trio direction.
    db = band(other=-45.0, piano=-25.0)
    assert suggest(levels(1.0, db), ROFORMER).ensemble == "trio"
    for stem in absent:
        del db[stem]
    s = suggest(levels(1.0, db), ROFORMER)
    assert s.ensemble is None and s.stem is None
    for stem in absent:
        assert stem in s.reason
    assert "bsroformer_sw" not in s.reason  # the separator is right, the set is not


def test_every_evidence_value_is_finite():
    # The GUI hands evidence to a JSON encoder that refuses infinity.
    cases = [
        levels(1.0, band(other=-45.0, piano=-25.0)),
        levels(0.0, band(other=-21.0, piano=-117.0)),
        levels(0.75, band(other=-24.0, piano=-20.0)),
        levels(1.0, band(other=-120.0, piano=-38.0, bass=-26.5, drums=-45.0)),
        levels(1.0, band(other=-45.0, piano=-25.0), active_s=3.0),
        StemLevels({"other": -20.0, "piano": -30.0}, {"other": 1.0, "piano": 0.0}, 60.0, 60.0),
        StemLevels({}, {}, 0.0, 0.0),
    ]
    for lv in cases:
        for model in (ROFORMER, "htdemucs_6s"):
            evidence = suggest(lv, model).evidence
            assert all(math.isfinite(v) for v in evidence.values()), evidence


# --- the property ---------------------------------------------------------------

# The worst horn spans and windows the survey measured on the Roformer stems
# (docs/routing.md), each as it was measured: (piano share, piano dB over the
# loudest other melodic stem, active seconds). Windows are every length from
# the floor to 60 s at 1 s steps inside the 100 horn spans. None may ever
# come back trio, and none passes EITHER piano test on its own.
WORST_HORN_SPANS = [
    (0.548, 0.35, 31.0),  # Chet Baker, There Will Never Be Another You, solo 75
    (0.481, -0.6, 133.0),  # Wayne Shorter, Adam's Apple
    (0.568, 1.77, 190.0),  # Shorter's Dolores selected together with Hancock's solo
]
WORST_HORN_WINDOWS = [
    (0.824, 0.35, 17.0),  # the highest share: My Favorite Things, 119-136 s
    (0.812, 3.01, 16.0),  # the highest margin: Adam's Apple, 51-67 s
]
WORST_HORNS = WORST_HORN_SPANS + WORST_HORN_WINDOWS


@pytest.mark.parametrize(("share", "margin", "active_s"), WORST_HORNS)
def test_the_worst_horns_measured_are_never_trio(share, margin, active_s):
    assert active_s >= routing.MIN_ACTIVE_S  # judged, not refused as short
    lv = levels(share, band(other=-24.0, piano=-24.0 + margin), active_s=active_s)
    s = suggest(lv, ROFORMER)
    assert s.ensemble not in ("trio", "solo-piano")


def test_a_piano_call_needs_both_tests_everywhere():
    # Sweep the plane: the piano is called only where the share AND the level
    # test both pass, with room to spare over every horn above.
    for share_pct in range(0, 101, 2):
        for margin in range(-20, 31):
            share = share_pct / 100
            s = suggest(levels(share, band(other=-30.0, piano=-30.0 + margin)), ROFORMER)
            piano = s.ensemble in ("trio", "solo-piano")
            assert piano == (share >= routing.PIANO_SHARE_MIN and margin >= routing.PIANO_MARGIN_DB)
    # Every measured horn fails BOTH tests, each by a margin: a threshold
    # moved toward the horns fails here before it reaches a listener.
    worst_share = max(share for share, _, _ in WORST_HORNS)
    worst_margin = max(margin for _, margin, _ in WORST_HORNS)
    assert routing.PIANO_SHARE_MIN - worst_share >= 0.07
    assert routing.PIANO_MARGIN_DB - worst_margin >= 2.9


def test_confidence_rises_away_from_the_boundary():
    near = suggest(levels(0.91, band(other=-30.0, piano=-23.0)), ROFORMER)
    far = suggest(levels(1.0, band(other=-60.0, piano=-23.0)), ROFORMER)
    assert near.ensemble == far.ensemble == "trio"
    assert 0.5 <= near.confidence < far.confidence == 1.0


# --- reading wavs -----------------------------------------------------------------


def test_measure_reads_a_region_of_real_wavs(tmp_path):
    np = pytest.importorskip("numpy")
    soundfile = pytest.importorskip("soundfile")
    rate = 8000
    seconds = 45
    t = np.arange(rate * seconds) / rate
    tone = 0.3 * np.sin(2 * np.pi * 440 * t)
    quiet = 0.003 * np.sin(2 * np.pi * 220 * t)
    faint = 1e-4 * np.sin(2 * np.pi * 330 * t)
    # The piano plays the first 20 s, the horn the last 25.
    piano = np.where(t < 20, tone, quiet)
    other = np.where(t < 20, quiet, tone)
    bass = 0.1 * np.sin(2 * np.pi * 55 * t)  # a rhythm section: trio, not solo piano
    signals = (
        ("piano", piano),
        ("other", other),
        ("bass", bass),
        ("drums", quiet),
        ("vocals", faint),
        ("guitar", faint),
    )
    paths = {}
    for name, signal in signals:
        paths[name] = tmp_path / f"{name}.wav"
        soundfile.write(paths[name], np.stack([signal, signal], axis=1), rate)
    whole = routing.measure(paths)
    assert whole.span_s == 45.0
    assert whole.lead_share["piano"] == pytest.approx(20 / 45)
    first = routing.measure(paths, (0.0, 20.0))
    assert first.lead_share["piano"] == 1.0
    assert suggest(first, ROFORMER).ensemble == "trio"
    assert suggest(routing.measure(paths, (20.0, None)), ROFORMER).ensemble == "horn-led"


def test_window_power_is_the_same_across_block_boundaries(tmp_path):
    # window_power reads in blocks of 30 windows. A region that starts off a
    # block boundary and spans several blocks must give exactly the windows a
    # one-shot read gives, with the partial window at the end dropped.
    np = pytest.importorskip("numpy")
    soundfile = pytest.importorskip("soundfile")
    rate = 4000
    rng = np.random.default_rng(7)
    ramp = np.linspace(0.1, 1.0, rate * 75)[:, None]
    signal = (rng.normal(0.0, 0.1, size=(rate * 75, 2)) * ramp).astype("float32")
    path = tmp_path / "piano.wav"
    soundfile.write(path, signal, rate, subtype="FLOAT")
    window_s = 0.5
    hop = int(window_s * rate)

    def one_shot(lo, hi):
        mono = signal[int(lo * rate) : int(hi * rate)].astype(np.float64).mean(axis=1)
        whole = len(mono) // hop
        return (mono[: whole * hop].reshape(whole, hop) ** 2).mean(axis=1)

    # 68.6 s is 137 whole windows: five blocks of 30, the last one partial.
    got = routing.window_power({"piano": path}, (3.3, 71.9), window_s)["piano"]
    want = one_shot(3.3, 71.9)
    assert len(got) == len(want) == 137
    assert np.allclose(got, want, rtol=1e-6, atol=0.0)
    # The whole file from zero, and an open-ended region.
    whole = routing.window_power({"piano": path}, None, window_s)["piano"]
    assert np.allclose(whole, one_shot(0, 75))
    tail = routing.window_power({"piano": path}, (50.25, None), window_s)["piano"]
    assert np.allclose(tail, one_shot(50.25, 75))


# --- the survey script ----------------------------------------------------------------


def _survey():
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    spec = importlib.util.spec_from_file_location("routing_survey", scripts / "routing_survey.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("routing_survey", module)
    spec.loader.exec_module(module)
    return module


def test_survey_scores_null_as_horn_led_and_both_pianos_as_trio():
    survey = _survey()
    assert survey.truth_of(None) == "horn-led"
    assert survey.truth_of("horn-led") == "horn-led"
    assert survey.truth_of("trio") == survey.truth_of("solo-piano") == "trio"
    none = routing.Suggestion(None, None, 0.0, "")
    solo = routing.Suggestion("solo-piano", "piano", 0.9, "")
    assert survey.called(none) == "none"
    assert survey.called(solo) == "trio"


def test_survey_leave_one_out_rule_takes_the_gap_midpoint():
    survey = _survey()
    rows = [
        {"truth": "horn-led", "piano_share": 0.2, "margin": -10.0},
        {"truth": "horn-led", "piano_share": 0.5, "margin": 0.0},
        {"truth": "trio", "piano_share": 1.0, "margin": 20.0},
        {"truth": "trio", "piano_share": 0.9, "margin": 12.0},
    ]
    assert survey.gap_midpoint_rule(rows, rows[1]) == (pytest.approx(0.55), pytest.approx(1.0))
    assert survey.gap_midpoint_rule(rows, rows[3]) == (pytest.approx(0.75), pytest.approx(10.0))


def test_survey_splits_refusals_from_doubt_and_finds_the_joint_worst():
    # The previous survey counted a short window and an unsure one as one
    # "none", and kept the share and margin extremes apart -- which is how a
    # horn window passing the share test at +3.6 dB went unreported.
    survey = _survey()
    stats = survey.FloorStats()

    def horn(share, margin, active_s=60.0):
        lv = levels(share, band(other=-30.0, piano=-30.0 + margin), active_s=active_s)
        stats.add("horn-led", suggest(lv, ROFORMER), "a horn", 0, int(active_s))

    horn(0.95, 3.5, active_s=10.0)  # short: refused before any test
    horn(0.92, 2.0)  # passes the share test alone: the joint worst
    horn(0.70, 4.0)  # the loudest, but under the share threshold: unsure
    horn(0.30, -6.0)  # plainly horn-led
    got = stats.as_dict()
    assert got["counts"] == {
        "horn-led -> short": 1,
        "horn-led -> none": 2,
        "horn-led -> horn-led": 1,
    }
    assert got["horn_passing_share"] == 1
    assert got["horn_joint_worst"][:2] == (pytest.approx(0.92), pytest.approx(2.0))
    assert got["horn_max_margin"][:2] == (pytest.approx(0.70), pytest.approx(4.0))
    assert got["horn_max_share"][:2] == (pytest.approx(0.92), pytest.approx(2.0))
    assert survey.judged(suggest(levels(1.0, band(other=-45.0, piano=-25.0)), ROFORMER))


def test_survey_floor_is_restored_after_the_sweep():
    survey = _survey()
    shipped = routing.MIN_ACTIVE_S
    with survey.floor_of(3.0):
        assert routing.MIN_ACTIVE_S == 3.0
    assert shipped == routing.MIN_ACTIVE_S
