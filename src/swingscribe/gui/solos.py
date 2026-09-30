"""Find the solos: proposed spans on the Overview (roadmap O3).

A thin adapter over `swingscribe.solo_spans`, the way `gui/suggestion.py` is
over `routing`: find a whole-file stem set, read (or build) its envelopes,
lay the proposer over the repaired bar grid, and turn the answer into JSON.
Nothing here decides where a solo is, and nothing here SETS anything: the
page draws the spans as bands under the Overview, and a click on one is the
listener's selection, made through the same flow as a drag. The lead label
is text on the band and nowhere else -- it names a stem of the separation
the envelopes were read from (docs/solo-spans.md, "The lead label"), so it
never reaches the Stem menu, and never `ensemble`: a horn span labelled
`piano` would send a horn to the piano oracle.

docs/solo-spans.md has the measurements (77 WJazzD solos on 49 recordings:
a span edge within two bars of 71% of solo starts and 73% of ends at the
default, 21 solos as one span). What this adapter adds:

- **Which stems.** A WHOLE-FILE set, never a span set: a span separation is
  silent outside its span, and the proposer would find the span's own
  edges. htdemucs_6s first -- the set the survey measured, and the one a new
  track can have in minutes -- then a whole-file BS-RoFormer set if one is
  already on disk (F2 0.679 against htdemucs_6s's 0.699 on the 22
  recordings with both; its better horn routing buys no boundaries). With
  neither, the Find the solos job separates the whole track with
  htdemucs_6s first (`needs` says so, with the estimate).
- **The envelopes are cached beside the stems**, as
  `_envelopes-<version>.npz` in the stems directory, fingerprinted by the
  stems' sizes and mtimes and by the reader's constants: a re-separation
  misses it by itself, and deleting the stems directory -- the cache
  panel's unit -- takes the envelopes with it. Reading six stems is a few
  seconds of numpy (9 s for an 824 s track); loading the cache, a
  twentieth of one. The underscore keeps it out of every stem listing.
- **The grid** is the repaired bar grid `/beats` draws, under the meter the
  listener set (time signature, and the downbeat if they placed one), so a
  band's edges are bar lines of the page they are selecting for. With no
  downbeat the whole-track vote places the bars, as in the survey -- not
  the vote around the selection, which moves with every span chosen, and
  would move every band with it. The downbeat moves bands but not their
  quality (measured 2026-09-30 over the survey's 77 solos, penalty 4, the
  downbeat moved 1/2/3 beats off the vote): F2 0.688/0.698/0.732 against
  0.706, 55-61 wrong-inside against 59, and 22-23% of the vote's 367
  boundaries move by more than a bar. So a listener who sets a downbeat
  gets a reshuffled fifth of the bands, no better and no worse; their
  records for the moved ones are carried.
- **What the listener did with a proposal** is kept in the sidecar's
  `solo_proposals` list (`decide`, `merge`), matched back by CONTENT -- a
  span's two edges and the stem set it was read from -- never by index: a
  different level, a moved downbeat or a new separation renumbers every
  span, like a config change renumbers notes (gui/erasures.py). A record
  whose span is not proposed any more is carried, never dropped.

Pure standard library at import: the numpy half of `solo_spans` is imported
inside the functions that need it, so the record logic runs in CI.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from swingscribe.config import Config
from swingscribe.gui import library
from swingscribe.model import Document

# The separation the job runs when no whole-file set is on disk, and the
# order existing sets are taken in (the module docstring says why).
SEPARATION_MODEL = "htdemucs_6s"
SOLO_MODELS = ("htdemucs_6s", "bsroformer_sw")

# The fewer/more control -> the partition's penalty per feature
# (solo_spans.PENALTY is the default; a test holds them together). At 6 the
# survey reads starts/ends within two bars 0.60/0.65 at 265 boundaries; at 4
# 0.71/0.73 at 367; at 3 0.71/0.78 at 504, with twice the false boundaries
# inside solos (docs/solo-spans.md, the penalty table).
LEVELS: dict[str, float] = {"fewer": 6.0, "default": 4.0, "more": 3.0}
DEFAULT_LEVEL = "default"

# Bumped when what the cache file holds changes shape. A change to the
# reader's constants needs no bump: they are in the fingerprint.
ENVELOPE_VERSION = "v1"
ENVELOPE_PREFIX = "_envelopes-"

# The sidecar key holding what the listener did with the proposals.
SIDECAR_KEY = "solo_proposals"

# Two spans are the same proposal when both edges agree this closely and they
# were read from the same stem set. Proposals are bar lines of the grid, so
# the same grid gives the same times to the millisecond; a moved downbeat
# moves them by a beat (a fifth of a second at 300 bpm) or more.
MATCH_TOLERANCE_S = 0.05
# A clicked span whose edges the selection still has, within this, was
# ACCEPTED; any further and it was adjusted. A click sets them exactly.
ACCEPT_TOLERANCE_S = 0.01
# A selection is about a span when one of the two lies mostly inside the
# other: their overlap is at least this share of the shorter. Among several
# such spans (a selection over two bands of one solo the proposer split),
# the one with the largest intersection-over-union is the one it is about.
CONTAINMENT_FLOOR = 0.5

ACCEPTED = "accepted"
ADJUSTED = "adjusted"
IGNORED = "ignored"


# ── the stems ────────────────────────────────────────────────────────────────


def whole_file_set(document: Document, config: Config) -> tuple[str, dict[str, str]] | None:
    """(model, {stem: path}) of the first COMPLETE whole-file set on disk, in
    SOLO_MODELS order, or None. Complete against the model's own source
    list: a directory holding one stem copied across from another cache
    (CLAUDE.md) has no drums or bass to read a level against."""
    from swingscribe.stages.separate import KNOWN_SOURCES, existing_stems, stems_dir

    digest = library.stem_digest(document)
    for model in SOLO_MODELS:
        found = existing_stems(
            stems_dir(config.cache_dir, digest, model), list(KNOWN_SOURCES[model])
        )
        if found is not None:
            return model, found
    return None


def envelope_path(stems: dict[str, str]) -> Path:
    """Where a stem set's envelopes are cached: inside its own directory."""
    directory = Path(next(iter(stems.values()))).parent
    return directory / f"{ENVELOPE_PREFIX}{ENVELOPE_VERSION}.npz"


