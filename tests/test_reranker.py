"""A6's re-ranker hook in the quantizer, and the model behind it.

Pure arithmetic like the rest of quantize: the hook, the features and the
linear model run in CI. What is held here is the CONTRACT
(docs/reranker.md), not the model's quality, which is measured on human
pages by scripts/reranker_eval.py:

- off by default, and dumping nothing at its default, so no quantize key
  and no pin moves;
- a hook that defers changes nothing;
- whatever the model picks, every heard note is still on the page: it is
  only ever offered readings that keep the beat's onsets apart and push
  nothing onto a neighbour's own note, gated or "open".
"""

import json
import random

import pytest

from swingscribe import reranker
from swingscribe.config import QuantizeConfig
from swingscribe.stages.quantize import (
    choose_reading,
    quantize_notes,
    settings,
    snap,
)
from swingscribe.stages.swing import swing_spans

FIGURES = (
    (0.0, 0.5),
    (0.0, 0.5),
    (0.0,),
    (0.5,),
    (0.0, 1 / 3, 2 / 3),
    (1 / 3, 2 / 3),
    (0.0, 0.25, 0.5, 0.75),
    (0.0, 0.5, 0.75),
    (0.25, 0.5),
)


def _line(bpm=200.0, beats=96, phi=0.58, jitter=0.04, seed=0):
    """A swung line of mixed figures, played with jitter in beats."""
    rng = random.Random(seed)
    beat_s = 60.0 / bpm
    grid = [i * beat_s for i in range(beats + 3)]
    onsets = []
    for b in range(1, beats + 1):
        figure = rng.choice(FIGURES)
        for f in figure:
            phase = phi if f == 0.5 and len(figure) <= 2 else f
            onsets.append((b + phase + rng.gauss(0.0, jitter)) * beat_s)
    onsets.sort()
    kept = []
    for t in onsets:
        if not kept or t - kept[-1] > 0.02:
            kept.append(t)
    return kept, grid


def _quantize(onsets, grid, **overrides):
    spans = swing_spans(onsets, grid)
    kwargs = {**settings(QuantizeConfig()), **overrides}
    return quantize_notes(
        onsets, [0.1] * len(onsets), [60] * len(onsets), grid, spans, [], **kwargs
    )


def _written(notes):
    return [(n.bar, round(n.beat, 6)) for n in notes]


class Picker:
    """A stand-in model: records what it is offered and picks by `rule`."""

    def __init__(self, rule, open_=False):
        self.rule = rule
        self.open = open_
        self.offered = []

    def choose(self, context, candidates):
        self.offered.append((context, candidates))
        return self.rule(candidates)


# ── the switch ──────────────────────────────────────────────────────────────


def test_reranker_is_off_by_default_and_dumps_nothing():
    qc = QuantizeConfig()
    assert qc.reranker == ""
    assert "reranker" not in qc.model_dump()
    assert QuantizeConfig(reranker="w.json").model_dump()["reranker"] == "w.json"
    assert settings(qc)["reranker"] == ""


def test_a_deferring_hook_changes_nothing():
    onsets, grid = _line(seed=1)
    off, _ = _quantize(onsets, grid)
    picker = Picker(lambda candidates: None)
    on, _ = _quantize(onsets, grid, reranker=picker)
    assert picker.offered, "the hook was never asked"
    assert _written(on) == _written(off)
    assert [n.duration_beats for n in on] == [n.duration_beats for n in off]


def test_choose_reading_without_a_hook_is_unchanged():
    for offsets in ([0.0, 0.55], [0.0, 0.31, 0.68], [0.1, 0.4, 0.62, 0.8], [0.7]):
        plain = choose_reading(offsets, (2, 4, 3), raw_offsets=offsets, star=0.6)
        hooked = choose_reading(
            offsets, (2, 4, 3), raw_offsets=offsets, star=0.6, rerank=lambda c: None
        )
        assert plain == hooked


# ── never a lost note ───────────────────────────────────────────────────────


def _keeps_every_note(candidates):
    for c in candidates:
        snapped = [round(s, 9) for s in c["snapped"]]
        assert len(set(snapped)) == len(snapped)


@pytest.mark.parametrize("open_", [False, True])
@pytest.mark.parametrize("pick", ["finest", "coarsest", "last", "ternary"])
def test_any_pick_keeps_every_heard_note(open_, pick):
    rules = {
        "finest": lambda cs: max(range(len(cs)), key=lambda i: cs[i]["divisions"]),
        "coarsest": lambda cs: min(range(len(cs)), key=lambda i: cs[i]["divisions"]),
        "last": lambda cs: len(cs) - 1,
        "ternary": lambda cs: next((i for i, c in enumerate(cs) if c["divisions"] % 3 == 0), None),
    }
    for seed in range(4):
        onsets, grid = _line(seed=seed, jitter=0.06)
        off, _ = _quantize(onsets, grid)
        picker = Picker(rules[pick], open_)
        on, _ = _quantize(onsets, grid, reranker=picker)
        for _context, candidates in picker.offered:
            _keeps_every_note(candidates)
        # Every note placed, and never fewer distinct written positions than
        # the rule's own page (the rule itself can merge two notes where no
        # grid keeps a crowded beat apart; the hook is never asked there).
        assert len(on) == len(off)
        assert len(set(_written(on))) >= len(set(_written(off)))


