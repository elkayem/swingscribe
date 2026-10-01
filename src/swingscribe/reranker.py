"""A6: a learned per-beat re-ranker for the quantizer's grid choice.

docs/reranker.md has the data, the performance model, the training and every
number. In one paragraph: `choose_reading` enumerates the (grid, reading)
pairs a beat could be written under and the shipped rule keeps the coarsest
one within slack of the best (after the figure prior, R33). Every hand rule
tried on top of that since R33 is level or worse on the pages
(docs/writing-round2.md). This module replaces the final PICK, and only the
pick: `choose_reading` hands it the readings every note-keeping guard admits
(each keeps the beat's onsets apart and pushes nothing onto a neighbour's
line), marks the rule's own choice, and writes whichever this model scores
highest. A conditional logit -- one linear score per candidate, softmax
over the beat's candidates -- over features of the candidate (grid, reading,
snap error, the figure it writes, its surprisal on a human page) crossed
with features of the beat and its neighbours (onset count, where its first
and last onsets sound, tempo, the swing reading, the lag, how busy the
beats around it are).

It is trained on SYNTHETIC performances of human transcription pages: the
OMR corpus's dev split, each page played by a performance model fitted to
WJazzD's onsets against its annotated beats (never its Flex-Q tatums, D36).
Weights are a JSON of a few hundred numbers.

Measured on the pages it is NOT an improvement (docs/reranker.md): a model
offered only what the rule may write never reliably moves them, because
there is almost nothing to choose -- an oracle over those readings moves the
triples' (a) rhythm by +0.002 -- and a model offered every reading the
note-keeping guards allow is decided DOWN on the Omnibook in all six judged.
So no weights ship; the hook and this module stay, off, for the day paired
human data (performed onsets beside a human page) can train it.

Pure Python, no numpy, so the quantizer stays CI-light. Off unless
`QuantizeConfig.reranker` names a weights file.
"""

from __future__ import annotations

import functools
import json
import math
from pathlib import Path

FEATURE_SET = "v1"

# Beat length (seconds) bands, onset-count bands, neighbour density bands.
TEMPO_EDGES = (0.22, 0.30, 0.40, 0.55)  # > 273, 200-273, 150-200, 109-150, < 109 bpm
DENSITY_EDGES = (0.75, 1.5, 2.5)
FIRST_EDGES = (0.06, 0.15, 0.30, 0.45)  # where the beat's first raw onset sounds
LAST_EDGES = (0.60, 0.75, 0.88)  # ... and its last
SWING_EDGES = (0.02, 0.08)  # the beat's swing point past straight
THIRDS_FIT = 0.04  # a neighbour of three onsets this close to thirds "looks ternary"

# Figures named one by one (the commonest on the human pages, figure prior);
# the rest share "other".
NAMED_FIGURES = (
    "0 1/2",
    "0",
    "1/2",
    "0 1/4 1/2 3/4",
    "0 1/3 2/3",
    "0 1/2 3/4",
    "1/2 3/4",
    "0 1/4 1/2",
    "0 1/4",
    "1/4 1/2 3/4",
    "1/3",
    "0 2/3",
    "1/3 2/3",
    "0 3/4",
    "3/4",
    "0 1/4 3/4",
    "2/3",
    "1/4 3/4",
    "1/4",
    "1/4 1/2",
    "0 1/3",
    "-",
)
# Figures also crossed with tempo and onset count.
CROSSED_FIGURES = NAMED_FIGURES[:12]


def _band(value: float, edges: tuple[float, ...]) -> int:
    for i, edge in enumerate(edges):
        if value < edge:
            return i
    return len(edges)


def _position_class(position: float) -> str:
    """A written position inside the beat, by name."""
    for name, at in (
        ("0", 0.0),
        ("e", 0.25),
        ("and", 0.5),
        ("a", 0.75),
        ("t1", 1 / 3),
        ("t2", 2 / 3),
        ("next", 1.0),
    ):
        if abs(position - at) < 1e-6:
            return name
    if abs(position * 8 - round(position * 8)) < 1e-6:
        return "32nd"
    return "other"


def _thirds_error(offsets: list[float]) -> float:
    return sum(abs(o * 3 - round(o * 3)) / 3 for o in offsets) / len(offsets)


def beat_features(context: dict) -> dict[str, str | int | float]:
    """What the beat and its neighbours say, once per beat."""
    raw = sorted(context["raw"])
    neighbours = context["neighbours"]
    counts = [len(neighbours.get(k, [])) for k in (-2, -1, 1, 2)]
    density = sum(counts) / 4.0
    busy = sum(1 for k in (-1, 1) if len(neighbours.get(k, [])) >= 4)
    ternary = sum(
        1
        for k in (-1, 1)
        if len(neighbours.get(k, [])) == 3 and _thirds_error(neighbours[k]) <= THIRDS_FIT
    )
    n = len(raw)
    return {
        "n": min(n, 5),
        "t": _band(context["beat_s"], TEMPO_EDGES),
        "d": _band(density, DENSITY_EDGES),
        "n16": busy,
        "n3": ternary,
        "s": _band(context["star"] - 0.5, SWING_EDGES),
        "lag": 1 if context["lag"] > 0 else 0,
        "f": _band(raw[0], FIRST_EDGES) if raw else 0,
        "l": _band(raw[-1], LAST_EDGES) if raw else 0,
        "beat_s": context["beat_s"],
        "prev_late": 1 if any(o >= 0.75 for o in neighbours.get(-1, [])) else 0,
        "next_empty": 1 if not neighbours.get(1) else 0,
    }