def fingerprint(stems: dict[str, str]) -> str:
    """What the cached envelopes were read from, and how. A stem rewritten by
    a new separation changes its size or mtime; a changed reader constant
    changes the rest."""
    from swingscribe import solo_spans

    files = []
    for name, path in sorted(stems.items()):
        stat = Path(path).stat()
        files.append([name, stat.st_size, stat.st_mtime_ns])
    reader = {
        "hop_s": solo_spans.HOP_S,
        "read_rate": solo_spans.READ_RATE,
        "n_fft": solo_spans.N_FFT,
        "band_low_hz": solo_spans.BAND_LOW_HZ,
        "bands_per_octave": solo_spans.BANDS_PER_OCTAVE,
        "chroma": [
            solo_spans.CHROMA_N_FFT,
            solo_spans.CHROMA_LOW_HZ,
            solo_spans.CHROMA_HIGH_HZ,
            list(solo_spans.CHROMA_STEMS),
        ],
    }
    return json.dumps({"stems": files, "reader": reader}, sort_keys=True)


# Loaded envelopes, by cache file and its stat: a level change or a new
# downbeat asks again at once, and decompressing a few MB each time is waste.
_MEMO_SIZE = 4
_memo: OrderedDict[tuple, Any] = OrderedDict()
_memo_lock = threading.Lock()


def clear_memo() -> None:
    """For tests: forget every loaded envelope."""
    with _memo_lock:
        _memo.clear()


def cached_envelopes(stems: dict[str, str]):
    """The set's envelopes from its cache file, or None when there is none or
    it describes other stems. Never reads a stem."""
    import numpy as np

    from swingscribe.solo_spans import StemEnvelopes

    path = envelope_path(stems)
    try:
        stat = path.stat()
        expected = fingerprint(stems)
    except OSError:
        return None
    key = (str(path), stat.st_size, stat.st_mtime_ns, expected)
    with _memo_lock:
        if key in _memo:
            _memo.move_to_end(key)
            return _memo[key]
    try:
        with np.load(path) as data:
            if str(data["fingerprint"]) != expected:
                return None
            env = StemEnvelopes(
                hop_s=float(data["hop_s"]),
                edges_hz=data["edges_hz"],
                power={k[6:]: data[k] for k in data.files if k.startswith("power_")},
                chroma={k[7:]: data[k] for k in data.files if k.startswith("chroma_")},
            )
    except (OSError, ValueError, KeyError):
        return None  # a torn or foreign file is a miss; the job rewrites it
    with _memo_lock:
        _memo[key] = env
        while len(_memo) > _MEMO_SIZE:
            _memo.popitem(last=False)
    return env


