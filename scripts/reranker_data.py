"""A6's training data: human pages, played by a performance model fitted to WJazzD.

    python scripts/reranker_data.py fit --db wjazz/wjazzd.db --out perf.json
    python scripts/reranker_data.py fidelity --db wjazz/wjazzd.db --perf perf.json
    python scripts/reranker_data.py render --perf perf.json --q 0 --renderings 3 --out beats.pkl

docs/reranker.md. Training pairs of (performed onsets, human page) are what
the project lacks -- the eight triples are the evaluation -- so this script
makes them: each DEV-split page of the OMR corpus (figure_prior's reader and
exclusions: no test-split page, no page whose recording is benchmarked) is
played by a small performance model and run through the shipped swing and
quantize stages, and every beat where the grid choice has a choice is
recorded with its admitted candidates and which of them write the page.

`fit` measures the performance model on WJazzD's PERFORMED onsets against
its annotated BEATS -- never its tatum layer, which is Flex-Q's (D36) --
leaving out the eight triples' solos (the evaluation). Per solo:

- the DOWNBEAT's place inside an eighth-note line (v3, the model trained
  on): for three consecutive onsets whose outer two are offbeats (0.5-0.88)
  of consecutive beats, the middle one's signed offset from the beat line
  between them (-0.3..+0.45, so an early downbeat counts); the solo's
  median, and the residuals about it as 49 quantiles;
- the eighth pair's OFFBEAT (v2): over beats holding exactly two onsets,
  the first before 0.42 and the second at 0.42-0.9, the beat before not
  ending on a pushed note -- the second onset's median phase and its
  residual quantiles about a running median over the pairs within 8
  beats either side;
- pooled: the DRIFT of the pair downbeat along the solo, an AR(1) fitted to
  the autocorrelation of the per-beat offsets at lags 1-32, and how much
  EARLIER a beat of 3 or 4 onsets starts than a pair (`density_offset`);
- and, recorded for the doc, the first model's nearest-onset lag (v1, which
  pulls in the previous beat's last notes and read the line ten times too
  close to the beat) and whether a run of sixteenths swings (it does not).

`fidelity` holds a rendering of every page against WJazzD's real beats on
the per-beat statistics a re-ranker sees (onset count, the pair's two
phases, where a lone onset sits): it is how the anticipation rate was set.

`render` plays each page: a reference solo near the page's marked tempo
(within 20%; an unmarked page takes a solo at random and its tempo) lends
its downbeat lateness, offbeat place and scatter; a written downbeat (and
every position but an eighth pair's offbeat) is played at the solo's
downbeat lateness, less the density offset for a busy beat, plus the drift
and its own draw from the solo's downbeat residuals (sixteenths and
triplets at their written spacing before those draws: they do not swing);
the offbeat of a beat written in eighths is played at
the solo's offbeat place plus the drift and its own residual. A note written
on an "and" and held across the next beat line may be played ON that beat
(`--q`; the estimate from docs/writing-round2.md's ratio is 0.78, and
`fidelity` showed q=0 nearest WJazzD, so the models were trained at q=0).
Nothing else: no extra or missing notes. Then swing.run and quantize_notes
with a recorder in the reranker hook.

Only aggregates leave this script for the repo: the per-solo table and the
recorded beats stay in scratch (WJazzD is ODbL; the pages are derivatives
of commercial recordings).
"""

from __future__ import annotations

import argparse
import bisect
import contextlib
import io
import json
import math
import pickle
import random
import sqlite3
import statistics
import sys
from collections import Counter
from fractions import Fraction
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "src"))

# The triples' solos are the evaluation (docs/triples.md): never fitted on.
TRIPLE_MELIDS = {53, 55, 56, 58, 60, 61, 68, 121}
NEAR_LINE = 0.22  # beats either side of a beat line: an onset there is "the downbeat"
RUNNING = 8  # beat lines either side of the running median
PAIR_FIRST_MAX = 0.22
PAIR_SECOND = (0.38, 0.9)
MIN_PAIRS = 10
# v2 (docs/reranker.md, "the first model's lag was wrong"): the eighth pair
# measured as a pair -- a beat of exactly two onsets, the first before 0.42
# and the second at 0.42-0.9, the beat before not ending on a pushed note --
# for the downbeat's own lateness, the offbeat's own place, and their
# scatter. v1 took the NEAREST onset to each beat line instead, which pulls
# in the previous beat's last notes and read the line ten times too close
# to the beat (median lag 0.015 against the pair's 0.133).
PAIR_V2_FIRST_MAX = 0.42
PAIR_V2_SECOND = (0.42, 0.9)
PUSHED_BEFORE = 0.88
MIN_PAIRS_V2 = 15
# v3: the downbeat INSIDE an eighth-note line, measured symmetrically --
# three consecutive onsets, the outer two offbeats (0.5-0.88) of
# consecutive beats, the middle one within -0.3..+0.45 of the beat line
# between them. Nothing truncates an early downbeat, which the pair (a
# beat of two onsets, its first inside the beat) cannot see: 13% of them
# are early, and the scatter is 0.10 of a beat, not the pair's 0.07.
LINE_OFFBEAT = (0.5, 0.88)
LINE_WINDOW = (-0.3, 0.45)
MIN_LINE = 20
QUANTILES = [i / 50 for i in range(1, 50)]
AUTOCORR_LAGS = (1, 2, 4, 8, 16, 32)
TEMPO_MATCH = math.log(1.2)
MARGIN_BEATS = 4  # grid beats before the page's first beat
MIN_GAP_S = 0.015  # two performed onsets never closer than this
STEM = "other"
# docs/writing-round2.md, "So the class is ours": of the matched notes of the
# triples' (a) row that SOUNDED within 0.15 of a beat line and that we wrote
# on the beat, the page writes the beat for 531 and the "and" before for 54.
ANTICIPATED_PER_ON_BEAT = 54 / 531