def test_a_reading_that_pushes_onto_the_next_beats_note_is_never_offered():
    # The beat's last onset at 0.8 would go to the next beat line, where the
    # next beat has its own note: no offered reading may send it there.
    offsets = [0.0, 0.8]
    seen = []
    choose_reading(
        offsets,
        (2, 4, 3),
        raw_offsets=offsets,
        star=0.6,
        next_occupied=True,
        prior_weight=0.015,
        rerank=lambda cs: seen.extend(cs) or None,
        rerank_grids=(2, 4, 3),
    )
    assert seen
    assert all(max(c["snapped"]) < 1.0 for c in seen)


def test_open_offers_what_the_convention_gates_refuse():
    # Two onsets at the second and third of a triplet: the tuplet gate needs
    # three, so the rule cannot write thirds; an open model is offered them.
    offsets = [1 / 3 + 0.01, 2 / 3 - 0.01]
    gated, opened = [], []
    choose_reading(
        offsets, (2, 4, 3), raw_offsets=offsets, star=0.6, rerank=lambda cs: gated.extend(cs)
    )
    choose_reading(
        offsets,
        (2, 4, 3),
        raw_offsets=offsets,
        star=0.6,
        rerank=lambda cs: opened.extend(cs),
        rerank_grids=(2, 4, 3),
    )
    assert not any(c["divisions"] == 3 for c in gated)
    thirds = [c for c in opened if c["divisions"] == 3]
    assert thirds and not thirds[0]["gated"]
    assert any(c["baseline"] for c in opened)


def test_a_pick_is_written():
    offsets = [1 / 3 + 0.01, 2 / 3 - 0.01]
    divisions, reading = choose_reading(
        offsets,
        (2, 3),
        raw_offsets=offsets,
        star=0.6,
        rerank=lambda cs: next(i for i, c in enumerate(cs) if c["divisions"] == 3),
        rerank_grids=(2, 4, 3),
    )
    assert (divisions, reading) == (3, "raw")
    assert [snap(o, 3)[0] for o in offsets] == [1 / 3, 2 / 3]


# ── the model ───────────────────────────────────────────────────────────────


def _context(raw, star=0.58, lag=0.0, beat_s=0.3):
    return {
        "index": 10,
        "time": 3.0,
        "offsets": raw,
        "raw": raw,
        "star": star,
        "track_phase": star,
        "lag": lag,
        "beat_s": beat_s,
        "neighbours": {-2: [0.0, 0.6], -1: [0.0, 0.33, 0.66], 1: [0.0], 2: []},
    }


def _candidates():
    return [
        {
            "divisions": 4,
            "reading": "warped",
            "values": [0.33, 0.66],
            "snapped": [0.25, 0.75],
            "error": 0.08,
            "figure": "1/4 3/4",
            "baseline": True,
            "gated": True,
        },
        {
            "divisions": 3,
            "reading": "raw",
            "values": [0.33, 0.66],
            "snapped": [1 / 3, 2 / 3],
            "error": 0.003,
            "figure": "1/3 2/3",
            "baseline": False,
            "gated": False,
        },
    ]


def test_features_are_sparse_names_and_values():
    rows = reranker.featurize(_context([0.33, 0.66]), _candidates())
    assert len(rows) == 2
    assert rows[0]["base"] == 1.0 and "base" not in rows[1]
    assert rows[1]["ungated"] == 1.0
    assert "g:4" in rows[0] and "g:3" in rows[1]
    assert rows[1]["fig:1/3 2/3"] == 1.0
    assert all(isinstance(v, float) for row in rows for v in row.values())


def test_the_model_defers_on_a_tie_and_picks_a_better_score():
    candidates = _candidates()
    context = _context([0.33, 0.66])
    assert reranker.Model({}).choose(context, candidates) is None
    assert reranker.Model({"g:3": 1.0}).choose(context, candidates) == 1
    assert reranker.Model({"base": 5.0, "g:3": 1.0}).choose(context, candidates) is None


def test_weights_round_trip_and_the_feature_set_is_checked(tmp_path):
    path = tmp_path / "w.json"
    reranker.save_model(path, {"g:3": 0.5, "base": 0.25, "tiny": 1e-9}, {"open": True})
    model = reranker.load_model(str(path))
    assert model.open and model.weights == {"g:3": 0.5, "base": 0.25}
    data = json.loads(path.read_text(encoding="utf-8"))
    data["feature_set"] = "v0"
    other = tmp_path / "old.json"
    other.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        reranker.load_model(str(other))


def test_a_weights_path_in_config_reaches_the_quantizer(tmp_path):
    path = tmp_path / "w.json"
    # A model that always prefers thirds where it may: open, ternary-loving.
    reranker.save_model(path, {"g:3": 5.0}, {"open": True})
    onsets, grid = _line(seed=2)
    off, _ = _quantize(onsets, grid)
    on, _ = _quantize(onsets, grid, reranker=str(path))
    assert len(on) == len(off)
    assert len(set(_written(on))) >= len(set(_written(off)))
    thirds = sum(1 for n in on if abs(n.beat * 3 - round(n.beat * 3)) < 1e-6 and n.beat % 1)
    thirds_off = sum(1 for n in off if abs(n.beat * 3 - round(n.beat * 3)) < 1e-6 and n.beat % 1)
    assert thirds > thirds_off
