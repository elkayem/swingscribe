"""Putting WJazzD's clock and ours on the same axis.

These exist because the fit has been wrong twice, both times in the way that
matters most: it returned a confident alignment that was subtly off, and the
resulting bad score read as a transcription failure rather than a measurement
failure. The second one made a solo we transcribe at note F1 0.84 report 0.51.

So the cases below are the two that broke it, not a general survey.
"""

import pytest

numpy = pytest.importorskip("numpy")

from swingscribe.wjazz import (  # noqa: E402
    fit_affine,
    notated_positions,
    title_tokens,
)


def synth(n=240, spacing=0.25, offset=97.5, rate=1.0, seed=0):
    """A reference solo, and 'our' transcription of the same performance."""
    rng = numpy.random.default_rng(seed)
    ref_on = numpy.cumsum(rng.uniform(0.6, 1.4, n) * spacing)
    ref_p = rng.integers(55, 80, n)
    est_on = ref_on * rate + offset + rng.normal(0, 0.008, n)
    order = numpy.argsort(est_on)
    return ref_on, ref_p, est_on[order], ref_p[order]


def worst_placement_error(ref_on, offset, rate, true_offset, true_rate):
    """How far the fitted map puts a note from where the true map puts it.

    Offset and rate trade off against each other, so neither alone says
    whether the fit is right; only the map they define does.
    """
    fitted = ref_on * rate + offset
    truth = ref_on * true_rate + true_offset
    return float(numpy.max(numpy.abs(fitted - truth)))


def test_recovers_a_plain_offset():
    ref_on, ref_p, est_on, est_p = synth(offset=97.5)
    region = (float(est_on[0]) - 2, float(est_on[-1]) + 2)
    offset, rate, hits = fit_affine(ref_on, ref_p, est_on, est_p, region)
    assert worst_placement_error(ref_on, offset, rate, 97.5, 1.0) < 0.02
    assert hits > 0.9 * len(ref_on)


def test_recovers_a_playback_speed_difference():
    """Two CD issues of one master, 0.35% apart. Walkin' really is like this."""
    ref_on, ref_p, est_on, est_p = synth(offset=54.8, rate=0.9965)
    region = (float(est_on[0]) - 2, float(est_on[-1]) + 2)
    offset, rate, hits = fit_affine(ref_on, ref_p, est_on, est_p, region)
    assert worst_placement_error(ref_on, offset, rate, 54.8, 0.9965) < 0.02
    assert hits > 0.9 * len(ref_on)


def test_a_solo_starting_well_after_the_span_begins():
    """The bug of 2026-08-24.

    The user's span opened 26 seconds before J.J. Johnson actually started
    playing. Seeding the offset search from the span's start therefore aimed
    it 26 seconds wide, and the true offset fell outside the window — so the
    fit settled on a nearby wrong alignment and reported 253 matches where
    there were 415. Nothing may depend on the span being tight any more.
    """
    ref_on, ref_p, est_on, est_p = synth(offset=63.9, rate=0.9965)
    region = (float(est_on[0]) - 26.0, float(est_on[-1]) + 4.0)
    offset, rate, hits = fit_affine(ref_on, ref_p, est_on, est_p, region)
    assert worst_placement_error(ref_on, offset, rate, 63.9, 0.9965) < 0.02
    assert hits > 0.9 * len(ref_on)


def test_the_wrong_take_cannot_be_fitted():
    """The control the whole benchmark leans on.

    Two free parameters over a few hundred notes must not be able to
    manufacture agreement, or a high score would mean nothing. Against an
    unrelated solo the fit has to stay near what note density alone predicts.
    """
    ref_on, ref_p, _, _ = synth(seed=1)
    _, _, est_on, est_p = synth(seed=2)
    region = (float(est_on[0]) - 5, float(est_on[-1]) + 5)
    _, _, hits = fit_affine(ref_on, ref_p, est_on, est_p, region)
    assert hits < 0.15 * len(ref_on)


def test_title_tokens_ignore_words_every_filename_has():
    assert title_tokens("06 Giant Steps") == {"giant", "steps"}
    assert title_tokens("Tommy Flanagan Solo on Giant Steps") == {
        "tommy",
        "flanagan",
        "giant",
        "steps",
    }


def test_notated_positions_read_the_metrical_annotation():
    """WJazzD carries a human's NOTATION, not only their onsets: bar, beat,
    and which tatum of how many subdivisions. That is what lets the notation
    be scored against solos other than the three bebop ones, which is the
    control a grid rule tuned on eighth-note lines needs."""

    class FakeDb:
        def __init__(self, rows):
            self.rows = rows

        def execute(self, _sql, _params):
            return iter(self.rows)

    # bar, beat, tatum, division, period, pitch
    rows = [
        (1, 1, 2, 2, 4, 57),  # bar 1, beat 1, second of two eighths -> 0.5
        (1, 3, 1, 1, 4, 62),  # bar 1, beat 3 -> 2.0
        (3, 2, 2, 3, 4, 55),  # bar 3, beat 2, second of a triplet -> 9.333
    ]
    positions = notated_positions(FakeDb(rows), 1)
    # Positions come back relative to the solo's own first note.
    assert positions[0] == (0.0, 57)
    assert abs(positions[1][0] - 1.5) < 1e-9
    assert abs(positions[2][0] - 8.8333333) < 1e-6