# ── the performance model, from WJazzD ──────────────────────────────────────


def _offsets(grid: list[float], onsets: list[float]) -> list[tuple[int, float, float]]:
    """(beat line, signed offset in beats, in ms) of the nearest onset within
    NEAR_LINE of each inner beat line."""
    out = []
    for i in range(1, len(grid) - 1):
        before, after = grid[i] - grid[i - 1], grid[i + 1] - grid[i]
        if before <= 0 or after <= 0:
            continue
        lo = bisect.bisect_left(onsets, grid[i] - NEAR_LINE * before)
        hi = bisect.bisect_right(onsets, grid[i] + NEAR_LINE * after)
        best = None
        for o in onsets[lo:hi]:
            d = (o - grid[i]) / (after if o >= grid[i] else before)
            if best is None or abs(d) < abs(best[0]):
                best = (d, (o - grid[i]) * 1000.0)
        if best is not None:
            out.append((i, best[0], best[1]))
    return out


def _quantiles(values: list[float], qs: list[float]) -> list[float]:
    ordered = sorted(values)
    out = []
    for q in qs:
        x = q * (len(ordered) - 1)
        lo = int(math.floor(x))
        hi = min(lo + 1, len(ordered) - 1)
        out.append(ordered[lo] + (ordered[hi] - ordered[lo]) * (x - lo))
    return out


def _rmad(values: list[float]) -> float:
    m = statistics.median(values)
    return 1.4826 * statistics.median(abs(v - m) for v in values)