def build_envelopes(
    stems: dict[str, str],
    report: Callable[[float, str], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
):
    """Read every stem once into its envelopes and cache them beside the
    stems. One stem at a time, so memory stays one stem's samples (the
    module's own discipline, `solo_spans.stem_envelopes`), and so the job can
    report and stop between stems. Returns the cached copy untouched when it
    is still good."""
    import numpy as np

    from swingscribe import solo_spans

    cached = cached_envelopes(stems)
    if cached is not None:
        if report:
            report(1.0, "envelopes cached")
        return cached
    stamp = fingerprint(stems)  # before reading: a stem rewritten meanwhile must miss
    power, chroma = {}, {}
    edges = solo_spans.band_edges()
    names = sorted(name for name in stems if "+" not in name)
    for index, name in enumerate(names):
        if cancelled is not None and cancelled():
            from swingscribe.gui.jobs import JobCancelled

            raise JobCancelled()
        if report:
            report(index / len(names), f"reading {name}")
        one = solo_spans.stem_envelopes({name: stems[name]})
        power.update(one.power)
        chroma.update(one.chroma)
        edges = one.edges_hz
    env = solo_spans.StemEnvelopes(
        hop_s=solo_spans.HOP_S, edges_hz=edges, power=power, chroma=chroma
    )
    _write_npz(
        envelope_path(stems),
        fingerprint=np.array(stamp),
        hop_s=np.array(env.hop_s),
        edges_hz=env.edges_hz,
        **{f"power_{k}": v for k, v in env.power.items()},
        **{f"chroma_{k}": v for k, v in env.chroma.items()},
    )
    if report:
        report(1.0, "envelopes ready")
    return env


def _write_npz(path: Path, **arrays) -> None:
    """Write beside the stems through a temporary file, so a reader never
    finds half a cache. OneDrive can refuse the rename over an existing file
    (WinError 5, CLAUDE.md); then the old file stays, its fingerprint
    misses, and the next job tries again -- the envelopes in hand are right
    either way."""
    import numpy as np

    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as handle:
        np.savez_compressed(handle, **arrays)
    try:
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)


# ── the proposal ─────────────────────────────────────────────────────────────


def level_penalty(level: str) -> float:
    if level not in LEVELS:
        raise ValueError(f"unknown level {level!r}; one of {', '.join(LEVELS)}")
    return LEVELS[level]


def bar_line_times(
    beat_grid, config: Config, duration: float, overrides: dict[str, Any] | None = None
) -> list[float]:
    """The repaired grid's bar lines over the whole track, as `/beats` draws
    them under the same meter, with the downbeat voted over the whole track
    when the listener has not placed one."""
    from swingscribe.stages import meter

    meter_config = config.meter.model_copy(update=overrides or {})
    meter.resolve_meter(meter_config)  # ValueError on a nonsense signature
    repaired, sections = meter.bar_grid(
        beat_grid.beats, beat_grid.downbeats, meter_config, duration
    )
    return [t for t, _number in meter.bar_lines(repaired, sections)]


def propose(env, lines: Sequence[float], model: str, level: str) -> dict[str, Any]:
    """The proposal as JSON: spans (edges, lead label, kind, bar count), the
    boundaries and which cue placed each, and the head stripe if one was
    believed. Times are rounded like every span the GUI keys on."""
    from swingscribe import solo_spans

    penalty = level_penalty(level)
    proposal = solo_spans.propose(env, lines, penalty=penalty)
    last = len(lines) - 1
    cuts = [0] + [b.bar for b in proposal.boundaries] + [last]
    spans = []
    for k, span in enumerate(proposal.spans):
        spans.append(
            {
                "start": round(span.start, 3),
                "end": round(span.end, 3),
                "lead": span.lead,
                "kind": span.kind,
                "bars": int(cuts[k + 1] - cuts[k]) if k + 1 < len(cuts) else None,
            }
        )
    head = None
    if proposal.head is not None:
        h = proposal.head
        head = {
            "in": [round(float(lines[h.in_start]), 3), round(float(lines[min(h.in_end, last)]), 3)],
            "out": [
                round(float(lines[h.out_start]), 3),
                round(float(lines[min(h.out_end, last)]), 3),
            ],
        }
    return {
        "model": model,
        "level": level,
        "penalty": penalty,
        "spans": spans,
        "boundaries": [{"time": round(b.time, 3), "source": b.source} for b in proposal.boundaries],
        "head": head,
    }


# ── what the listener did with them ──────────────────────────────────────────


def _is_record(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("start"), (int, float))
        and isinstance(value.get("end"), (int, float))
        and isinstance(value.get("model"), str)
    )


def records_of(settings: dict[str, Any]) -> list[dict[str, Any]]:
    """The sidecar's records, anything malformed left where it is but not
    read (the rule for every stored edit: never act on what cannot be
    matched, never delete it either)."""
    stored = settings.get(SIDECAR_KEY)
    return [r for r in stored if _is_record(r)] if isinstance(stored, list) else []


