"""Where are the solos? Score `swingscribe.solo_spans` against WJazzD.

    uv run python scripts/solo_spans_survey.py --db wjazz/wjazzd.db

Roadmap O3 (docs/roadmap.md): propose a solo's A and B instead of asking a
new listener to find them. The reference is WJazzD: 77 solos annotated on
the 49 distinct recordings under benchmark/wjazzd/ (74 files, several of
them byte-identical copies of one track, one per annotated soloist). Each
solo is placed in OUR audio's timeline by the batch's content fit (the
sidecar's `region`, first and last annotated onset with a one-second
margin); the three annotated solos on those tracks with no copy on disk are
placed from WJazzD's `solostart_sec` corrected by their located siblings.

What is read: the whole-file htdemucs_6s stems the batch located with
(the stage cache under benchmark/.swingscribe-cache; Gingerbread Boy has
only a Roformer set), reduced to tenth-of-a-second envelopes and cached in
benchmark/.solo-spans/ (gitignored, like everything derived from the
recordings), and the harness's tracked beat grids (.benchmark-grids.json)
repaired through `meter.bar_grid` under the DEFAULT meter -- what a new
listener's track has before they set anything. No separation, no CREPE.

What is printed, all aggregates (plan section 12):

1. the reference: how many edges, how they were placed, and the ceiling a
   chorus-line proposer has against a first onset that is a pickup;
2. the shipped proposer at its defaults and the penalty's whole curve; the
   same proposals under mir_eval's ONE-TO-ONE matching and which edges that
   loses; and a chance control at the same boundary count;
3. two-fold cross-validation by recording: of the penalty, then jointly of
   the penalty, the minimum segment and the head edges;
4. ablations (no head cue; the head-out edge as well);
5. recall by kind of edge, and what the head edge does, counted without
   selecting on the answer;
6. the lead-stem label: against the soloist's instrument, and against the
   stem whose chroma follows WJazzD's annotated line -- on both separations;
7. the Roformer against htdemucs_6s where both whole-file sets exist;
8. the Omnibook: the end of Parker's chorus(es), the one edge its located
   regions give, on whatever whole-file stems exist;
9. a form-length estimate from the bass stem's chroma, which is NOT
   shipped (it reads the chorus length right on about half the tunes).

Measured 2026-09-30 (docs/solo-spans.md has the numbers). About a minute
with the envelopes cached; the first run reads every stem set (about six
seconds each, 87 sets).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from swingscribe import solo_spans  # noqa: E402

BENCH = Path("benchmark")
WJAZZD = BENCH / "wjazzd"
OMNIBOOK = BENCH / "Omnibook"
CACHE = BENCH / ".swingscribe-cache"
GRIDS = Path(".benchmark-grids.json")
WORK = BENCH / ".solo-spans"
# The batch's located region is the solo's first and last annotated onset
# with this much margin either side (scripts/wjazz_batch.py SOLO_MARGIN_S).
SOLO_MARGIN_S = 1.0
# The survey also keeps the bass and piano chroma, for the form-length
# experiment (section 9) and the line check (section 6); the proposer reads
# only the horn stems'.
SURVEY_CHROMA = ("bass", "guitar", "other", "piano", "vocals")
ENVELOPE_VERSION = "v3"
PENALTIES = (2.0, 3.0, 4.0, 5.0, 6.0, 8.0)
MIN_BARS = (4, 8, 12)
HEAD_EDGES = ("none", "in", "in+out")
HORNS = {"as", "ts", "ss", "bs", "tp", "tb", "cor", "cl", "bcl", "fl"}
# A solo that starts within this many seconds of another's end is a handover
# -- or up to HANDOVER_OVERLAP_S before it: an edge is a first onset or a
# last note-off, and Red Garland's first note on Oleo sounds 0.04 s before
# Coltrane's last one ends. The 21 handovers run -0.04 to +3.7 s; the next
# gap is 15 s (Coltrane's two solos on My Favorite Things, Tyner between).
HANDOVER_S = 8.0
HANDOVER_OVERLAP_S = 1.0
# The chance control's draws, and the line check's frame (in envelope hops).
CHANCE_DRAWS = 200
LINE_POOL = 5
# A lead label whose line correlation is this far under the best stem's is
# clearly wrong; nearer, the line is shared between stems.
LINE_MARGIN = 0.1

DEFAULT = (solo_spans.PENALTY, solo_spans.MIN_BARS, solo_spans.HEAD_EDGES)


# ── the reference ────────────────────────────────────────────────────────────


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def melid_of(path: Path) -> int | None:
    found = re.search(r"_(\d+)$", path.stem)
    return int(found.group(1)) if found else None


def stems_dir(source_digest: str, model: str) -> Path | None:
    """The whole-file stem set for a source file, through its ingest wav.

    Stems are keyed by the NORMALIZED wav's digest, the wav by the source
    file's (CLAUDE.md), so naming one takes the join.
    """
    wav = CACHE / "audio" / f"{source_digest}-44100.wav"
    if not wav.is_file():
        return None
    directory = CACHE / "stems" / f"{digest(wav)}-{model}"
    return directory if directory.is_dir() and any(directory.glob("*.wav")) else None


def recordings(db) -> list[dict]:
    """The benchmark's WJazzD recordings: one entry per distinct audio file."""
    groups: dict[str, list[Path]] = defaultdict(list)
    for path in sorted(WJAZZD.glob("*.m4a")):
        if melid_of(path) is not None:
            groups[digest(path)].append(path)
    out = []
    for source, paths in sorted(groups.items(), key=lambda item: item[1][0].name):
        tracks = {
            row[0]
            for p in paths
            for row in db.execute("select trackid from solo_info where melid=?", (melid_of(p),))
        }
        out.append(
            {
                "name": paths[0].name,
                "key": f"wjazzd/{paths[0].name}",
                "source": source,
                "paths": paths,
                "trackids": sorted(tracks),
                "htdemucs_6s": stems_dir(source, "htdemucs_6s"),
                "bsroformer_sw": stems_dir(source, "bsroformer_sw"),
            }
        )
    return out


