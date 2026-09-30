"""Proposing solo spans from stem envelopes and the bar grid (roadmap O3).

Everything here is synthetic: envelopes built in numpy, or a few seconds of
tone written with the standard library's `wave`. The real measurement is
scripts/solo_spans_survey.py against WJazzD (docs/solo-spans.md); these
hold the arithmetic it stands on -- that the partitioning is exact, that the
head is found where the melody repeats and nowhere else, that a boundary
is scored against the reference the way the survey says.
"""

import itertools
import wave

import pytest

# numpy is in the ml group, which CI does not install; the module needs it at import.
pytest.importorskip("numpy", reason="ml dependency group not installed")

import numpy as np  # noqa: E402

from swingscribe import solo_spans  # noqa: E402
from swingscribe.solo_spans import (
    Head,
    StemEnvelopes,
    band_edges,
    band_power,
    bar_frames,
    chroma_power,
    combine,
    find_head,
    lead_stem,
    pool_bars,
    propose,
    read_mono,
    score_boundaries,
    segment,
    stem_envelopes,
)

HOP = solo_spans.HOP_S


def _write_wav(path, channels_data, rate=44100, width=2):
    data = np.stack(channels_data, axis=1)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(data.shape[1])
        handle.setsampwidth(width)
        handle.setframerate(rate)
        if width == 2:
            handle.writeframes((data * 32767).astype("<i2").tobytes())
        else:
            handle.writeframes(((data * 127) + 128).astype(np.uint8).tobytes())


# ── reading ──────────────────────────────────────────────────────────────────


def test_band_edges_run_from_the_bass_band_to_nyquist():
    edges = band_edges(22050)
    assert edges[0] == 20.0 and edges[1] == solo_spans.BAND_LOW_HZ
    assert edges[-1] == 11025.0
    assert np.all(np.diff(edges) > 0)


def test_read_mono_averages_the_channels_and_halves_the_rate(tmp_path):
    path = tmp_path / "stem.wav"
    frames = 44100
    _write_wav(path, [np.full(frames, 0.5), np.full(frames, 0.25)])
    samples, rate = read_mono(path)
    assert rate == 22050
    assert samples.size == frames // 2
    assert samples.dtype == np.float32
    assert np.allclose(samples, 0.375, atol=1e-3)


def test_read_mono_refuses_what_it_cannot_read(tmp_path):
    path = tmp_path / "eight-bit.wav"
    _write_wav(path, [np.zeros(100)], width=1)
    with pytest.raises(ValueError, match="16-bit"):
        read_mono(path)


def test_band_power_puts_a_tone_in_its_own_band():
    rate = 22050
    t = np.arange(rate * 2) / rate
    power = band_power(np.sin(2 * np.pi * 1000.0 * t).astype(np.float32), rate)
    edges = band_edges(rate)
    assert power.shape == (int(np.ceil(t.size / (HOP * rate))), len(edges) - 1)
    loudest = int(np.argmax(power[5]))
    assert edges[loudest] <= 1000.0 < edges[loudest + 1]


def test_chroma_power_names_the_pitch_class():
    rate = 22050
    t = np.arange(rate * 2) / rate
    chroma = chroma_power(np.sin(2 * np.pi * 220.0 * t).astype(np.float32), rate)
    assert int(np.argmax(chroma[5])) == 9  # A, with C as class 0


def test_stem_envelopes_keeps_chroma_only_for_the_stems_asked(tmp_path):
    t = np.arange(44100) / 44100
    tone = 0.3 * np.sin(2 * np.pi * 440 * t)
    for name in ("other", "drums"):
        _write_wav(tmp_path / f"{name}.wav", [tone, tone])
    env = stem_envelopes({p.stem: p for p in tmp_path.glob("*.wav")})
    assert set(env.power) == {"other", "drums"}
    assert set(env.chroma) == {"other"}
    assert env.frames == 10  # one second at a tenth of a second a frame


# ── per-bar pooling ──────────────────────────────────────────────────────────


