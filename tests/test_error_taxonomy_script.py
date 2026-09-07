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