def fit(db_path: Path) -> dict:
    import wjazz_quantize

    db = sqlite3.connect(db_path)
    info = {
        m: (t, feel)
        for m, t, feel in db.execute("select melid, avgtempo, rhythmfeel from solo_info")
    }
    solos = []
    autocorr = {k: [0.0, 0] for k in AUTOCORR_LAGS}
    variance = [0.0, 0]
    pair_auto = {k: [0.0, 0] for k in AUTOCORR_LAGS}
    pair_var = [0.0, 0]
    first_by_count: dict[int, list[float]] = {}
    sixteenths = []
    all_resid_beats, all_resid_ms = [], []
    for (melid,) in db.execute("select melid from solo_info order by melid").fetchall():
        if melid in TRIPLE_MELIDS:
            continue
        solo = wjazz_quantize.load_solo(db, melid)
        if solo is None or len(solo["grid"]) < 32:
            continue
        grid = solo["grid"]
        onsets = sorted(n["onset"] for n in solo["notes"])
        rows = _offsets(grid, onsets)
        if len(rows) < 40:
            continue
        lag = statistics.median(d for _i, d, _ms in rows)
        by_line = {i: d - lag for i, d, _ms in rows}
        for i, d in by_line.items():
            variance[0] += d * d
            variance[1] += 1
            for k in AUTOCORR_LAGS:
                if i + k in by_line:
                    autocorr[k][0] += d * by_line[i + k]
                    autocorr[k][1] += 1
        lines = [i for i, _d, _ms in rows]
        resid_beats, resid_ms = [], []
        for i, d, _ms in rows:
            lo = bisect.bisect_left(lines, i - RUNNING)
            hi = bisect.bisect_right(lines, i + RUNNING)
            window = [rows[k][1] for k in range(lo, hi)]
            if len(window) < 5:
                continue
            local = statistics.median(window)
            resid_beats.append(d - local)
            length = grid[i + 1] - grid[i] if d >= 0 else grid[i] - grid[i - 1]
            resid_ms.append((d - local) * length * 1000.0)
        # The eighth pair: beats holding exactly two onsets.
        per_beat: dict[int, list[float]] = {}
        for o in onsets:
            i = bisect.bisect_right(grid, o) - 1
            if 0 <= i < len(grid) - 1:
                per_beat.setdefault(i, []).append((o - grid[i]) / (grid[i + 1] - grid[i]))
        pairs = [
            p[1] - p[0]
            for p in per_beat.values()
            if len(p) == 2 and p[0] <= PAIR_FIRST_MAX and PAIR_SECOND[0] <= p[1] <= PAIR_SECOND[1]
        ]
        fours = [
            p[2] - p[0]
            for p in per_beat.values()
            if len(p) == 4 and p[0] <= PAIR_FIRST_MAX and p[3] <= 0.87
        ]
        sixteenths.extend(fours)
        # v2: the eighth pair's own downbeat and offbeat, in absolute phase.
        pair_rows = []
        for i in sorted(per_beat):
            p = per_beat[i]
            before = per_beat.get(i - 1, [])
            if before and max(before) >= PUSHED_BEFORE:
                continue
            if p[0] < PAIR_V2_FIRST_MAX:
                first_by_count.setdefault(min(len(p), 4), []).append(p[0])
            if (
                len(p) == 2
                and p[0] < PAIR_V2_FIRST_MAX
                and PAIR_V2_SECOND[0] <= p[1] <= PAIR_V2_SECOND[1]
            ):
                pair_rows.append((i, p[0], p[1]))
        v2 = None
        if len(pair_rows) >= MIN_PAIRS_V2:
            down = statistics.median(r[1] for r in pair_rows)
            off = statistics.median(r[2] for r in pair_rows)
            idx = [r[0] for r in pair_rows]
            res_down, res_off = [], []
            for i, first, second in pair_rows:
                lo = bisect.bisect_left(idx, i - RUNNING)
                hi = bisect.bisect_right(idx, i + RUNNING)
                window = pair_rows[lo:hi]
                if len(window) >= 5:
                    local_d = statistics.median(r[1] for r in window)
                    local_o = statistics.median(r[2] for r in window)
                else:
                    local_d, local_o = down, off
                res_down.append(first - local_d)
                res_off.append(second - local_o)
            by_pair = {i: first - down for i, first, _s in pair_rows}
            for i, d in by_pair.items():
                pair_var[0] += d * d
                pair_var[1] += 1
                for k in AUTOCORR_LAGS:
                    if i + k in by_pair:
                        pair_auto[k][0] += d * by_pair[i + k]
                        pair_auto[k][1] += 1
            v2 = {
                "down": down,
                "off": off,
                "pairs": len(pair_rows),
                "down_q": _quantiles(res_down, QUANTILES),
                "off_q": _quantiles(res_off, QUANTILES),
                "down_rmad": _rmad(res_down),
                "off_rmad": _rmad(res_off),
            }
        line = line_downbeats(grid, onsets)
        v3 = None
        if len(line) >= MIN_LINE:
            middle = statistics.median(line)
            v3 = {
                "down": middle,
                "down_q": _quantiles([d - middle for d in line], QUANTILES),
                "down_rmad": _rmad(line),
                "n": len(line),
            }
        beat_s = statistics.median(grid[i + 1] - grid[i] for i in range(len(grid) - 1))
        tempo, feel = info.get(melid, (None, None))
        all_resid_beats.extend(resid_beats)
        all_resid_ms.extend(resid_ms)
        solos.append(
            {
                "melid": melid,
                "bpm": 60.0 / beat_s,
                "avgtempo": tempo,
                "feel": feel,
                "lag": lag,
                "phi": statistics.median(pairs) if len(pairs) >= MIN_PAIRS else None,
                "pairs": len(pairs),
                "jitter_q": _quantiles(resid_beats, QUANTILES),
                "jitter_rmad_beats": _rmad(resid_beats),
                "jitter_rmad_ms": _rmad(resid_ms),
                "lines": len(rows),
                "v2": v2,
                "v3": v3,
            }
        )
    pair_first = statistics.median(first_by_count[2])
    model = {
        "solos": solos,
        "drift": _ar1(autocorr, variance),
        # v2: the drift of the PAIR downbeat along the solo, and how much
        # earlier a beat of n onsets starts than a pair (pooled medians).
        "drift_v2": _ar1(pair_auto, pair_var),
        "density_offset": {
            str(n): statistics.median(v) - pair_first for n, v in sorted(first_by_count.items())
        },
        "first_by_count": {
            str(n): {"median": statistics.median(v), "beats": len(v)}
            for n, v in sorted(first_by_count.items())
        },
        "summary": summary(solos, sixteenths, all_resid_beats, all_resid_ms),
        "excluded_melids": sorted(TRIPLE_MELIDS),
    }
    return model