def test_bar_frames_never_hands_out_an_empty_bar():
    ranges = bar_frames([0.0, 0.02, 1.0, 2.0], HOP, 20)
    assert ranges.tolist() == [[0, 1], [0, 10], [10, 20]]


def test_pool_bars_carries_the_bar_before_a_rest():
    values = np.arange(40, dtype=float)[:, None]
    active = np.ones(40, dtype=bool)
    active[10:20] = False  # the second bar is a rest
    ranges = np.array([[0, 10], [10, 20], [20, 30], [30, 40]])
    pooled = pool_bars(values, ranges, active)
    assert pooled[:, 0].tolist() == [4.5, 4.5, 24.5, 34.5]
    spread = pool_bars(values, ranges, spread=True)
    assert spread.shape == (4, 2) and spread[0, 1] == pytest.approx(np.std(np.arange(10)))


def test_pool_bars_fills_leading_rests_from_the_first_sounding_bar():
    values = np.arange(30, dtype=float)[:, None]
    active = np.zeros(30, dtype=bool)
    active[20:] = True
    pooled = pool_bars(values, np.array([[0, 10], [10, 20], [20, 30]]), active)
    assert pooled[:, 0].tolist() == [24.5, 24.5, 24.5]


# ── partitioning ─────────────────────────────────────────────────────────────


def _brute_force(x, penalty, min_bars):
    """Every admissible partition's cost, the slow way."""
    n = len(x)
    best = (np.inf, None)
    for count in range(n):
        for cuts in itertools.combinations(range(1, n), count):
            edges = [0, *cuts, n]
            pieces = list(zip(edges[:-1], edges[1:], strict=False))
            if any(b - a < min_bars and a != 0 and b != n for a, b in pieces):
                continue
            cost = sum(((x[a:b] - x[a:b].mean(axis=0)) ** 2).sum() + penalty for a, b in pieces)
            if cost < best[0] - 1e-9:
                best = (cost, list(cuts))
    return best[1]


def test_segment_is_the_exact_optimum():
    rng = np.random.default_rng(3)
    for trial in range(20):
        x = rng.normal(size=(8, 2)) + (np.arange(8)[:, None] >= 4) * rng.uniform(0, 3)
        for penalty, min_bars in ((0.5, 1), (2.0, 2), (4.0, 3)):
            assert segment(x, penalty, min_bars) == _brute_force(x, penalty, min_bars), trial


def test_segment_cuts_where_the_texture_changes_and_nowhere_else():
    rng = np.random.default_rng(0)
    means = np.repeat(rng.normal(scale=3.0, size=(3, 30)), 20, axis=0)
    x = means + rng.normal(size=means.shape)
    assert segment(x, 4.0 * 30, 8) == [20, 40]
    # stationary bars earn no cut at the shipped penalty
    assert segment(rng.normal(size=(60, 30)), solo_spans.PENALTY * 30, 8) == []


def test_segment_respects_the_minimum_length():
    x = np.zeros((30, 1))
    x[10:13] = 10.0  # three loud bars inside a quiet stretch
    assert segment(x, 1.0, 1) == [10, 13]
    cuts = segment(x, 1.0, 8)
    pieces = np.diff([0, *cuts, 30])
    assert all(p >= 8 for p in pieces[1:-1])


# ── the head ─────────────────────────────────────────────────────────────────


def _unit_rows(rng, count):
    x = rng.normal(size=(count, 12))
    x -= x.mean(axis=1, keepdims=True)
    return x / np.linalg.norm(x, axis=1, keepdims=True)


@pytest.mark.parametrize("seed", range(6))
def test_find_head_places_the_head_exactly(seed):
    # Exact, not within a bar or two: the smoothed stripe alone began one or
    # two bars late (an even kernel in np.convolve's "same" mode, and the
    # floor eroding the edge), on 193 of 200 planted heads.
    rng = np.random.default_rng(seed)
    chroma = _unit_rows(rng, 120)
    chroma[96:112] = chroma[4:20]  # the head-out repeats the head-in
    head = find_head(chroma)
    assert head is not None
    assert (head.in_start, head.in_end, head.out_start, head.out_end) == (4, 20, 96, 112)
    assert head.similarity > 0.9


