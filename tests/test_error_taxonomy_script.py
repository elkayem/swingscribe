"""The taxonomy script's regression guard: what it pins and how it diffs.

Same reasoning as tests/test_eval_harness.py — a harness that decides what
counts as a change deserves the same tests as the code it measures. Pure
dict logic, so it runs in CI without audio or the ml group.
"""

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

error_taxonomy = pytest.importorskip("error_taxonomy")


def aggregate(counts, family_counts=None):
    return {
        "overall": {
            "n_solos": 3,
            "n_errors": sum(counts.values()),
            "counts": counts,
            "populations": {"miss": 1, "fp": 1, "pair": 1},
        },
        "family": {"horn": {"counts": family_counts or counts}},
        "noise": {cls: {"count_sd": 1.0, "share_sd": 0.01} for cls in counts},
    }


def test_flatten_names_every_count_by_class_and_family():
    flat = error_taxonomy.flatten(aggregate({"merged": 4, "gated": 2}))
    assert flat["count/merged"] == 4
    assert flat["family/horn/gated"] == 2
    assert flat["population/pair"] == 1
    assert flat["n_solos"] == 3
    assert flat["n_errors"] == 6


def test_unchanged_counts_exit_zero(tmp_path, monkeypatch, capsys):
    agg = aggregate({"merged": 4, "gated": 2})
    pin = tmp_path / "baseline.json"
    pin.write_text(json.dumps({"flat": error_taxonomy.flatten(agg), "noise": agg["noise"]}))
    monkeypatch.setattr(error_taxonomy, "BASELINE", pin)
    assert error_taxonomy.compare(agg) == 0
    assert "unchanged" in capsys.readouterr().out


def test_a_moved_count_exits_one_and_is_flagged_beyond_noise(tmp_path, monkeypatch, capsys):
    pinned = aggregate({"merged": 4, "gated": 2})
    pin = tmp_path / "baseline.json"
    pin.write_text(json.dumps({"flat": error_taxonomy.flatten(pinned), "noise": pinned["noise"]}))
    monkeypatch.setattr(error_taxonomy, "BASELINE", pin)
    # gated grows by 5 against a bootstrap sd of 1.0: beyond 2 sd. merged
    # moves by one, inside it — printed, but not flagged.
    now = aggregate({"merged": 5, "gated": 7})
    assert error_taxonomy.compare(now) == 1
    out = capsys.readouterr().out
    assert "count/gated" in out and "beyond 2 sd" in out
    merged_line = next(line for line in out.splitlines() if "count/merged" in line)
    assert "beyond" not in merged_line


def test_a_class_that_vanished_is_reported(tmp_path, monkeypatch, capsys):
    pinned = aggregate({"merged": 4, "gated": 2})
    pin = tmp_path / "baseline.json"
    pin.write_text(json.dumps({"flat": error_taxonomy.flatten(pinned), "noise": pinned["noise"]}))
    monkeypatch.setattr(error_taxonomy, "BASELINE", pin)
    assert error_taxonomy.compare(aggregate({"merged": 4})) == 1
    assert "gone" in capsys.readouterr().out


def test_no_baseline_is_not_a_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(error_taxonomy, "BASELINE", tmp_path / "missing.json")
    assert error_taxonomy.compare(aggregate({"merged": 1})) == 0


def test_a_mover_is_judged_solo_by_solo_when_the_pin_carries_per_solo_counts(
    tmp_path, monkeypatch, capsys
):
    """Sample sd says `gated` +5 on a class of 2 is beyond noise; the paired
    test says the same because every solo moved up. A class that moved in
    one solo only is inside paired noise however far it moved."""
    pinned = aggregate({"merged": 4, "gated": 2})
    pinned["solos"] = {
        f"s{i}": {
            "family": "horn",
            "note_f1": 0.8,
            "counts": {"merged": 1, "gated": 1 if i < 2 else 0},
        }
        for i in range(4)
    }
    pin = tmp_path / "baseline.json"
    pin.write_text(
        json.dumps(
            {
                "flat": error_taxonomy.flatten(pinned),
                "noise": pinned["noise"],
                "solos": pinned["solos"],
            }
        )
    )
    monkeypatch.setattr(error_taxonomy, "BASELINE", pin)
    now = aggregate({"merged": 9, "gated": 6})
    now["solos"] = {
        f"s{i}": {
            "family": "horn",
            "note_f1": 0.8,
            "counts": {"merged": 1 if i else 6, "gated": (1 if i < 2 else 0) + 1},
        }
        for i in range(4)
    }
    assert error_taxonomy.compare(now) == 1
    out = capsys.readouterr().out
    gated_line = next(line for line in out.splitlines() if "count/gated" in line)
    merged_line = next(line for line in out.splitlines() if "count/merged" in line)
    assert "paired: beyond 2 se" in gated_line and "up 4 / down 0 of 4" in gated_line
    assert "paired: inside noise" in merged_line and "up 1 / down 0 of 4" in merged_line