def line_downbeats(grid: list[float], onsets: list[float]) -> list[float]:
    """v3's downbeat offsets, in beats: see LINE_OFFBEAT."""

    def phase(t):
        i = bisect.bisect_right(grid, t) - 1
        if not 0 <= i < len(grid) - 1:
            return None, None
        return i, (t - grid[i]) / (grid[i + 1] - grid[i])

    out = []
    for a, b, c in zip(onsets, onsets[1:], onsets[2:], strict=False):
        ia, pa = phase(a)
        ic, pc = phase(c)
        if ia is None or ic is None or ic != ia + 1:
            continue
        if not (
            LINE_OFFBEAT[0] <= pa <= LINE_OFFBEAT[1] and LINE_OFFBEAT[0] <= pc <= LINE_OFFBEAT[1]
        ):
            continue
        line = grid[ic]
        length = grid[ic + 1] - grid[ic] if b >= line else grid[ic] - grid[ic - 1]
        d = (b - line) / length
        if LINE_WINDOW[0] <= d <= LINE_WINDOW[1]:
            out.append(d)
    return out


def _ar1(autocorr: dict, variance: list) -> dict:
    """AR(1) drift under white jitter: corr(k) = share * rho**k for k >= 1,
    least squares on log corr over the lags where it is positive."""
    var0 = variance[0] / variance[1]
    corr = {k: (s / n) / var0 for k, (s, n) in autocorr.items() if n}
    points = [(k, math.log(c)) for k, c in corr.items() if c > 0]
    n = len(points)
    mean_k = sum(k for k, _ in points) / n
    mean_y = sum(y for _, y in points) / n
    slope = sum((k - mean_k) * (y - mean_y) for k, y in points) / sum(
        (k - mean_k) ** 2 for k, _ in points
    )
    rho = min(0.999, math.exp(slope))
    share = min(1.0, math.exp(mean_y - slope * mean_k))
    return {
        "rho": rho,
        "sd": math.sqrt(max(0.0, share) * var0),
        "share": share,
        "autocorr": corr,
        "var": var0,
    }


def summary(solos, sixteenths, resid_beats, resid_ms) -> dict:
    with_phi = [s for s in solos if s["phi"] is not None]
    lags = [s["lag"] for s in solos]
    out = {
        "solos": len(solos),
        "solos_with_swing": len(with_phi),
        "lag": {
            "median": statistics.median(lags),
            "q10": _quantiles(lags, [0.1])[0],
            "q90": _quantiles(lags, [0.9])[0],
        },
        "phi": {
            "median": statistics.median(s["phi"] for s in with_phi),
            "q10": _quantiles([s["phi"] for s in with_phi], [0.1])[0],
            "q90": _quantiles([s["phi"] for s in with_phi], [0.9])[0],
        },
        "jitter": {
            "rmad_beats": _rmad(resid_beats),
            "rmad_ms": _rmad(resid_ms),
            "q": dict(
                zip(
                    ("q01", "q05", "q25", "q50", "q75", "q95", "q99"),
                    _quantiles(resid_beats, [0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99]),
                    strict=True,
                )
            ),
        },
        "sixteenth_third_onset": {
            "median": statistics.median(sixteenths) if sixteenths else None,
            "n": len(sixteenths),
        },
        "by_tempo": {},
    }
    for lo, hi in ((0, 100), (100, 140), (140, 180), (180, 240), (240, 500)):
        band = [s for s in solos if lo <= s["bpm"] < hi]
        if not band:
            continue
        phis = [s["phi"] for s in band if s["phi"] is not None]
        out["by_tempo"][f"{lo}-{hi}"] = {
            "solos": len(band),
            "lag": statistics.median(s["lag"] for s in band),
            "phi": statistics.median(phis) if phis else None,
            "jitter_rmad_beats": statistics.median(s["jitter_rmad_beats"] for s in band),
            "jitter_rmad_ms": statistics.median(s["jitter_rmad_ms"] for s in band),
        }
    return out


# ── the pages ───────────────────────────────────────────────────────────────