def annotated_solos(db, rec: dict) -> list[dict]:
    """Every annotated solo on the recording, placed in OUR audio's timeline.

    The batch located each solo it has a copy of by content (the sidecar's
    `region`). A solo on the same track with no copy on disk is placed from
    WJazzD's own `solostart_sec` -- where its excerpt starts in the original
    track -- corrected by the offset its located siblings show, fitted as a
    line in time when two or more siblings allow it (a transfer at another
    speed drifts: So What's three located solos read +2.3, +4.2, +6.3 s
    against the original track).
    """
    q = ",".join(str(t) for t in rec["trackids"])
    rows = db.execute(
        "select s.melid, s.performer, s.instrument, t.solostart_sec from solo_info s "
        f"join transcription_info t on s.melid=t.melid where s.trackid in ({q})"
    ).fetchall()
    sidecars = {}
    for path in rec["paths"]:
        side = json.loads(Path(str(path) + ".swingscribe.json").read_text(encoding="utf-8"))
        if side.get("region") and side.get("melid") == melid_of(path):
            sidecars[side["melid"]] = side
    solos = []
    for melid, performer, instrument, start_sec in rows:
        first, last_end = db.execute(
            "select min(onset), max(onset+duration) from melody where melid=?", (melid,)
        ).fetchone()
        solo = {
            "melid": melid,
            "performer": performer,
            "instrument": instrument,
            "first_onset": first,
            "original_start": start_sec + first,
            "original_end": start_sec + last_end,
        }
        side = sidecars.get(melid)
        if side:
            lo, hi = side["region"]
            solo.update(start=lo + SOLO_MARGIN_S, end=hi - SOLO_MARGIN_S, placed_by="located")
        solos.append(solo)
    located = [s for s in solos if "start" in s]
    for solo in solos:
        if "start" in solo:
            continue
        xs = np.array([s["original_start"] for s in located])
        ys = np.array([s["start"] - s["original_start"] for s in located])
        slope, intercept = np.polyfit(xs, ys, 1) if len(located) >= 2 else (0.0, float(ys.mean()))
        solo["start"] = float(solo["original_start"] * (1 + slope) + intercept)
        solo["end"] = float(solo["original_end"] * (1 + slope) + intercept)
        solo["placed_by"] = "original-track time"
    for solo in solos:
        solo["offset"] = solo["start"] - solo["original_start"]
        # WJazzD's own chorus lines, carried into our timeline by the shift
        # that places the solo's first onset.
        shift = solo["start"] - solo["first_onset"]
        starts: dict[int, float] = {}
        for onset, chorus in db.execute(
            "select onset, chorus_id from beats where melid=? and chorus_id>0 order by onset",
            (solo["melid"],),
        ):
            starts.setdefault(chorus, onset + shift)
        solo["chorus_starts"] = [starts[k] for k in sorted(starts)]
    return sorted(solos, key=lambda s: s["start"])


def envelopes(key: str, directory: Path | None, model: str) -> solo_spans.StemEnvelopes | None:
    """The stems' envelopes, cached under benchmark/ (gitignored)."""
    if directory is None:
        return None
    WORK.mkdir(parents=True, exist_ok=True)
    cached = WORK / f"{key}-{model}-{ENVELOPE_VERSION}.npz"
    if cached.is_file():
        data = np.load(cached)
        return solo_spans.StemEnvelopes(
            hop_s=float(data["hop_s"]),
            edges_hz=data["edges_hz"],
            power={k[6:]: data[k] for k in data.files if k.startswith("power_")},
            chroma={k[7:]: data[k] for k in data.files if k.startswith("chroma_")},
        )
    paths = {p.stem: p for p in directory.glob("*.wav") if "+" not in p.stem}
    env = solo_spans.stem_envelopes(paths, chroma_stems=SURVEY_CHROMA)
    np.savez_compressed(
        cached,
        hop_s=env.hop_s,
        edges_hz=env.edges_hz,
        **{f"power_{k}": v for k, v in env.power.items()},
        **{f"chroma_{k}": v for k, v in env.chroma.items()},
    )
    return env


def bar_grid(grid: dict) -> tuple[np.ndarray, np.ndarray]:
    """(repaired beats, bar lines) under the default meter, as a new listener
    has them: no time signature, no downbeat, no sidecar."""
    from swingscribe.config import Config
    from swingscribe.stages import meter

    config = Config()
    duration = grid.get("duration") or grid["beats"][-1]
    beats, sections = meter.bar_grid(
        grid["beats"], grid.get("downbeats", []), config.meter, duration
    )
    lines = [t for t, _ in meter.bar_lines(beats, sections)]
    return np.array([b.time for b in beats]), np.array(lines)


