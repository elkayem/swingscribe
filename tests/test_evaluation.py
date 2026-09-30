"""The benchmark's bookkeeping (swingscribe.evaluation, docs/roadmap.md E1-E3).

Three things the harness asks about its scores: is a change more than noise,
may a track be looked at, and how far a reference page can be trusted. Pure
arithmetic and hashing, so all of it runs in CI.
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


def test_a_noisy_small_change_is_not_decided():
    # R33's shape: a small mean rise with 7 pages up and 5 down.
    before = [0.80] * 12
    after = [0.83, 0.82, 0.84, 0.81, 0.83, 0.82, 0.83, 0.78, 0.79, 0.77, 0.79, 0.78]
    c = paired_change(before, after, tolerance=0.002)
    assert (c.up, c.down, c.level) == (7, 5, 0)
    assert c.low < 0.0 < c.high
    assert not c.decided
    assert c.p == pytest.approx(sign_test(7, 5))


def test_a_consistent_change_is_decided_and_the_interval_brackets_the_mean():
    before = [0.5 + 0.01 * i for i in range(20)]
    after = [b + 0.02 + 0.001 * (i % 3) for i, b in enumerate(before)]
    c = paired_change(before, after)
    assert c.decided
    assert c.low <= c.mean <= c.high
    assert c.up == 20 and c.down == 0
    assert c.p < 1e-5


def test_the_interval_resamples_recordings_not_tracks():
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
    before = [0.1, 0.4, 0.3, 0.9, 0.5]
    after = [0.2, 0.3, 0.35, 0.95, 0.4]
    assert paired_change(before, after) == paired_change(before, after)


def test_paired_change_refuses_what_it_cannot_pair():
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