def load_pages(log=print) -> list[dict]:
    """Every dev-split page of the OMR corpus as a flat list of onsets in
    quarter notes, with which beats may be labelled. figure_prior's reader
    and exclusions: OVERLAP (recordings under benchmark/) and the test
    split are dropped before anything is read here."""
    import figure_prior

    corpus = figure_prior.load_corpus(log=lambda *_: None)
    corpus = figure_prior.without_test_pages(corpus, log=lambda *_: None)
    pages = []
    for t in corpus:
        onsets: list[Fraction] = []
        rest_starts: list[Fraction] = []
        labelled: set[int] = set()
        start = Fraction(0)
        for bar in t.bars:
            if bar.quarter_beats or bar.signature[1] == 8:
                for o in bar.onsets:
                    onsets.append(start + o)
                for p, _d in bar.rests:
                    rest_starts.append(start + p)
            ok = (
                figure_prior.bar_included(t, bar, strict=False)
                and bar.voices == 1
                and bar.signature[1] == 4
            )
            if ok:
                for beat in range(int(bar.length)):
                    if beat not in bar.duplicate_beats:
                        labelled.add(int(start) + beat)
            start += bar.length
        onsets = sorted(set(onsets))
        if len(onsets) < 16 or not labelled:
            continue
        tempo = t.tempo if t.tempo and t.tempo >= figure_prior.MIN_TEMPO else None
        pages.append(
            {
                "name": t.name,
                "source": t.source,
                "tempo": tempo,
                "onsets": onsets,
                "rest_starts": sorted(rest_starts),
                "labelled": labelled,
                "beats": int(start),
            }
        )
    log(f"  {len(corpus)} dev pages read, {len(pages)} with notes on quarter beats")
    return pages


def anticipation_rate(pages: list[dict]) -> dict:
    """P(a held "and" is played on the next beat), from the triples' ratio of
    anticipated to on-beat notes and the pages' own counts: q = ratio *
    on-beat notes / held "and" notes."""
    on_beat = held = 0
    for page in pages:
        for k, p in enumerate(page["onsets"]):
            frac = p - int(p)
            if frac == 0:
                on_beat += 1
            elif frac == Fraction(1, 2) and _held_across(page, k):
                held += 1
    q = min(1.0, ANTICIPATED_PER_ON_BEAT * on_beat / max(1, held))
    return {"on_beat": on_beat, "held_and": held, "q": q}


def _held_across(page: dict, k: int) -> bool:
    """Is the note at onsets[k] (on an "and") held across the next beat line:
    no onset and no rest before the half beat after it?"""
    p = page["onsets"][k]
    nxt = page["onsets"][k + 1] if k + 1 < len(page["onsets"]) else None
    if nxt is not None and nxt < p + 1:
        return False
    i = bisect.bisect_right(page["rest_starts"], p)
    return not (i < len(page["rest_starts"]) and page["rest_starts"][i] < p + Fraction(1, 2))


# ── rendering ───────────────────────────────────────────────────────────────


def _jitter(rng: random.Random, q: list[float]) -> float:
    """A draw from a solo's jitter quantiles (inverse CDF, linear)."""
    u = rng.random() * (len(q) + 1) - 0.5
    if u <= 0:
        return q[0]
    if u >= len(q) - 1:
        return q[-1]
    lo = int(u)
    return q[lo] + (q[lo + 1] - q[lo]) * (u - lo)


def pick_reference(rng: random.Random, solos: list[dict], tempo: float | None) -> dict:
    if tempo is None:
        return rng.choice(solos)
    near = [s for s in solos if abs(math.log(s["bpm"] / tempo)) <= TEMPO_MATCH]
    if not near:
        near = sorted(solos, key=lambda s: abs(math.log(s["bpm"] / tempo)))[:10]
    return rng.choice(near)


def render(
    page: dict, perf: dict, rng: random.Random, q_anticipate: float, version: str = "v2"
) -> dict:
    """One performance of one page: (beat times, onsets in seconds, the page
    position of each, in quarter notes), sorted by onset. v1 is the first
    model (nearest-onset lag, eighth offbeat at the pair spacing)."""
    if version in ("v2", "v3"):
        return render_v2(page, perf, rng, q_anticipate, version)
    solos = [s for s in perf["solos"] if s["phi"] is not None]
    ref = pick_reference(rng, solos, page["tempo"])
    bpm = page["tempo"] or ref["bpm"]
    beat_s = 60.0 / bpm
    total = page["beats"] + 2 * MARGIN_BEATS + 2
    grid = [i * beat_s for i in range(total + 1)]
    rho, sd = perf["drift"]["rho"], perf["drift"]["sd"]
    drift, x = [], rng.gauss(0.0, sd)
    for _ in range(total + 1):
        drift.append(x)
        x = rho * x + math.sqrt(max(0.0, 1 - rho * rho)) * sd * rng.gauss(0.0, 1.0)
    onsets = page["onsets"]
    by_beat: dict[int, list[Fraction]] = {}
    for p in onsets:
        by_beat.setdefault(int(p), []).append(p - int(p))
    eighths = {b for b, fr in by_beat.items() if all(f in (0, Fraction(1, 2)) for f in fr)}
    played = []
    for k, p in enumerate(onsets):
        b, frac = int(p), p - int(p)
        phase = float(frac)
        if b in eighths and frac == Fraction(1, 2):
            phase = ref["phi"]
        if (
            frac == Fraction(1, 2)
            and q_anticipate > 0
            and _held_across(page, k)
            and rng.random() < q_anticipate
        ):
            b, phase = b + 1, 0.0  # played on the beat the page anticipates
        at = b + MARGIN_BEATS
        phase += ref["lag"] + drift[at] + _jitter(rng, ref["jitter_q"])
        played.append(((at + phase) * beat_s, p))
    played.sort()
    out_on, out_pos = [], []
    last = -math.inf
    for t, p in played:
        t = max(t, last + MIN_GAP_S)
        out_on.append(t)
        out_pos.append(p)
        last = t
    return {
        "grid": grid,
        "onsets": out_on,
        "positions": out_pos,
        "bpm": bpm,
        "ref": ref["melid"],
        "phi": ref["phi"],
        "lag": ref["lag"],
    }