def test_refine_moves_a_smoothed_edge_onto_the_raw_crossing():
    raw = np.array([0.0] * 5 + [1.0] * 10 + [0.0] * 5)
    kernel = np.ones(solo_spans.HEAD_SMOOTH_BARS) / solo_spans.HEAD_SMOOTH_BARS
    smoothed = np.convolve(raw, kernel, mode="same")
    a, b = solo_spans._run(smoothed >= 0.7, 10, 0)
    assert (a, b) == (6, 15)  # the bias: one bar late at the start
    assert solo_spans._refine(raw, a, b, 0.7, 2) == (5, 15)
    # inward too, when the smoothed run overhangs bars that are not repeats
    assert solo_spans._refine(raw, 3, 17, 0.7, 2) == (5, 15)
    # and never further than `reach`
    assert solo_spans._refine(raw, 8, 12, 0.7, 2) == (6, 14)


def test_find_head_ignores_repetition_that_does_not_open_and_close_the_track():
    rng = np.random.default_rng(2)
    assert find_head(_unit_rows(rng, 120)) is None
    middle = _unit_rows(rng, 120)
    middle[95:107] = middle[50:62]  # a riff repeated inside the solos, 45 bars on
    assert find_head(middle) is None
    assert find_head(_unit_rows(rng, solo_spans.HEAD_MIN_BARS - 1)) is None


def test_the_head_run_bridges_a_short_gap():
    above = np.array([0, 1, 1, 0, 0, 1, 1, 0, 0, 0, 0, 0, 1], dtype=bool)
    assert solo_spans._run(above, 1, 2) == (1, 7)
    assert solo_spans._run(above, 1, 1) == (1, 3)
    assert solo_spans._run(above, 6, 8) == (1, 13)


def test_combine_keeps_the_timbre_cut_where_the_cues_agree():
    head = Head(in_start=2, in_end=12, out_start=50, out_end=60, similarity=0.95)
    # the cut at 10 and the head edge at 12 are one boundary, placed by the cut
    assert combine([10, 30], head, 70) == {10: "both", 30: "timbre"}
    # with no cut near it, the head edge stands on its own
    assert combine([30], head, 70) == {12: "head", 30: "timbre"}
    assert combine([10, 30], head, 70, "none") == {10: "timbre", 30: "timbre"}
    assert combine([10, 30], None, 70) == {10: "timbre", 30: "timbre"}
    # an edge off the end of the track is no boundary
    assert combine([], Head(0, 5, 69, 70, 0.9), 69) == {5: "head"}


def test_the_head_out_edge_is_only_a_boundary_when_asked_for():
    # Off by default: the reference never once says it is right.
    assert solo_spans.HEAD_EDGES == "in"
    head = Head(in_start=2, in_end=12, out_start=50, out_end=60, similarity=0.95)
    assert combine([10, 30], head, 70, "in+out") == {10: "both", 30: "timbre", 50: "head"}
    assert combine([30], head, 70, "in+out") == {12: "head", 30: "timbre", 50: "head"}


# ── the proposal on synthetic stems ─────────────────────────────────────────


def _envelopes(bars=60, bar_s=2.0, seed=0, change=None):
    """Six stems' band envelopes. `change(stem, bar)` -> (level, centre band)."""
    rng = np.random.default_rng(seed)
    edges = band_edges()
    bands = len(edges) - 1
    per_bar = int(round(bar_s / HOP))
    frames = bars * per_bar
    index = np.arange(bands)
    power = {}
    for stem in ("bass", "drums", "guitar", "other", "piano", "vocals"):
        rows = np.zeros((frames, bands), dtype=np.float32)
        for bar in range(bars):
            level, centre = change(stem, bar)
            shape = np.exp(-0.5 * ((index - centre) / 2.5) ** 2)
            block = level * shape[None, :] * rng.lognormal(sigma=0.3, size=(per_bar, bands))
            rows[bar * per_bar : (bar + 1) * per_bar] = block
        power[stem] = rows
    lines = np.arange(bars + 1) * bar_s
    return StemEnvelopes(hop_s=HOP, edges_hz=edges, power=power), lines