def bar_seconds(beats: np.ndarray, pulses: int = 4):
    """t -> the length of the bar there, from the local median beat."""

    def at(t: float) -> float:
        i = int(np.searchsorted(beats, t))
        lo, hi = max(0, i - 4), min(len(beats) - 1, i + 4)
        if hi <= lo:
            return 2.0
        return pulses * float(np.median(np.diff(beats[lo : hi + 1])))

    return at


# ── scoring ──────────────────────────────────────────────────────────────────


class Prepared:
    """One recording's features, head and reference, computed once so a
    penalty sweep only re-runs the partitioning."""

    def __init__(self, rec: dict, env: solo_spans.StemEnvelopes, grid: dict, model: str):
        self.rec, self.env, self.model = rec, env, model
        self.beats, self.lines = bar_grid(grid)
        self.bar = bar_seconds(self.beats)
        self.features = solo_spans.bar_features(env, self.lines)
        self.head = solo_spans.find_head(solo_spans.bar_chroma(env, self.lines))
        self.cuts: dict[tuple[float, int], list[int]] = {}

    @property
    def track(self) -> tuple[float, float]:
        return float(self.lines[0]), float(self.lines[-1])

    def boundaries(self, penalty: float, min_bars: int, head_edges: str) -> list[float]:
        key = (penalty, min_bars)
        if key not in self.cuts:
            d = self.features.shape[1]
            self.cuts[key] = solo_spans.segment(self.features, penalty * d, min_bars)
        chosen = solo_spans.combine(self.cuts[key], self.head, len(self.features), head_edges)
        return [float(self.lines[k]) for k in sorted(chosen)]


def edges_of(solos) -> list[tuple[float, float]]:
    return [(s["start"], s["end"]) for s in solos]


def score(p: Prepared, solos, penalty, min_bars=solo_spans.MIN_BARS, head_edges=DEFAULT[2]):
    return solo_spans.score_boundaries(
        p.boundaries(penalty, min_bars, head_edges), edges_of(solos), p.bar, track=p.track
    )


def summarize(scores: list, label: str) -> dict:
    hits = np.array([h for s in scores for h in s.hits], dtype=bool).reshape(-1, 2, 3)
    starts, ends = hits[:, 0, :], hits[:, 1, :]
    both = starts & ends
    row = {
        "label": label,
        "solos": len(hits),
        "start": starts.mean(axis=0).round(3).tolist(),
        "end": ends.mean(axis=0).round(3).tolist(),
        "both": both.mean(axis=0).round(3).tolist(),
        "inside": sum(s.inside for s in scores),
        "outside": sum(s.outside for s in scores),
    }
    edges_hit = int(hits[:, :, 1].sum())
    row["f1"] = round(f_beta(edges_hit, 2 * len(hits), row["inside"], 1.0), 3)
    row["f2"] = round(f_beta(edges_hit, 2 * len(hits), row["inside"], 2.0), 3)
    return row


def f_beta(hit: int, edges: int, inside: int, beta: float) -> float:
    """Edges found (two bars) against proposals that are wrong for certain.

    Proposals outside every annotated solo are left out on both sides: the
    reference cannot say whether they are right. The penalty is chosen on
    F2, which weighs a missed edge four times a false one, and that was
    decided before any fold was scored: a false boundary inside a solo costs
    the listener a drag across it, a missed one costs finding it by ear.
    """
    recall = hit / edges if edges else 0.0
    precision = hit / (hit + inside) if hit + inside else 0.0
    b2 = beta * beta
    denominator = b2 * precision + recall
    return (1 + b2) * precision * recall / denominator if denominator else 0.0


def fmt(xs) -> str:
    return "/".join(f"{x:.2f}" for x in xs)


def show(row: dict) -> str:
    return (
        f"{row['label']:<34s} n={row['solos']:3d}  start {fmt(row['start'])}  "
        f"end {fmt(row['end'])}  both {fmt(row['both'])}  "
        f"wrong-inside {row['inside']:3d}  unjudged-outside {row['outside']:3d}  "
        f"F1 {row['f1']:.3f} F2 {row['f2']:.3f}"
    )


def handover_partner(solos, i: int, side: int) -> dict | None:
    """The annotated solo across edge (i, side) within HANDOVER_S, if any."""
    s = solos[i]
    for o in solos:
        if o is s:
            continue
        gap = s["start"] - o["end"] if side == 0 else o["start"] - s["end"]
        if -HANDOVER_OVERLAP_S <= gap <= HANDOVER_S:
            return o
    return None


# ── section 2: one-to-one, and chance ───────────────────────────────────────