def render_v2(
    page: dict, perf: dict, rng: random.Random, q_anticipate: float, version: str = "v2"
) -> dict:
    """v2: a written downbeat (and every position but the eighth pair's
    offbeat) is played at the reference solo's PAIR downbeat lateness,
    less how much earlier a beat of that many onsets starts, plus a shared
    drift and the solo's own downbeat scatter; the offbeat of a beat
    written in eighths at the solo's own offbeat place plus the drift and
    its own scatter. Sixteenths and triplets keep their spacing. v3 takes
    the downbeat's lateness and scatter from the line measure instead."""
    solos = [s for s in perf["solos"] if s.get("v2") and (version == "v2" or s.get("v3"))]
    ref = pick_reference(rng, solos, page["tempo"])
    pair = dict(ref["v2"])
    if version == "v3":
        pair["down"], pair["down_q"] = ref["v3"]["down"], ref["v3"]["down_q"]
    bpm = page["tempo"] or ref["bpm"]
    beat_s = 60.0 / bpm
    total = page["beats"] + 2 * MARGIN_BEATS + 2
    grid = [i * beat_s for i in range(total + 1)]
    rho, sd = perf["drift_v2"]["rho"], perf["drift_v2"]["sd"]
    drift, x = [], rng.gauss(0.0, sd)
    for _ in range(total + 1):
        drift.append(x)
        x = rho * x + math.sqrt(max(0.0, 1 - rho * rho)) * sd * rng.gauss(0.0, 1.0)
    density = perf["density_offset"]
    onsets = page["onsets"]
    by_beat: dict[int, list[Fraction]] = {}
    for p in onsets:
        by_beat.setdefault(int(p), []).append(p - int(p))
    eighths = {b for b, fr in by_beat.items() if all(f in (0, Fraction(1, 2)) for f in fr)}
    played = []
    for k, p in enumerate(onsets):
        b, frac = int(p), p - int(p)
        late = pair["down"] + density.get(str(min(4, len(by_beat[b]))), 0.0)
        if (
            frac == Fraction(1, 2)
            and q_anticipate > 0
            and _held_across(page, k)
            and rng.random() < q_anticipate
        ):
            # Played on the beat the page anticipates.
            b, frac = b + 1, Fraction(0)
            late = pair["down"] + density.get(str(min(4, len(by_beat.get(b, [])) + 1)), 0.0)
        at = b + MARGIN_BEATS
        if b in eighths and frac == Fraction(1, 2):
            phase = pair["off"] + drift[at] + _jitter(rng, pair["off_q"])
        else:
            phase = float(frac) + late + drift[at] + _jitter(rng, pair["down_q"])
        played.append(((at + phase) * beat_s, p))
    played.sort()
    out_on, out_pos = [], []
    last = -math.inf
    for t, p in played:
        t = max(t, last + MIN_GAP_S)
        out_on.append(t)
        out_pos.append(p)
        last = t
    return {
        "grid": grid,
        "onsets": out_on,
        "positions": out_pos,
        "bpm": bpm,
        "ref": ref["melid"],
        "phi": pair["off"],
        "lag": pair["down"],
    }


class Recorder:
    """The reranker hook in recording mode: keeps every beat's context and
    admitted candidates and lets the shipped rule decide."""

    def __init__(self, open_: bool = True):
        self.open = open_
        self.beats: list[tuple[dict, list[dict]]] = []

    def choose(self, context: dict, candidates: list[dict]):
        self.beats.append(
            (
                dict(context),
                [
                    {
                        k: c[k]
                        for k in (
                            "divisions",
                            "reading",
                            "snapped",
                            "error",
                            "figure",
                            "baseline",
                            "gated",
                        )
                    }
                    for c in candidates
                ],
            )
        )
        return None