# ── the Omnibook block: pinned apart, compared apart ──────────────────────


def test_a_section_is_compared_against_its_own_block(tmp_path, monkeypatch, capsys):
    wjazzd = aggregate({"merged": 4})
    omnibook = aggregate({"octave": 9, "squeezed": 3})
    pin = tmp_path / "baseline.json"
    pin.write_text(
        json.dumps(
            {
                "flat": error_taxonomy.flatten(wjazzd),
                "noise": wjazzd["noise"],
                "omnibook": {"flat": error_taxonomy.flatten(omnibook), "noise": omnibook["noise"]},
            }
        )
    )
    monkeypatch.setattr(error_taxonomy, "BASELINE", pin)
    assert error_taxonomy.compare(omnibook, "omnibook") == 0
    assert "[omnibook]" in capsys.readouterr().out
    # The Omnibook's counts against WJazzD's block would read as a change.
    assert error_taxonomy.compare(omnibook) == 1
    moved = aggregate({"octave": 2, "squeezed": 3})
    assert error_taxonomy.compare(moved, "omnibook") == 1


def test_a_section_nobody_pinned_is_not_a_failure(tmp_path, monkeypatch, capsys):
    wjazzd = aggregate({"merged": 4})
    pin = tmp_path / "baseline.json"
    pin.write_text(json.dumps({"flat": error_taxonomy.flatten(wjazzd), "noise": wjazzd["noise"]}))
    monkeypatch.setattr(error_taxonomy, "BASELINE", pin)
    assert error_taxonomy.compare(aggregate({"octave": 9}), "omnibook") == 0
    assert "No `omnibook` block" in capsys.readouterr().out


def test_tempo_bands_are_wjazzds():
    assert error_taxonomy.tempo_band(79.0) == "SLOW"
    assert error_taxonomy.tempo_band(118.0) == "MEDIUM"
    assert error_taxonomy.tempo_band(179.9) == "MEDIUM UP"
    assert error_taxonomy.tempo_band(301.0) == "UP"


def test_a_score_is_placed_by_its_matches_and_its_hits_are_the_alignments():
    from types import SimpleNamespace

    melody = [
        SimpleNamespace(position=q / 2, duration=0.5, pitch=60 + (q * 7) % 12, bar=1 + q // 8)
        for q in range(64)
    ]
    score = SimpleNamespace(melody=melody, pitches=[n.pitch for n in melody])
    # We heard every note but two, on a 0.3 s/quarter clock starting at 12 s.
    estimate = [
        {"onset": 12.0 + 0.3 * n.position, "duration": 0.1, "pitch": n.pitch, "confidence": 0.9}
        for k, n in enumerate(melody)
        if k not in (20, 41)
    ]
    reference, matched, placement = error_taxonomy.score_reference(score, estimate)
    assert len(matched) == 62 and placement["transposition"] == 0
    assert {ri for ri, _ in matched} == set(range(64)) - {20, 41}
    # The two we missed are placed where the clock puts them.
    assert reference[20]["onset"] == pytest.approx(12.0 + 0.3 * 10.0)
    assert reference[41]["onset"] == pytest.approx(12.0 + 0.3 * 20.5)
    assert reference[20]["bar"] == 3 and reference[20]["position"] == 10.0
    assert reference[20]["duration"] == pytest.approx(0.15)


def test_a_head_heard_an_octave_low_sets_the_clock_and_is_not_a_hit():
    from types import SimpleNamespace

    # A line inside one octave, so nothing an octave under it is also in it.
    melody = [
        SimpleNamespace(position=q / 2, duration=0.5, pitch=60 + (q * 5) % 11, bar=1 + q // 8)
        for q in range(96)
    ]
    score = SimpleNamespace(melody=melody, pitches=[n.pitch for n in melody])
    # The first 32 notes come back an octave under the book and on a clock of
    # their own (a rubato head); the rest is heard at pitch in steady time.
    estimate = []
    for k, n in enumerate(melody):
        head = k < 32
        onset = 5.0 + 0.4 * n.position if head else 5.0 + 0.4 * 16 + 0.3 * (n.position - 16)
        estimate.append(
            {
                "onset": onset,
                "duration": 0.1,
                "pitch": n.pitch - (12 if head else 0),
                "confidence": 1,
            }
        )
    reference, matched, placement = error_taxonomy.score_reference(score, estimate)
    assert {ri for ri, _ in matched} == set(range(32, 96))  # the head is not a hit
    assert placement["octave_anchors"] == 32
    # ...but it is placed on the clock it was played on, not the solo's.
    assert reference[10]["onset"] == pytest.approx(5.0 + 0.4 * 5.0)