def one_to_one(prepared, out: dict) -> None:
    """The default's proposals under mir_eval's one-to-one matching, and
    which edges the one-to-one count loses."""
    many, single = [], []
    lost = Counter()
    for p, solos in prepared:
        proposed = p.boundaries(*DEFAULT)
        sc = solo_spans.score_boundaries(proposed, edges_of(solos), p.bar, track=p.track)
        matched = solo_spans.match_boundaries(proposed, edges_of(solos), p.bar, track=p.track)
        many.extend(sc.hits)
        single.extend(matched)
        for k, (h, m) in enumerate(zip(sc.hits, matched, strict=True)):
            for col, what in ((1, "two bars"), (2, "4 s")):
                if h[col] and not m[col]:
                    kind = "handover" if handover_partner(solos, *divmod(k, 2)) else "other"
                    lost[(what, kind)] += 1
    a = np.array(many, dtype=bool).reshape(-1, 2, 3)
    b = np.array(single, dtype=bool).reshape(-1, 2, 3)
    for label, h in (("many-to-one (shipped count)", a), ("one-to-one (mir_eval)", b)):
        print(
            f"   {label:<30s} start {fmt(h[:, 0].mean(axis=0))}  end {fmt(h[:, 1].mean(axis=0))}"
            f"  edges {fmt(h.reshape(-1, 3).mean(axis=0))}"
        )
    for what in ("two bars", "4 s"):
        total = lost[(what, "handover")] + lost[(what, "other")]
        print(
            f"   one-to-one loses {total} edges within {what}: {lost[(what, 'handover')]} are one "
            f"edge of a handover (another solo within {HANDOVER_S:g} s across it)"
        )
    out["one_to_one"] = {
        "many_to_one_edges": a.reshape(-1, 3).mean(axis=0).round(3).tolist(),
        "one_to_one_edges": b.reshape(-1, 3).mean(axis=0).round(3).tolist(),
        "one_to_one_start": b[:, 0].mean(axis=0).round(3).tolist(),
        "one_to_one_end": b[:, 1].mean(axis=0).round(3).tolist(),
        "lost": {f"{w} {k}": v for (w, k), v in lost.items()},
    }


def chance(prepared, out: dict) -> None:
    """The same number of boundaries per recording, placed without
    listening: uniformly on the interior bar lines, and evenly spaced at a
    random phase. What the proposer's recall is worth above that."""
    rng = np.random.default_rng(0)
    draws: dict[str, list[dict]] = {"uniform": [], "evenly spaced": []}
    counts = [len(p.boundaries(*DEFAULT)) for p, _ in prepared]
    for _ in range(CHANCE_DRAWS):
        placed: dict[str, list] = {"uniform": [], "evenly spaced": []}
        for (p, solos), k in zip(prepared, counts, strict=True):
            bars = len(p.lines) - 1
            k = min(k, bars - 1)
            uniform = rng.choice(np.arange(1, bars), size=k, replace=False)
            step = bars / (k + 1)
            even = step * np.arange(1, k + 1) + rng.uniform(-step / 2, step / 2)
            even = np.unique(np.clip(np.round(even).astype(int), 1, bars - 1))
            for label, picks in (("uniform", uniform), ("evenly spaced", even)):
                placed[label].append(
                    solo_spans.score_boundaries(
                        [float(p.lines[i]) for i in np.sort(picks)],
                        edges_of(solos),
                        p.bar,
                        track=p.track,
                    )
                )
        for label, scores in placed.items():
            draws[label].append(summarize(scores, label))
    out["chance"] = {}
    for label, rows in draws.items():
        start = np.mean([r["start"] for r in rows], axis=0)
        end = np.mean([r["end"] for r in rows], axis=0)
        found = np.array([(r["start"][1] + r["end"][1]) / 2 for r in rows])
        inside = float(np.mean([r["inside"] for r in rows]))
        print(
            f"   chance, {label:<14s} ({CHANCE_DRAWS} draws)  start {fmt(start)}  end {fmt(end)}  "
            f"wrong-inside {inside:.0f}; edges within two bars 95th/max of the draws "
            f"{np.percentile(found, 95):.2f}/{found.max():.2f}"
        )
        out["chance"][label] = {
            "start": start.round(3).tolist(),
            "end": end.round(3).tolist(),
            "inside": round(inside, 1),
            "two_bar_p95": round(float(np.percentile(found, 95)), 3),
            "two_bar_max": round(float(found.max()), 3),
        }


# ── section 6: the lead label against the annotated line ────────────────────