def record(performance: dict, config=None) -> list[tuple[dict, list[dict]]]:
    """Run swing and quantize over one performance with the recorder in the
    hook, exactly as the stages run them (shipped settings)."""
    from swingscribe.config import Config
    from swingscribe.model import BeatGrid, Document, NoteEvent
    from swingscribe.stages import quantize, swing

    config = config or Config()
    config = config.model_copy(
        update={
            "swing": config.swing.model_copy(update={"stem": STEM}),
            "quantize": config.quantize.model_copy(update={"stem": STEM}),
        }
    )
    onsets = performance["onsets"]
    durations = [
        max(0.03, 0.9 * ((onsets[i + 1] if i + 1 < len(onsets) else onsets[i] + 0.5) - onsets[i]))
        for i in range(len(onsets))
    ]
    notes = [
        NoteEvent(onset=o, duration=d, pitch=60, confidence=1.0, source="synthetic")
        for o, d in zip(onsets, durations, strict=True)
    ]
    grid = performance["grid"]
    document = Document(
        audio_path="synthetic",
        sample_rate=44100,
        beat_grid=BeatGrid(beats=grid, downbeats=[], beats_per_bar=4),
        notes={STEM: notes},
    )
    with contextlib.redirect_stdout(io.StringIO()):
        spans = swing.run(document, config).swing
    recorder = Recorder()
    quantize.quantize_notes(
        onsets,
        durations,
        [60] * len(onsets),
        grid,
        spans,
        [],
        **{**quantize.settings(config.quantize), "reranker": recorder},
    )
    return recorder.beats


def labels_for(performance: dict, page: dict, beats: list[tuple[dict, list[dict]]]) -> list[dict]:
    """Each recorded beat with, per candidate, whether it writes every note
    of the beat where the page does. A beat is labelled only inside a bar
    the page fills (figure_prior's filters) and only when every note it
    holds is written by the page within the beat or on the next beat line."""
    from swingscribe.stages.quantize import beat_position

    grid = performance["grid"]
    members: dict[int, list[Fraction]] = {}
    for t, p in zip(performance["onsets"], performance["positions"], strict=True):
        position = beat_position(t, grid)
        if position is not None:
            members.setdefault(int(position), []).append(p)
    out = []
    for context, candidates in beats:
        index = context["index"]
        page_beat = index - MARGIN_BEATS
        positions = members.get(index, [])
        rel = [float(p - page_beat) for p in positions]
        labelled = (
            page_beat in page["labelled"]
            and len(rel) == len(context["raw"])
            and all(-1e-9 <= r <= 1.0 + 1e-9 for r in rel)
        )
        correct = [
            labelled and all(abs(s - r) < 1e-6 for s, r in zip(c["snapped"], rel, strict=True))
            for c in candidates
        ]
        out.append(
            {
                "context": context,
                "candidates": candidates,
                "labelled": labelled,
                "correct": correct,
                "page_figure": " ".join(str(Fraction(r).limit_denominator(48)) for r in rel),
            }
        )
    return out


# ── fidelity: synthetic beats against WJazzD's ──────────────────────────────


def _phases_by_beat(grid: list[float], onsets: list[float]) -> list[list[float]]:
    per: dict[int, list[float]] = {}
    for o in onsets:
        i = bisect.bisect_right(grid, o) - 1
        if 0 <= i < len(grid) - 1:
            per.setdefault(i, []).append((o - grid[i]) / (grid[i + 1] - grid[i]))
    return list(per.values())


LONE_BINS = (0.0, 0.15, 0.3, 0.45, 0.6, 0.75, 0.9, 1.0)


def beat_statistics(beats: list[list[float]]) -> dict:
    """What a re-ranker sees of a beat, summarised: onset counts, the two
    phases of a two-onset beat, where a lone onset sits, a beat's last
    onset at the next line."""
    beats = [b for b in beats if b]
    counts = Counter(min(len(b), 5) for b in beats)
    two = [b for b in beats if len(b) == 2]
    lone = [b[0] for b in beats if len(b) == 1]
    hist = [0] * (len(LONE_BINS) - 1)
    for x in lone:
        hist[min(len(hist) - 1, bisect.bisect_right(LONE_BINS, x) - 1)] += 1
    return {
        "count_share": {k: round(v / len(beats), 3) for k, v in sorted(counts.items())},
        "pair_first_q25_50_75": [
            round(x, 3) for x in _quantiles([b[0] for b in two], [0.25, 0.5, 0.75])
        ],
        "pair_second_q25_50_75": [
            round(x, 3) for x in _quantiles([b[1] for b in two], [0.25, 0.5, 0.75])
        ],
        "pair_first_from_0.25": round(sum(b[0] >= 0.25 for b in two) / len(two), 3),
        "lone_phase_hist": [round(h / len(lone), 3) for h in hist],
        "last_from_0.88": round(sum(max(b) >= 0.88 for b in beats) / len(beats), 3),
    }