def _horn_then_piano(stem, bar):
    horn = bar < 30
    table = {
        "bass": (1.0, 3),
        "drums": (1.0, 20),
        "other": (10.0 if horn else 0.01, 9),
        "piano": (0.3 if horn else 10.0, 12),
        "guitar": (0.01, 10),
        "vocals": (0.01, 10),
    }
    return table[stem]


def test_propose_cuts_a_horn_solo_from_a_piano_solo_and_names_them():
    env, lines = _envelopes(change=_horn_then_piano)
    proposal = propose(env, lines)
    assert [b.bar for b in proposal.boundaries] == [30]
    assert proposal.boundaries[0].time == pytest.approx(60.0)
    assert [(s.lead, s.kind) for s in proposal.spans] == [
        ("other", "section"),
        ("piano", "section"),
    ]
    assert proposal.head is None  # no chroma, no head


def test_propose_hears_one_horn_hand_over_to_another_in_the_same_stem():
    def trumpet_then_tenor(stem, bar):
        if stem == "other":
            return 10.0, (13 if bar < 30 else 7)  # same level, lower register
        return _horn_then_piano(stem, 0)

    env, lines = _envelopes(change=trumpet_then_tenor)
    assert [b.bar for b in propose(env, lines).boundaries] == [30]


def test_propose_leaves_one_soloist_whole():
    env, lines = _envelopes(change=lambda stem, bar: _horn_then_piano(stem, 0))
    proposal = propose(env, lines)
    assert proposal.boundaries == []
    assert len(proposal.spans) == 1 and proposal.spans[0].lead == "other"


def test_lead_stem_is_rhythm_when_the_melodic_stems_fall_silent():
    def bass_solo(stem, bar):
        if bar >= 30 and stem in solo_spans.MELODIC_STEMS:
            return 1e-4, 10
        return _horn_then_piano(stem, 0)

    env, lines = _envelopes(change=bass_solo)
    assert lead_stem(env, 0.0, 60.0) == "other"
    assert lead_stem(env, 60.0, 120.0) == "rhythm"


def test_propose_handles_a_track_too_short_to_cut():
    env, _lines = _envelopes(bars=2, change=_horn_then_piano)
    empty = propose(env, [0.0, 2.0])
    assert empty.boundaries == [] and empty.spans == []


def _with_head(env, bars=60, head_bars=12, out_at=48, seed=5):
    """`env` with horn chroma in `other`: a melody over the first
    `head_bars` played again from bar `out_at`, and a solo of fresh pitch
    classes in between -- the same horn at the same level throughout, so no
    timbre cue can see where the head ends."""
    rng = np.random.default_rng(seed)
    per_bar = env.frames // bars
    melody = rng.uniform(0.05, 1.0, size=(head_bars, 12))
    rows = []
    for bar in range(bars):
        if bar < head_bars:
            profile = melody[bar]
        elif out_at <= bar < out_at + head_bars:
            profile = melody[bar - out_at]
        else:
            profile = rng.uniform(0.05, 1.0, size=12)
        rows.append(profile[None, :] * rng.lognormal(sigma=0.1, size=(per_bar, 12)))
    chroma = {"other": np.concatenate(rows).astype(np.float32)}
    return StemEnvelopes(hop_s=env.hop_s, edges_hz=env.edges_hz, power=env.power, chroma=chroma)