def line_stem(db, solo: dict, env: solo_spans.StemEnvelopes) -> dict[str, float]:
    """Each melodic stem's agreement with WJazzD's annotated line.

    The annotated notes, carried into our timeline by the shift that places
    the solo's first onset, become a pitch-class target on half-second
    frames; each stem's log chroma is correlated with it frame by frame over
    the frames the line sounds in. The stem the horn is in follows the line;
    a stem of bleed follows the comping. Independent of the label, which
    reads energy and never pitch.
    """
    shift = solo["start"] - solo["first_onset"]
    notes = db.execute(
        "select onset, duration, pitch from melody where melid=?", (solo["melid"],)
    ).fetchall()
    frame = env.hop_s * LINE_POOL
    a = int(solo["start"] / frame)
    b = int(solo["end"] / frame) + 1
    target = np.zeros((b - a, 12))
    for onset, duration, pitch in notes:
        t0 = (onset + shift) / frame - a
        t1 = (onset + duration + shift) / frame - a
        for f in range(max(0, int(t0)), min(b - a, int(np.ceil(t1)))):
            target[f, int(round(pitch)) % 12] += 1
    keep = target.sum(axis=1) > 0
    y = target - target.mean(axis=1, keepdims=True)
    y /= np.linalg.norm(y, axis=1, keepdims=True) + 1e-9
    scores = {}
    for stem in solo_spans.MELODIC_STEMS:
        if stem not in env.chroma:
            continue
        c = env.chroma[stem][: env.frames]
        whole = (c.shape[0] // LINE_POOL) * LINE_POOL
        pooled = c[:whole].reshape(-1, LINE_POOL, 12).sum(axis=1)[a:b]
        if pooled.shape[0] < b - a:
            continue
        x = np.log1p(pooled / (np.median(pooled) + 1e-12))
        x = x - x.mean(axis=1, keepdims=True)
        x /= np.linalg.norm(x, axis=1, keepdims=True) + 1e-9
        scores[stem] = float(np.mean((x * y).sum(axis=1)[keep]))
    return scores


def lead_against_line(db, group, label: str, out: dict) -> None:
    """For every LOCATED horn solo: the span label at its middle against the
    stem that follows its annotated line."""
    agree = 0
    total = 0
    labels, best_stems = Counter(), Counter()
    misses = []
    for p, solos in group:
        spans = solo_spans.propose(p.env, p.lines).spans
        for s in solos:
            if s["instrument"] not in HORNS or s["placed_by"] != "located":
                continue
            middle = 0.5 * (s["start"] + s["end"])
            span = next((sp for sp in spans if sp.start <= middle < sp.end), None)
            lead = span.lead if span else "none"
            scores = line_stem(db, s, p.env)
            best = max(scores, key=scores.get)
            total += 1
            labels[lead] += 1
            best_stems[best] += 1
            if lead == best:
                agree += 1
                continue
            margin = scores[best] - scores.get(lead, -1.0)
            misses.append((p.rec["name"][:44], lead, best, margin, scores))
    clear = [m for m in misses if m[3] > LINE_MARGIN]
    print(
        f"   {label}: the label is the stem that follows the annotated line on {agree} of "
        f"{total} located horn solos; clearly not ({LINE_MARGIN:g} or more under it) on "
        f"{len(clear)}, close on {len(misses) - len(clear)}"
    )
    print(f"      labels {dict(labels.most_common())}; line stems {dict(best_stems.most_common())}")
    for name, lead, best, margin, scores in misses:
        rounded = {k: round(v, 2) for k, v in scores.items()}
        print(f"      {name:<44s} label {lead:<7s} line {best:<7s} ({margin:+.2f}) {rounded}")
    out[f"lead_line_{label}"] = {
        "agree": agree,
        "n": total,
        "clearly_wrong": len(clear),
        "close": len(misses) - len(clear),
        "labels": dict(labels),
        "line_stems": dict(best_stems),
    }


# ── the form-length experiment (section 9, not shipped) ─────────────────────

FORM_CANDIDATES = (12, 16, 20, 24, 32, 36, 40, 48, 64)


def form_length(env: solo_spans.StemEnvelopes, lines: np.ndarray) -> int | None:
    """The chorus length in bars whose lag most stands out in the bass
    stem's bar-chroma self-similarity (its value minus its neighbours')."""
    chroma = solo_spans.bar_chroma(env, lines, ("bass",))
    n = len(chroma)
    sim = chroma @ chroma.T
    profile = {lag: float(np.mean(np.diag(sim, lag))) for lag in range(1, min(70, n - 1) + 1)}
    scores = {
        lag: profile[lag] - 0.5 * (profile[lag - 1] + profile[lag + 1])
        for lag in FORM_CANDIDATES
        if lag + 1 in profile
    }
    return max(scores, key=scores.get) if scores else None


def wjazz_chorus_seconds(db, melid: int) -> float | None:
    starts: dict[int, float] = {}
    for onset, chorus in db.execute(
        "select onset, chorus_id from beats where melid=? and chorus_id>0 order by onset", (melid,)
    ):
        starts.setdefault(chorus, onset)
    keys = sorted(starts)
    gaps = [starts[b] - starts[a] for a, b in zip(keys[:-1], keys[1:], strict=False) if b == a + 1]
    return float(np.median(gaps)) if gaps else None


# ── the Omnibook (section 8) ─────────────────────────────────────────────────


def omnibook_sides(wjazz_sources: set[str]) -> list[dict]:
    sides = []
    for sidecar in sorted(OMNIBOOK.glob("*.m4a.swingscribe.json")):
        audio = sidecar.with_name(sidecar.name[: -len(".swingscribe.json")])
        settings = json.loads(sidecar.read_text(encoding="utf-8"))
        if not audio.is_file() or not settings.get("region"):
            continue
        source = digest(audio)
        sides.append(
            {
                "name": audio.name,
                "key": f"Omnibook/{audio.name}",
                "source": source,
                "region": settings["region"],
                "also_in_wjazzd": source in wjazz_sources,
                "htdemucs_6s": stems_dir(source, "htdemucs_6s"),
                "bsroformer_sw": stems_dir(source, "bsroformer_sw"),
            }
        )
    return sides


# ── main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default="wjazz/wjazzd.db")
    parser.add_argument("--json", help="write every printed row here too")
    args = parser.parse_args()
    db = sqlite3.connect(args.db)
    grids = json.loads(GRIDS.read_text(encoding="utf-8"))
    out: dict = {}

    # 1. the reference
    recs = recordings(db)
    prepared: list[tuple[Prepared, list[dict]]] = []
    placed = Counter()
    offsets = []
    pickups, tails = [], []
    for rec in recs:
        solos = annotated_solos(db, rec)
        model = "htdemucs_6s" if rec["htdemucs_6s"] else "bsroformer_sw"
        env = envelopes(rec["source"], rec[model], model)
        if env is None or rec["key"] not in grids:
            print(f"  skipping {rec['name']}: no stems or no grid")
            continue
        p = Prepared(rec, env, grids[rec["key"]], model)
        prepared.append((p, solos))
        for s in solos:
            placed[s["placed_by"]] += 1
            if s["placed_by"] == "located":
                offsets.append(s["offset"])
            cs = s["chorus_starts"]
            if len(cs) >= 2:
                length = float(np.median(np.diff(cs)))
                chorus_lines = [cs[0] + k * length for k in range(len(cs) + 2)]
                pickups.append((s["start"] - cs[0]) / p.bar(s["start"]))
                end_line = min(chorus_lines, key=lambda t: abs(t - s["end"]))
                tails.append((s["end"] - end_line) / p.bar(s["end"]))
    n_solos = sum(len(s) for _, s in prepared)
    models = Counter(p.model for p, _ in prepared)
    offsets = np.array(offsets)
    pickups, tails = np.abs(pickups), np.abs(tails)
    print(f"1. {len(prepared)} recordings, {n_solos} annotated solos, {2 * n_solos} edges")
    print(f"   placed: {dict(placed)}; stems: {dict(models)}")
    worst = offsets[np.argmax(np.abs(offsets))]
    print(
        "   located start minus WJazzD's original-track start: "
        f"median {np.median(offsets):+.2f} s, |.| <= 1 s on {np.mean(np.abs(offsets) <= 1):.0%} "
        f"of {len(offsets)}; the rest are transfers at another speed or a wrong "
        f"solostart_sec (largest {worst:+.1f} s)"
    )
    print(
        f"   first onset within 1/2 bars of WJazzD's first chorus line: "
        f"{np.mean(pickups <= 1):.2f}/{np.mean(pickups <= 2):.2f}; last note within 1/2 bars of a "
        f"chorus line: {np.mean(tails <= 1):.2f}/{np.mean(tails <= 2):.2f} (n={len(pickups)}) -- "
        "the ceiling of a proposer that cuts on chorus lines, against the one-bar reading"
    )
    handovers = sum(
        handover_partner(solos, i, 0) is not None
        for _, solos in prepared
        for i in range(len(solos))
    )
    print(
        f"   {handovers} handovers (an annotated solo ending at most {HANDOVER_S:g} s before one "
        f"starts, or {HANDOVER_OVERLAP_S:g} s after)"
    )
    out["reference"] = {
        "recordings": len(prepared),
        "solos": n_solos,
        "placed": dict(placed),
        "handovers": handovers,
        "chorus_line_ceiling": {
            "n": len(pickups),
            "start_1bar": round(float(np.mean(pickups <= 1)), 3),
            "start_2bar": round(float(np.mean(pickups <= 2)), 3),
            "end_1bar": round(float(np.mean(tails <= 1)), 3),
            "end_2bar": round(float(np.mean(tails <= 2)), 3),
        },
    }

    # 2. defaults and the curve
    print(
        f"\n2. the proposer (hits within one bar / two bars / 4 s); defaults penalty "
        f"{DEFAULT[0]:g}, min {DEFAULT[1]} bars, head edges {DEFAULT[2]!r}"
    )
    rows = []
    for penalty in PENALTIES:
        scores = [score(p, s, penalty) for p, s in prepared]
        mark = "  <- default" if penalty == solo_spans.PENALTY else ""
        row = summarize(scores, f"penalty {penalty:g}{mark}")
        row["boundaries"] = sum(
            len(p.boundaries(penalty, DEFAULT[1], DEFAULT[2])) for p, _ in prepared
        )
        rows.append(row)
        print("   " + show(row) + f"  boundaries {row['boundaries']}")
    out["curve"] = rows
    minutes = sum(s["end"] - s["start"] for _, solos in prepared for s in solos) / 60
    default = next(r for r in rows if "default" in r["label"])
    total = default["boundaries"]
    print(
        f"   at the default: {total} boundaries on {len(prepared)} recordings "
        f"({total / len(prepared):.1f} each); {default['inside']} of them inside the "
        f"{minutes:.0f} annotated solo-minutes ({default['inside'] / minutes:.2f} a minute)"
    )
    whole = clean = 0
    for p, solos in prepared:
        times = p.boundaries(*DEFAULT)
        sc = score(p, solos, solo_spans.PENALTY)
        for i, solo in enumerate(solos):
            if sc.hits[2 * i][1] and sc.hits[2 * i + 1][1]:
                whole += 1
                lo = solo["start"] + 2 * p.bar(solo["start"])
                hi = solo["end"] - 2 * p.bar(solo["end"])
                clean += not any(lo < t < hi for t in times)
    print(
        f"   {whole} of {n_solos} solos have both edges within two bars; {clean} of them are "
        "ONE proposed span (no boundary inside) -- a single click"
    )
    out["one_click"] = {"both_edges": whole, "single_span": clean, "solos": n_solos}
    # Which side of the note a found boundary falls on: a proposal on the
    # bar line before a pickup is a better A than one on the first note.
    signed: dict[str, list[float]] = {"start": [], "end": []}
    for p, solos in prepared:
        times = np.array([p.track[0], *p.boundaries(*DEFAULT), p.track[1]])
        for solo in solos:
            for side in signed:
                gaps = times - solo[side]
                k = int(np.argmin(np.abs(gaps)))
                if abs(gaps[k]) <= 4 * p.bar(solo[side]):
                    signed[side].append(gaps[k] / p.bar(solo[side]))
    for side, values in signed.items():
        q = np.percentile(values, [10, 25, 50, 75, 90])
        print(
            f"   {side}s found within four bars (n={len(values)}): proposal minus note, in bars, "
            f"percentiles 10/25/50/75/90 = {' / '.join(f'{v:+.2f}' for v in q)}"
        )
    out["signed_error_bars"] = {
        side: np.percentile(v, [10, 25, 50, 75, 90]).round(2).tolist() for side, v in signed.items()
    }
    one_to_one(prepared, out)
    chance(prepared, out)

    # 3. cross-validation, by recording
    print("\n3. two-fold cross-validation on F2 (folds alternate by recording)")
    folds = [prepared[0::2], prepared[1::2]]
    for name, grid in (
        ("the penalty", [(pen, DEFAULT[1], DEFAULT[2]) for pen in PENALTIES]),
        (
            "penalty x min bars x head edges",
            [(pen, mb, he) for pen in PENALTIES for mb in MIN_BARS for he in HEAD_EDGES],
        ),
    ):
        held = []
        chosen = []
        for k, (train, test) in enumerate(((folds[0], folds[1]), (folds[1], folds[0]))):
            best = max(
                grid,
                key=lambda cfg, train=train: summarize([score(p, s, *cfg) for p, s in train], "")[
                    "f2"
                ],
            )
            chosen.append(best)
            held.extend(score(p, s, *best) for p, s in test)
            print(f"   {name}, fold {k}: {best} chosen on {len(train)} recordings")
        cv = summarize(held, f"cross-validated ({name})")
        print("   " + show(cv))
        out[f"cross_validated {name}"] = {"chosen": chosen, **cv}

    # 4. ablations
    print("\n4. ablations at the default penalty")
    ablations = []
    for label, kwargs in (
        ("timbre only (no head cue)", {"head_edges": "none"}),
        ("timbre + head-in edge (default)", {"head_edges": "in"}),
        ("timbre + head-in + head-out", {"head_edges": "in+out"}),
        ("min 4 bars", {"min_bars": 4}),
        ("min 12 bars", {"min_bars": 12}),
    ):
        scores = [score(p, s, solo_spans.PENALTY, **kwargs) for p, s in prepared]
        row = summarize(scores, label)
        row["boundaries"] = sum(
            len(
                p.boundaries(
                    solo_spans.PENALTY,
                    kwargs.get("min_bars", DEFAULT[1]),
                    kwargs.get("head_edges", DEFAULT[2]),
                )
            )
            for p, _ in prepared
        )
        ablations.append(row)
        print("   " + show(row) + f"  boundaries {row['boundaries']}")
    heads = sum(p.head is not None for p, _ in prepared)
    print(f"   a head stripe was believed on {heads} of {len(prepared)} recordings")
    from swingscribe.evaluation import paired_change

    out["head_cue"] = {}
    for column, what in ((1, "two bars"), (2, "4 s")):
        before, after, labels = [], [], []
        for p, solos in prepared:
            a = score(p, solos, solo_spans.PENALTY, head_edges="none")
            b = score(p, solos, solo_spans.PENALTY)
            before.append(float(np.mean([h[column] for h in a.hits])))
            after.append(float(np.mean([h[column] for h in b.hits])))
            labels.append(p.rec["name"])
        change = paired_change(before, after, labels)
        print(
            f"   head cue, share of edges found within {what}, per recording: "
            f"{change.mean:+.3f} [{change.low:+.3f}, {change.high:+.3f}], up {change.up} / "
            f"down {change.down} / level {change.level}, sign test p={change.p:.3f}"
        )
        out["head_cue"][what] = [round(change.mean, 3), change.up, change.down, round(change.p, 3)]
    out["ablations"] = ablations

    # 5. by kind of edge, and the head without selecting on the answer
    print("\n5. edges found within two bars, by what is on the other side")
    kinds: dict[str, list[bool]] = defaultdict(list)
    for p, solos in prepared:
        sc = score(p, solos, solo_spans.PENALTY)
        for i, s in enumerate(solos):
            for side in (0, 1):
                other = handover_partner(solos, i, side)
                if other is None:
                    kind = f"{'start' if side == 0 else 'end'}, other side not annotated"
                elif other["instrument"] == s["instrument"]:
                    kind = "handover, same instrument"
                else:
                    kind = "handover, different instrument"
                kinds[kind].append(sc.hits[2 * i + side][1])
    for kind, hits in sorted(kinds.items()):
        print(f"   {kind:<40s} {np.mean(hits):.2f} of {len(hits)}")
    out["by_kind"] = {k: [round(float(np.mean(v)), 3), len(v)] for k, v in kinds.items()}
    # Where the head-in edge is against the first start with nothing annotated
    # before it -- every such start on a recording with a believed head, not
    # only the ones near the edge (that selection is the hit condition).
    open_starts = 0
    first: list[float] = []
    head_out_near_end = 0
    for p, solos in prepared:
        if p.head is None:
            continue
        seen = False
        for i, s in enumerate(solos):
            if handover_partner(solos, i, 0) is not None:
                continue
            open_starts += 1
            if not seen:
                first.append(abs(p.lines[p.head.in_end] - s["start"]) / p.bar(s["start"]))
                seen = True
        out_start = p.lines[min(p.head.out_start, len(p.lines) - 1)]
        head_out_near_end += any(abs(out_start - s["end"]) <= 2 * p.bar(s["end"]) for s in solos)
    first = np.array(first)
    print(
        f"   on the {heads} recordings with a believed head, {open_starts} starts have no "
        f"annotated solo before them; for the first on each ({len(first)}), the head-in edge is "
        f"within two bars on {int((first <= 2).sum())}, within eight on "
        f"{int((first <= 8).sum())}, median {np.median(first):.1f} bars away"
    )
    print(
        f"   the head-out's start is within two bars of an annotated solo end on "
        f"{head_out_near_end} of {heads}"
    )
    gained, lost = [], []
    for p, solos in prepared:
        a = score(p, solos, solo_spans.PENALTY, head_edges="none")
        b = score(p, solos, solo_spans.PENALTY)
        for k, (ha, hb) in enumerate(zip(a.hits, b.hits, strict=True)):
            tag = f"{p.rec['name'][:30]} {'start' if k % 2 == 0 else 'end'}"
            if hb[1] and not ha[1]:
                gained.append(tag)
            if ha[1] and not hb[1]:
                lost.append(tag)
    print(f"   against timbre alone, edges within two bars gained {len(gained)}: {gained}")
    print(f"   lost {len(lost)}: {lost}")
    out["head"] = {
        "believed": heads,
        "open_starts": open_starts,
        "first_open_start_within_2_bars": int((first <= 2).sum()),
        "first_open_start_within_8_bars": int((first <= 8).sum()),
        "first_open_start_median_bars": round(float(np.median(first)), 2),
        "n_first": len(first),
        "head_out_near_an_end": head_out_near_end,
        "gained": len(gained),
        "lost": len(lost),
    }

    # 6. the lead label
    print("\n6. the lead label of the span covering each annotated solo's middle")
    labels_by_class: dict[str, Counter] = defaultdict(Counter)
    for p, solos in prepared:
        proposal_spans = solo_spans.propose(p.env, p.lines).spans
        for s in solos:
            middle = 0.5 * (s["start"] + s["end"])
            span = next((sp for sp in proposal_spans if sp.start <= middle < sp.end), None)
            klass = "horn" if s["instrument"] in HORNS else s["instrument"]
            labels_by_class[klass][span.lead if span else "none"] += 1
    for klass, counts in sorted(labels_by_class.items()):
        print(f"   {klass:<6s} {dict(counts.most_common())}")
    out["lead"] = {k: dict(v) for k, v in labels_by_class.items()}
    lead_against_line(db, prepared, "htdemucs_6s", out)

    # 7. Roformer against htdemucs_6s
    both = [(p, s) for p, s in prepared if p.rec["bsroformer_sw"] and p.model == "htdemucs_6s"]
    if both:
        print(f"\n7. the same {len(both)} recordings on each whole-file separation")
        rows7 = []
        roformer = []
        for p, s in both:
            env = envelopes(p.rec["source"], p.rec["bsroformer_sw"], "bsroformer_sw")
            roformer.append((Prepared(p.rec, env, grids[p.rec["key"]], "bsroformer_sw"), s))
        for label, group in (("htdemucs_6s", both), ("bsroformer_sw", roformer)):
            row = summarize([score(p, s, solo_spans.PENALTY) for p, s in group], label)
            rows7.append(row)
            print("   " + show(row))
        out["separator"] = rows7
        print("   the lead label on each, over the same recordings:")
        lead_against_line(db, both, "htdemucs_6s, these recordings", out)
        lead_against_line(db, roformer, "bsroformer_sw", out)

    # 8. the Omnibook
    sides = omnibook_sides({p.rec["source"] for p, _ in prepared})
    print(f"\n8. the Omnibook: the end of Parker's solo on {len(sides)} located sides")
    ends: dict[str, list[tuple[bool, bool, bool]]] = defaultdict(list)
    used = Counter()
    for side in sides:
        model = "htdemucs_6s" if side["htdemucs_6s"] else "bsroformer_sw"
        env = envelopes(side["source"], side[model], model)
        if env is None or side["key"] not in grids:
            continue
        used[model] += 1
        p = Prepared(side, env, grids[side["key"]], model)
        region_end = float(side["region"][1])
        sc = solo_spans.score_boundaries(
            p.boundaries(*DEFAULT),
            [(float(side["region"][0]), region_end)],
            p.bar,
            track=p.track,
        )
        group = "also in WJazzD" if side["also_in_wjazzd"] else "Omnibook only"
        ends[group].append(sc.hits[1])
        ends["all"].append(sc.hits[1])
    for group, hits in sorted(ends.items()):
        rate = np.mean(np.array(hits), axis=0)
        print(
            f"   {group:<16s} n={len(hits):2d}  "
            f"end within 1 bar / 2 bars / 4 s: {rate.round(2).tolist()}"
        )
    print(f"   stems: {dict(used)}")
    out["omnibook"] = {
        g: [len(h), np.mean(np.array(h), axis=0).round(3).tolist()] for g, h in ends.items()
    }

    # 9. form length (not shipped)
    right = total_forms = 0
    near = 0
    for p, solos in prepared:
        seconds = [wjazz_chorus_seconds(db, s["melid"]) for s in solos]
        seconds = [x for x in seconds if x]
        if not seconds:
            continue
        truth = float(np.median(seconds)) / float(np.median(np.diff(p.lines)))
        if truth > 70:  # an open form: one "chorus" is the whole solo
            continue
        estimate = form_length(p.env, p.lines)
        total_forms += 1
        if estimate and abs(estimate - truth) / truth < 0.06:
            right += 1
        elif estimate and any(
            abs(estimate * f - truth) / truth < 0.06 for f in (0.5, 2, 3, 1 / 3, 4, 0.25)
        ):
            near += 1
    print(
        f"\n9. form length from the bass chroma (not shipped): right on {right} of {total_forms} "
        f"tunes, a multiple or divisor on {near} more"
    )
    out["form_length"] = {"right": right, "multiple": near, "n": total_forms}

    if args.json:
        Path(args.json).write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