def fidelity(db_path: Path, perf: dict, qs=(None, 0.25, 0.0)) -> dict:
    """WJazzD's real beats (the fitted solos, triples left out) beside one
    rendering of every page at each anticipation rate (None: the estimate)."""
    import wjazz_quantize

    db = sqlite3.connect(db_path)
    real: list[list[float]] = []
    for (melid,) in db.execute("select melid from solo_info order by melid").fetchall():
        if melid in TRIPLE_MELIDS:
            continue
        solo = wjazz_quantize.load_solo(db, melid)
        if solo is None or len(solo["grid"]) < 32:
            continue
        real.extend(_phases_by_beat(solo["grid"], sorted(n["onset"] for n in solo["notes"])))
    out = {"wjazzd": beat_statistics(real)}
    pages = load_pages(log=lambda *_: None)
    estimate = anticipation_rate(pages)["q"]
    for q in qs:
        rate = estimate if q is None else q
        synth: list[list[float]] = []
        for page in pages:
            performance = render(page, perf, random.Random(f"fid:{page['name']}"), rate, "v3")
            synth.extend(_phases_by_beat(performance["grid"], performance["onsets"]))
        out[f"v3 q={rate:.2f}"] = beat_statistics(synth)
    return out


def render_all(
    pages, perf, renderings: int, seed: int, q: float, version: str = "v2", log=print
) -> list[dict]:
    rows = []
    for r in range(renderings):
        for n, page in enumerate(pages):
            rng = random.Random(f"{seed}:{r}:{page['name']}")
            performance = render(page, perf, rng, q, version)
            beats = record(performance)
            for row in labels_for(performance, page, beats):
                row["page"] = page["name"]
                row["rendering"] = r
                row["bpm"] = performance["bpm"]
                rows.append(row)
            if n % 40 == 0:
                log(f"  rendering {r}: {n}/{len(pages)} pages, {len(rows)} beats so far")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="mode", required=True)
    f = sub.add_parser("fit")
    f.add_argument("--db", type=Path, default=REPO_ROOT / "wjazz/wjazzd.db")
    f.add_argument("--out", type=Path, required=True)
    fi = sub.add_parser("fidelity")
    fi.add_argument("--db", type=Path, default=REPO_ROOT / "wjazz/wjazzd.db")
    fi.add_argument("--perf", type=Path, required=True)
    r = sub.add_parser("render")
    r.add_argument("--perf", type=Path, required=True)
    r.add_argument("--renderings", type=int, default=3)
    r.add_argument("--seed", type=int, default=0)
    r.add_argument("--limit", type=int, default=0)
    r.add_argument("--no-anticipation", action="store_true")
    r.add_argument("--perf-model", choices=("v1", "v2", "v3"), default="v3")
    r.add_argument(
        "--q", type=float, default=None, help="anticipation rate, overriding the estimate"
    )
    r.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "fit":
        model = fit(args.db)
        args.out.write_text(json.dumps(model, indent=1), encoding="utf-8")
        keys = ("drift", "drift_v2", "density_offset", "first_by_count", "summary")
        print(json.dumps({k: model[k] for k in keys}, indent=1))
        return
    perf = json.loads(args.perf.read_text(encoding="utf-8"))
    if args.mode == "fidelity":
        for label, stats in fidelity(args.db, perf).items():
            print(f"{label:12} {json.dumps(stats)}")
        return
    pages = load_pages()
    if args.limit:
        pages = pages[: args.limit]
    rate = anticipation_rate(pages)
    q = 0.0 if args.no_anticipation else rate["q"] if args.q is None else args.q
    print(f"anticipation: {rate}, using q={q:.3f}")
    tempos = Counter("marked" if p["tempo"] else "unmarked" for p in pages)
    labelled_beats = sum(len(p["labelled"]) for p in pages)
    print(f"pages {len(pages)} ({dict(tempos)}), labelled beats {labelled_beats}")
    rows = render_all(pages, perf, args.renderings, args.seed, q, args.perf_model)
    with args.out.open("wb") as handle:
        pickle.dump({"rows": rows, "anticipation": rate, "q": q, "pages": len(pages)}, handle)
    labelled = [r for r in rows if r["labelled"]]
    n = max(1, len(labelled))
    rule = sum(
        any(c and k["baseline"] for c, k in zip(r["correct"], r["candidates"], strict=True))
        for r in labelled
    )
    oracle = sum(any(r["correct"]) for r in labelled)
    print(
        f"recorded {len(rows)} beats with a choice, {len(labelled)} labelled; "
        f"baseline right {rule / n:.4f}, oracle {oracle / n:.4f} (every reading the guards allow)"
    )


if __name__ == "__main__":
    main()