def candidate_features(beat: dict, candidate: dict, best_error: float, least_surprise: float):
    """Sparse features of one candidate in its beat: {name: value}."""
    from swingscribe.stages.quantize import figure_prior, figure_surprisal

    divisions = candidate["divisions"]
    straight = candidate["reading"] == "raw" and divisions % 3 != 0
    g = f"{divisions}{'r' if straight else ''}"
    snapped = sorted(candidate["snapped"])
    figure = candidate["figure"]
    surprise = figure_surprisal(figure, figure_prior())
    error = candidate["error"]
    pushed = any(s >= 1.0 - 1e-9 for s in snapped)
    named = figure if figure in NAMED_FIGURES else "other"
    first = _position_class(snapped[0]) if snapped else "none"
    last = _position_class(snapped[-1]) if snapped else "none"
    seconds = beat["beat_s"]
    out: dict[str, float] = {
        f"g:{g}": 1.0,
        "err": error,
        "err_s": error * seconds / 0.02,
        "erel": error - best_error,
        "erel_s": (error - best_error) * seconds / 0.02,
        "surp": surprise,
        "srel": surprise - least_surprise,
        f"fig:{named}": 1.0,
        f"first:{first}|f:{beat['f']}": 1.0,
        f"last:{last}|l:{beat['l']}": 1.0,
        f"g:{g}|n:{beat['n']}": 1.0,
        f"g:{g}|t:{beat['t']}": 1.0,
        f"g:{g}|d:{beat['d']}": 1.0,
        f"g:{g}|n16:{beat['n16']}": 1.0,
        f"g:{g}|n3:{beat['n3']}": 1.0,
        f"g:{g}|s:{beat['s']}": 1.0,
        f"g:{g}|lag:{beat['lag']}": 1.0,
        f"first:{first}|lag:{beat['lag']}": 1.0,
    }
    if not candidate.get("gated", True):
        # A reading the convention gates refuse, offered to an "open" model.
        out["ungated"] = 1.0
        out[f"ungated|g:{g}"] = 1.0
        out[f"ungated|g:{g}|n:{beat['n']}"] = 1.0
        out[f"ungated|g:{g}|t:{beat['t']}"] = 1.0
        out[f"ungated|g:{g}|n3:{beat['n3']}"] = 1.0
    if candidate["baseline"]:
        out["base"] = 1.0
        out[f"base|n:{beat['n']}"] = 1.0
        out[f"base|t:{beat['t']}"] = 1.0
    if pushed:
        out["push"] = 1.0
        out[f"push|t:{beat['t']}"] = 1.0
        out[f"push|prev_late:{beat['prev_late']}"] = 1.0
    if figure in CROSSED_FIGURES:
        out[f"fig:{figure}|t:{beat['t']}"] = 1.0
        out[f"fig:{figure}|d:{beat['d']}"] = 1.0
    return out


def featurize(context: dict, candidates: list[dict]) -> list[dict[str, float]]:
    beat = beat_features(context)
    from swingscribe.stages.quantize import figure_prior, figure_surprisal

    table = figure_prior()
    best = min(c["error"] for c in candidates)
    least = min(figure_surprisal(c["figure"], table) for c in candidates)
    return [candidate_features(beat, c, best, least) for c in candidates]


class Model:
    """A linear score per candidate; the highest wins, the rule's pick on a tie."""

    def __init__(self, weights: dict[str, float], meta: dict | None = None):
        self.weights = weights
        self.meta = meta or {}
        # Trained on every reading the note-keeping guards allow, the
        # convention gates lifted (quantize passes `rerank_grids`).
        self.open = bool(self.meta.get("open", False))

    def scores(self, context: dict, candidates: list[dict]) -> list[float]:
        w = self.weights
        return [
            sum(w.get(name, 0.0) * value for name, value in features.items())
            for features in featurize(context, candidates)
        ]

    def choose(self, context: dict, candidates: list[dict]) -> int | None:
        scores = self.scores(context, candidates)
        best = max(range(len(candidates)), key=lambda i: scores[i])
        base = next((i for i, c in enumerate(candidates) if c["baseline"]), None)
        if base is not None and (best == base or scores[best] <= scores[base] + 1e-12):
            return None
        return best


def save_model(path: Path, weights: dict[str, float], meta: dict) -> None:
    kept = {k: round(v, 6) for k, v in sorted(weights.items()) if abs(v) >= 1e-6}
    payload = {"feature_set": FEATURE_SET, "meta": meta, "weights": kept}
    path.write_text(json.dumps(payload, indent=1, sort_keys=False) + "\n", encoding="utf-8")


@functools.lru_cache(maxsize=4)
def load_model(spec: str) -> Model:
    """The model in the weights JSON at path `spec`. Read once per process."""
    path = Path(spec)
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("feature_set") != FEATURE_SET:
        raise ValueError(
            f"{path}: feature set {data.get('feature_set')!r}, this code computes {FEATURE_SET!r}"
        )
    weights = {k: float(v) for k, v in data["weights"].items() if math.isfinite(float(v))}
    return Model(weights, data.get("meta", {}))