def same_span(a: dict[str, Any], b: dict[str, Any], model: str | None = None) -> bool:
    """Is `a` the proposal `b` describes? Both edges within
    MATCH_TOLERANCE_S, and -- when both say -- the same stem set."""
    model_a = a.get("model", model)
    model_b = b.get("model", model)
    if model_a is not None and model_b is not None and model_a != model_b:
        return False
    return (
        abs(float(a["start"]) - float(b["start"])) <= MATCH_TOLERANCE_S
        and abs(float(a["end"]) - float(b["end"])) <= MATCH_TOLERANCE_S
    )


def match(
    records: Sequence[dict[str, Any]], spans: Sequence[dict[str, Any]], model: str
) -> dict[int, int]:
    """span index -> record index, by content. One record per span: `merge`
    keeps a proposal's record unique, and the first wins if a hand-edited
    sidecar holds two."""
    out: dict[int, int] = {}
    for r_index, record in enumerate(records):
        if not _is_record(record) or record["model"] != model:
            continue
        for s_index, span in enumerate(spans):
            if s_index not in out and same_span(record, span, model):
                out[s_index] = r_index
                break
    return out


def annotate(payload: dict[str, Any], records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Each proposed span with the listener's record for it (or None), and
    how many records match no span proposed now -- carried, not lost."""
    spans = payload["spans"]
    found = match(records, spans, payload["model"])
    for index, span in enumerate(spans):
        span["record"] = dict(records[found[index]]) if index in found else None
    payload["carried"] = sum(1 for r in records if _is_record(r)) - len(found)
    return payload


def _relation(span: dict[str, Any], selection: tuple[float, float]) -> tuple[float, float]:
    """(overlap over the shorter of the two, intersection over union)."""
    a, b = float(span["start"]), float(span["end"])
    lo, hi = selection
    inter = max(0.0, min(b, hi) - max(a, lo))
    shorter = max(1e-9, min(b - a, hi - lo))
    union = max(1e-9, max(b, hi) - min(a, lo))
    return inter / shorter, inter / union


def decide(
    spans: Sequence[dict[str, Any]],
    selection: tuple[float, float],
    origin: dict[str, Any] | None,
    records: Sequence[dict[str, Any]],
    model: str,
    level: str,
    now: float | None = None,
) -> dict[str, Any] | None:
    """The record a selection makes, or None when it is about no proposal.

    - **accepted**: the listener clicked the span (now, or before -- a click
      is remembered in its record) and the selection still has its edges;
    - **adjusted**: clicked, and then an edge moved; `moved` says by how many
      seconds each (selection minus proposal, so negative is earlier);
    - **ignored**: the listener drew their own selection over a proposed
      span they never clicked -- the band was on screen and they chose
      their own edges. `moved` is how far those edges sit from the band's.

    `origin` is the span the listener clicked to make this selection, if
    they did; it is the span the selection is about for as long as the two
    still mostly overlap (CONTAINMENT_FLOOR). Otherwise the selection is
    about the proposed span it mostly overlaps with the largest
    intersection-over-union, and about nothing if there is none.
    """
    lo, hi = float(min(selection)), float(max(selection))
    target, clicked = None, False
    if origin is not None and _relation(origin, (lo, hi))[0] >= CONTAINMENT_FLOOR:
        target, clicked = origin, True
    else:
        best = None
        for span in spans:
            containment, iou = _relation(span, (lo, hi))
            if containment >= CONTAINMENT_FLOOR and (best is None or iou > best[0]):
                best = (iou, span)
        if best is not None:
            target = best[1]
    if target is None:
        return None
    previous = next(
        (r for r in records if _is_record(r) and r["model"] == model and same_span(r, target)),
        None,
    )
    if previous is not None and previous.get("clicked"):
        clicked = True
    start, end = float(target["start"]), float(target["end"])
    moved = [round(lo - start, 3), round(hi - end, 3)]
    if not clicked:
        action = IGNORED
    elif abs(moved[0]) <= ACCEPT_TOLERANCE_S and abs(moved[1]) <= ACCEPT_TOLERANCE_S:
        action = ACCEPTED
    else:
        action = ADJUSTED
    return {
        "start": round(start, 3),
        "end": round(end, 3),
        "lead": target.get("lead"),
        "kind": target.get("kind"),
        "model": model,
        "level": target.get("level", level),
        "action": action,
        "clicked": clicked,
        "selection": [round(lo, 3), round(hi, 3)],
        "moved": moved,
        "overlap": round(_relation(target, (lo, hi))[1], 3),
        "at": round(time.time() if now is None else now, 1),
    }


def merge(records: Sequence[Any], record: dict[str, Any]) -> list[Any]:
    """`records` with `record` in place of the one for the same proposal, or
    appended. Nothing else changes -- not an unmatched record, not even a
    malformed one."""
    out = list(records)
    for index, existing in enumerate(out):
        if (
            _is_record(existing)
            and existing["model"] == record["model"]
            and same_span(existing, record)
        ):
            out[index] = record
            return out
    out.append(record)
    return out