def test_propose_finds_the_end_of_the_head_by_its_repetition():
    plain, lines = _envelopes(change=lambda stem, bar: _horn_then_piano(stem, 0))
    assert propose(plain, lines).boundaries == []  # timbre alone sees nothing
    env = _with_head(plain)
    proposal = propose(env, lines)
    head = proposal.head
    assert (head.in_start, head.in_end, head.out_start, head.out_end) == (0, 12, 48, 60)
    assert [(b.bar, b.time, b.source) for b in proposal.boundaries] == [(12, 24.0, "head")]
    # the head-out is labelled, but by default is not a boundary
    assert [(s.start, s.end, s.kind, s.lead) for s in proposal.spans] == [
        (0.0, 24.0, "head", "other"),
        (24.0, 120.0, "section", "other"),
    ]
    both = propose(env, lines, head_edges="in+out")
    assert [b.bar for b in both.boundaries] == [12, 48]
    assert [s.kind for s in both.spans] == ["head", "section", "head"]
    assert propose(env, lines, head_edges="none").boundaries == []


# ── scoring ──────────────────────────────────────────────────────────────────


def test_score_boundaries_counts_hits_and_the_errors_it_can_be_sure_of():
    solos = [(10.0, 50.0)]
    scored = score_boundaries([9.0, 30.0, 51.5, 70.0], solos, lambda t: 2.0)
    assert scored.hits == [(True, True, True), (True, True, True)]
    assert scored.inside == 1  # 30 s is inside the solo: wrong for certain
    assert scored.outside == 1  # 70 s: the reference cannot say
    far = score_boundaries([14.5], solos, lambda t: 2.0)
    assert far.hits[0] == (False, False, False)  # 4.5 s: past two bars and 4 s
    assert far.hits[1] == (False, False, False)
    assert score_boundaries([], solos, lambda t: 2.0).hits == [(False,) * 3] * 2


def test_the_track_ends_are_span_edges_but_never_wrong():
    solos = [(0.5, 50.0)]  # a solo that opens the track
    plain = score_boundaries([50.0], solos, lambda t: 2.0)
    assert plain.hits[0] == (False, False, False)  # no proposal near the start
    ends = score_boundaries([50.0], solos, lambda t: 2.0, track=(0.0, 120.0))
    assert ends.hits[0] == (True, True, True)
    assert (ends.inside, ends.outside) == (0, 0)


def test_one_boundary_at_a_handover_is_both_solos_edge():
    # Spans are contiguous: the boundary that ends one soloist's span starts
    # the next one's, so it is credited to both edges -- the deliberate
    # difference from mir_eval's one-to-one matching (see score_boundaries).
    solos = [(10.0, 50.0), (51.0, 90.0)]
    scored = score_boundaries([50.5], solos, lambda t: 2.0)
    assert scored.hits == [(False,) * 3, (True,) * 3, (True,) * 3, (False,) * 3]
    assert (scored.inside, scored.outside) == (0, 0)


def test_the_tolerance_is_in_bars_at_the_local_tempo():
    solos = [(10.0, 50.0)]
    slow = score_boundaries([14.0, 54.0], solos, lambda t: 3.0)  # 4 s is 1.3 bars
    assert slow.hits == [(False, True, True)] * 2
    fast = score_boundaries([14.0, 54.0], solos, lambda t: 1.5)  # 4 s is 2.7 bars
    assert fast.hits == [(False, False, True)] * 2


def test_match_boundaries_is_mir_evals_one_to_one_count():
    pytest.importorskip("mir_eval")
    solos = [(10.0, 50.0), (51.0, 90.0)]
    matched = solo_spans.match_boundaries([50.5], solos, lambda t: 2.0)
    assert sum(any(m) for m in matched) == 1  # the handover counts once
    assert matched[0] == matched[3] == (False, False, False)
    # the bar tolerance reaches mir_eval through its distance hook
    slow = solo_spans.match_boundaries([14.0, 54.0], [(10.0, 50.0)], lambda t: 3.0)
    assert slow == [(False, True, True)] * 2
    # with a proposal for each edge, one-to-one and many-to-one agree
    four = [9.0, 50.2, 51.3, 89.0]
    assert solo_spans.match_boundaries(four, solos, lambda t: 2.0) == (
        score_boundaries(four, solos, lambda t: 2.0).hits
    )
    empty = solo_spans.match_boundaries([], solos, lambda t: 2.0, track=(0.0, 100.0))
    assert empty == [(False,) * 3] * 4
