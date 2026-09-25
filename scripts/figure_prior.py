"""Per-beat rhythmic figures on human transcription pages, counted.

    python scripts/figure_prior.py                       # the tables (task 1)
    python scripts/figure_prior.py --json out.json       # ...and every count behind them
    python scripts/figure_prior.py condition             # what to condition on (task 3)
    python scripts/figure_prior.py compare --db wjazz/wjazzd.db   # humans vs humans vs us (task 2)
    python scripts/figure_prior.py build                 # write src/swingscribe/figure-prior.json

The corpus is `benchmark/Transcriptions_Other/musicxml/`: the MusicXML that
`pdf2musicxml` read off 275 PDF transcriptions by human transcribers
(docs/pdf2musicxml.md, docs/figure-prior-brief.md). A FIGURE is the sorted
set of onset positions inside one quarter-note beat, as exact fractions of
the beat: "0 1/2" is an eighth pair, "0 1/3 2/3" a triplet, "0 3/4" a
dotted eighth and a sixteenth, "-" a beat with no onset. It is the general
form of the conventions the quantizer already carries one rule at a time
(CLAUDE.md, R27-R29): how often a human writes each one.

What counts, and what is left out (the brief's rules, the listener's first):

- a bar whose notes do not FILL its time signature is excluded, without
  exception: a short or long bar is a certain sign of an OMR mistake
  somewhere in it, and there is no way to say where;
- a beat with two onsets at one position is an engine duplicate, not a
  figure, and is excluded;
- a bar the converter's own tuplet bookkeeping names as one it could not
  apply a printed tuplet number to (`tuplet_notes` in the manifest) is a
  bar the tool itself doubts, and is excluded; a reading's tuplet the page
  does not print is only COUNTED per file by the converter, so the strict
  filter drops every tuplet bar of such a file;
- a tied-into note is not an onset, a grace note is not an onset, a chord
  is one onset;
- compound metres (6/8, 12/8, 10/8, 8/8) have no quarter-note beat and are
  left out; 4/4, 3/4, 2/4 and 5/4 are counted per quarter, and 2/2 per
  quarter TOO but in a table of its own until it has been looked at;
- a corpus title that is a recording under `benchmark/` is dropped
  (`OVERLAP`), so the judge set stays a hold-out.

Two filters are reported side by side: PLAIN (the rules above) and STRICT
(plain, plus every bar the two OMR engines read differently, the manifest's
`check_disagreeing`). If the top figures agree under both, the OMR noise is
not shaping the table.

Only aggregates leave this script. The pages are transcriptions of
commercial recordings and `benchmark/` is gitignored (CLAUDE.md, plan
section 12): no note list, no bar-by-bar content, ever.

Standard library only, so it runs anywhere the corpus does.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from xml.etree import ElementTree

REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS = REPO_ROOT / "benchmark" / "Transcriptions_Other" / "musicxml"
PRIOR_PATH = REPO_ROOT / "src" / "swingscribe" / "figure-prior.json"

# Corpus files whose recording is under benchmark/ (the WJazzD folder, the
# Omnibook, or the listener's twelve): the judge set is a hold-out only if
# these stay out of the count. Same performer and tune; the take is not
# always knowable from the page, so a match is dropped either way.
OVERLAP = {
    "Cheese Cake - Dexter Gordon Solo EDITED 2025": "wjazzd/Dexter_Gordon_Cheese_Cake_solo_121",
    "Joy-Spring-Clifford-Browns-Trumpet-Solo": "wjazzd/Clifford_Brown_Joy_Spring_solo_93",
    "Gingerbread Boy - Wayne Shorter Solo": (
        "wjazzd/Herbie_Hancock_Gingerbread_Boy_solo_186 (the same Miles Smiles track)"
    ),
    "Charlie-Parker-Embraceable-You": "wjazzd/Charlie_Parker_Embraceable_You_solo_56",
    "Charlie-Parker-Moose-the-Mooche": "Omnibook/Moose_The_Mooche",
    "Moose the Mooche - Hank Mobley, Sonny Stitt, Charlie Parker Solos": (
        "Omnibook/Moose_The_Mooche (Parker's chorus among the three)"
    ),
    "Charlie-Parker-Scrapple-from-the-Apple": "Omnibook/Scrapple_From_The_Apple",
}
# Looked at and kept: "Ornithology (12-11-1948) - Charlie Parker Solo" is the
# 1948 take; the benchmark's (WJazzD solo 61, the Omnibook side) is 1946-07-29.

SOURCES = ("Wesley Chin", "maxgrynchuk", "peterandwillanderson")
MIN_TEMPO = 40.0  # a mark under this is a misread digit ("quarter = 20")
TEMPO_BANDS = ((100.0, "<100"), (160.0, "100-160"), (220.0, "160-220"), (300.0, "220-300"))
DENSITY_BUCKETS = ((0.5, "<0.5"), (1.0, "0.5-1"), (1.5, "1-1.5"), (2.0, "1.5-2"), (3.0, "2-3"))
DENSITY_HALF_WINDOW = 4  # beats either side: "the surrounding eight beats"
UNSEEN = 0.5  # half a count for a figure the table never saw

VALUE_NAMES = {
    Fraction(4): "whole",
    Fraction(3): "half.",
    Fraction(2): "half",
    Fraction(3, 2): "quarter.",
    Fraction(1): "quarter",
    Fraction(3, 4): "eighth.",
    Fraction(1, 2): "eighth",
    Fraction(3, 8): "16th.",
    Fraction(1, 4): "16th",
    Fraction(3, 16): "32nd.",
    Fraction(1, 8): "32nd",
}


# ── the reader ───────────────────────────────────────────────────────────────


@dataclass
class Bar:
    index: int  # 0-based position in the file
    number: str  # the printed measure number
    signature: tuple[int, int]
    length: Fraction  # quarter notes the signature calls for
    filled: Fraction  # quarter notes the notes and rests occupy
    onsets: list[Fraction] = field(default_factory=list)  # quarters from the bar's start
    rests: list[tuple[Fraction, Fraction]] = field(default_factory=list)  # (position, length)
    note_kinds: list[str] = field(default_factory=list)  # written symbols, chords collapsed
    rest_kinds: list[str] = field(default_factory=list)
    tie_starts: int = 0
    tied_into: int = 0
    tuplet_notes: int = 0
    tuplet_groups: int = 0
    voices: int = 1
    duplicate_beats: set[int] = field(default_factory=set)  # two onsets at one position
    whole_rest: bool = False

    @property
    def fills(self) -> bool:
        return self.filled == self.length

    @property
    def quarter_beats(self) -> bool:
        return self.signature[1] in (2, 4)

    def figures(self) -> list[tuple[int, tuple[Fraction, ...]]]:
        """(beat index, figure) per quarter-note beat of the bar."""
        out = []
        for beat in range(int(self.length)):
            inside = sorted(o - beat for o in self.onsets if beat <= o < beat + 1)
            out.append((beat, tuple(inside)))
        return out


@dataclass
class Transcription:
    path: Path
    name: str
    source: str
    tempo: float | None
    bars: list[Bar]
    manifest: dict = field(default_factory=dict)

    @property
    def disagreeing(self) -> set[str]:
        return {str(n) for n in self.manifest.get("check_disagreeing", [])}

    @property
    def doubted(self) -> set[str]:
        """Bars the converter names as ones it could not apply a printed
        tuplet number to (a `bar N: ... printed, <why not>` note), or whose
        tuplet it had to strip."""
        out = set()
        for note in self.manifest.get("tuplet_notes", []):
            match = re.match(r"bar (\S+): ", note)
            if match and " made a " not in note:
                out.add(match.group(1))
        return out

    @property
    def tuplets_unprinted(self) -> int:
        return int(self.manifest.get("tuplets_unprinted", 0) or 0)


def source_of(name: str) -> str:
    """Which of the three sources a file came from, told by the filename's
    shape (docs/pdf2musicxml.md does the same): Wesley Chin's are "Tune -
    Player Solo", maxgrynchuk.com's are hyphenated and end in the soloist's
    "-Solo", and peterandwillanderson.com's are "Player-Tune" (a book split
    into transcriptions carries " - 01 " after the name)."""
    if re.search(r" - \d\d ", name):
        return "peterandwillanderson"
    if " - " in name:
        return "Wesley Chin"
    if re.search(r"-solo(-[\w-]+)?$|-Full-Score$|-Cadenza$", name, re.IGNORECASE) or name in (
        "Minuano-Six-Eight-Bobby-Shew",
        "Maynard-Ferguson-Trumpet-La-Prima-Notte-Di-Quiete",
    ):
        return "maxgrynchuk"
    return "peterandwillanderson"


def _written_kind(note: ElementTree.Element, duration: Fraction) -> str:
    kind = note.findtext("type")
    if kind is None:
        kind = VALUE_NAMES.get(duration, "measure" if note.get("measure") == "yes" else "other")
    kind += "." * len(note.findall("dot"))
    tm = note.find("time-modification")
    if tm is not None:
        kind += f"[{tm.findtext('actual-notes')}:{tm.findtext('normal-notes')}]"
    return kind


def read_transcription(path: Path, manifest: dict | None = None) -> Transcription:
    """One MusicXML file as bars of onsets. `backup`/`forward` are honoured,
    a tied-into note and a grace note are not onsets, a chord is one onset."""
    root = ElementTree.parse(path).getroot()
    part = root.find("part")
    tempo = None
    for sound in root.iter("sound"):
        if sound.get("tempo"):
            try:
                tempo = float(sound.get("tempo"))
            except ValueError:
                tempo = None
            break
    bars: list[Bar] = []
    divisions = Fraction(1)
    signature = (4, 4)
    for index, measure in enumerate(part.findall("measure") if part is not None else []):
        if (value := measure.findtext("attributes/divisions")) is not None:
            divisions = Fraction(value)
        beats = measure.findtext("attributes/time/beats")
        beat_type = measure.findtext("attributes/time/beat-type")
        if beats and beat_type:
            signature = (int(beats), int(beat_type))
        length = Fraction(signature[0] * 4, signature[1])
        bar = Bar(index, measure.get("number", str(index + 1)), signature, length, Fraction(0))
        cursor = Fraction(0)
        voices: set[str] = set()
        positions: Counter = Counter()
        last_onset: Fraction | None = None
        for element in measure:
            if element.tag == "backup":
                cursor -= Fraction(element.findtext("duration") or 0) / divisions
                continue
            if element.tag == "forward":
                cursor += Fraction(element.findtext("duration") or 0) / divisions
                bar.filled = max(bar.filled, cursor)
                continue
            if element.tag != "note":
                continue
            if element.find("grace") is not None:
                continue
            voices.add(element.findtext("voice") or "1")
            duration = Fraction(element.findtext("duration") or 0) / divisions
            chord = element.find("chord") is not None
            if element.find("rest") is not None:
                bar.rests.append((cursor, duration))
                bar.rest_kinds.append(_written_kind(element, duration))
                bar.whole_rest = bar.whole_rest or element.find("rest").get("measure") == "yes"
                cursor += duration
                bar.filled = max(bar.filled, cursor)
                continue
            if chord:
                continue  # one onset with the note before it
            if element.find("time-modification") is not None:
                bar.tuplet_notes += 1
            if element.find("notations/tuplet[@type='start']") is not None:
                bar.tuplet_groups += 1
            bar.note_kinds.append(_written_kind(element, duration))
            tied_into = element.find("tie[@type='stop']") is not None
            if element.find("tie[@type='start']") is not None:
                bar.tie_starts += 1
            if tied_into:
                bar.tied_into += 1
            else:
                bar.onsets.append(cursor)
                positions[cursor] += 1
                last_onset = cursor
            cursor += duration
            bar.filled = max(bar.filled, cursor)
        bar.voices = max(1, len(voices))
        bar.onsets.sort()
        for position, count in positions.items():
            if count > 1:
                bar.duplicate_beats.add(int(position))
        del last_onset
        bars.append(bar)
    name = path.name.removesuffix(".musicxml")
    return Transcription(path, name, source_of(name), tempo, bars, manifest or {})


def load_manifests(folder: Path) -> dict[str, dict]:
    """Manifest entry per output file name; a book's manifest holds several."""
    out: dict[str, dict] = {}
    for path in sorted(folder.glob("*.pdf2musicxml.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for entry in data.get("transcriptions", []):
            output = entry.get("output")
            if output:
                out[Path(output).name] = entry
    return out


def load_corpus(folder: Path = CORPUS, log=print) -> list[Transcription]:
    manifests = load_manifests(folder)
    out = []
    for path in sorted(folder.glob("*.musicxml")):
        name = path.name.removesuffix(".musicxml")
        if name in OVERLAP:
            log(f"  dropped (recording under benchmark/): {name} <-> {OVERLAP[name]}")
            continue
        out.append(read_transcription(path, manifests.get(path.name)))
    return out


# ── the figures ──────────────────────────────────────────────────────────────


def figure_key(figure: tuple[Fraction, ...]) -> str:
    return " ".join(str(f) for f in figure) if figure else "-"


def onset_count(key: str) -> int:
    return 0 if key == "-" else len(key.split())


@dataclass
class BeatRecord:
    """One counted beat, with everything a conditioning might ask of it."""

    file: str
    source: str
    tempo: float | None
    signature: tuple[int, int]
    bar_index: int
    beat: int
    figure: str
    previous: str | None  # the beat before, if it was counted; None at a gap
    density: float | None  # onsets per beat over the surrounding eight beats


def bar_included(t: Transcription, bar: Bar, strict: bool) -> bool:
    if not bar.fills or not bar.quarter_beats:
        return False
    if bar.number in t.doubted:
        return False
    if strict:
        if bar.number in t.disagreeing:
            return False
        if t.tuplets_unprinted and bar.tuplet_groups:
            return False
    return True


def beat_records(t: Transcription, strict: bool = False) -> list[BeatRecord]:
    """Every counted beat of one transcription, in order."""
    # The density is read off the whole file's beat sequence, excluded bars
    # included: it is what the quantizer would see around a beat, not a
    # curated view. Compound bars have no quarter beat and are skipped.
    sequence: list[int] = []  # onsets per quarter beat, in file order
    where: dict[tuple[int, int], int] = {}
    for bar in t.bars:
        if not bar.quarter_beats:
            continue
        for beat, figure in bar.figures():
            where[(bar.index, beat)] = len(sequence)
            sequence.append(len(figure))
    out: list[BeatRecord] = []
    previous: str | None = None
    for bar in t.bars:
        if not bar.quarter_beats:
            previous = None
            continue
        if not bar_included(t, bar, strict):
            previous = None
            continue
        for beat, figure in bar.figures():
            if beat in bar.duplicate_beats:
                previous = None
                continue
            key = figure_key(figure)
            at = where[(bar.index, beat)]
            around = (
                sequence[max(0, at - DENSITY_HALF_WINDOW) : at]
                + sequence[at + 1 : at + 1 + DENSITY_HALF_WINDOW]
            )
            density = sum(around) / len(around) if around else None
            out.append(
                BeatRecord(
                    t.name,
                    t.source,
                    t.tempo,
                    bar.signature,
                    bar.index,
                    beat,
                    key,
                    previous,
                    density,
                )
            )
            previous = key
    return out


def tempo_band(tempo: float | None) -> str | None:
    if tempo is None or tempo < MIN_TEMPO:
        return None
    for ceiling, band in TEMPO_BANDS:
        if tempo < ceiling:
            return band
    return ">=300"


def density_bucket(density: float | None) -> str | None:
    if density is None:
        return None
    for ceiling, bucket in DENSITY_BUCKETS:
        if density < ceiling:
            return bucket
    return ">=3"


def is_cut_time(record: BeatRecord) -> bool:
    return record.signature[1] == 2


# ── tallies ──────────────────────────────────────────────────────────────────


def tally(records: list[BeatRecord]) -> Counter:
    return Counter(r.figure for r in records)


def share_table(counter: Counter, top: int = 30) -> list[tuple[str, int, float]]:
    total = sum(counter.values()) or 1
    return [(k, n, 100.0 * n / total) for k, n in counter.most_common(top)]


def corpus_summary(transcriptions: list[Transcription]) -> dict:
    """The brief's first table: what the corpus holds before any filter."""
    bars = sum(len(t.bars) for t in transcriptions)
    full = sum(1 for t in transcriptions for b in t.bars if b.fills)
    notes = sum(len(b.note_kinds) for t in transcriptions for b in t.bars)
    tuplets = sum(b.tuplet_notes for t in transcriptions for b in t.bars)
    tied = sum(b.tied_into for t in transcriptions for b in t.bars)
    rests = sum(len(b.rests) for t in transcriptions for b in t.bars)
    signatures = Counter(
        f"{b.signature[0]}/{b.signature[1]}" for t in transcriptions for b in t.bars
    )
    with_tempo = [t for t in transcriptions if t.tempo is not None and t.tempo >= MIN_TEMPO]
    bands = Counter(tempo_band(t.tempo) for t in with_tempo)
    disagreeing = sum(len(t.disagreeing) for t in transcriptions)
    doubted = sum(len(t.doubted) for t in transcriptions)
    return {
        "transcriptions": len(transcriptions),
        "per_source": dict(Counter(t.source for t in transcriptions)),
        "notes": notes,
        "rests": rests,
        "tuplet_notes": tuplets,
        "tuplet_share": round(tuplets / notes, 4) if notes else None,
        "tied_into": tied,
        "bars": bars,
        "bars_full": full,
        "bars_full_share": round(full / bars, 4) if bars else None,
        "bars_disagreeing": disagreeing,
        "bars_doubted_by_tuplet_bookkeeping": doubted,
        "files_with_tempo": len(with_tempo),
        "tempo_bands": dict(bands),
        "tempo_marks_under_min": sum(
            1 for t in transcriptions if t.tempo is not None and t.tempo < MIN_TEMPO
        ),
        "signatures": dict(signatures.most_common()),
    }


def stratum_tables(records: list[BeatRecord], top: int = 30) -> dict:
    """Pooled and per-source figure tables, quarter-beat metres only."""
    quarter = [r for r in records if not is_cut_time(r)]
    cut = [r for r in records if is_cut_time(r)]
    out = {
        "pooled": _table_block(quarter),
        "cut_time": _table_block(cut),
        "per_source": {s: _table_block([r for r in quarter if r.source == s]) for s in SOURCES},
    }
    return out


def _table_block(records: list[BeatRecord], top: int = 30) -> dict:
    counter = tally(records)
    with_onset = sum(n for k, n in counter.items() if k != "-")
    return {
        "beats": len(records),
        "beats_with_onset": with_onset,
        "files": len({r.file for r in records}),
        "figures": len(counter),
        "top": [(k, n, round(p, 2)) for k, n, p in share_table(counter, top)],
        "counts": dict(counter.most_common()),
    }


def rest_tables(transcriptions: list[Transcription], strict: bool = False) -> dict:
    """Where in the beat a rest starts, and what value it is written as,
    over the same counted bars."""
    positions: Counter = Counter()
    values: Counter = Counter()
    n = 0
    for t in transcriptions:
        for bar in t.bars:
            if not bar_included(t, bar, strict) or bar.signature[1] != 4:
                continue
            for position, length in bar.rests:
                n += 1
                positions[str(position - int(position))] += 1
                values[VALUE_NAMES.get(length, "measure" if length == bar.length else "other")] += 1
    return {
        "rests": n,
        "position_in_beat": [
            (k, v, round(100.0 * v / max(1, n), 2)) for k, v in positions.most_common(12)
        ],
        "values": [(k, v, round(100.0 * v / max(1, n), 2)) for k, v in values.most_common(12)],
    }


def vocabulary(transcriptions: list[Transcription], strict: bool = False) -> dict:
    """Tuplet share and tie rate per source, over the counted bars, beside the
    survey's numbers for the listener's pages and the Omnibook."""
    out = {}
    for source in SOURCES + ("all",):
        notes = tuplets = ties = 0
        for t in transcriptions:
            if source != "all" and t.source != source:
                continue
            for bar in t.bars:
                if not bar_included(t, bar, strict):
                    continue
                notes += len(bar.note_kinds)
                tuplets += bar.tuplet_notes
                ties += bar.tie_starts
        out[source] = {
            "notes": notes,
            "tuplet_share": round(tuplets / notes, 4) if notes else None,
            "tie_rate": round(ties / notes, 4) if notes else None,
        }
    return out


# ── conditioning (task 3) ────────────────────────────────────────────────────


def entropy(counter: Counter) -> float:
    total = sum(counter.values())
    if not total:
        return 0.0
    return -sum(n / total * math.log2(n / total) for n in counter.values() if n)


def conditional_entropy(records: list[BeatRecord], key) -> tuple[float, int, str]:
    """H(figure | key), and the count behind the sparsest cell."""
    groups: dict = defaultdict(Counter)
    for r in records:
        groups[key(r)][r.figure] += 1
    total = sum(sum(c.values()) for c in groups.values())
    h = sum(sum(c.values()) / total * entropy(c) for c in groups.values()) if total else 0.0
    sparsest = (
        min(groups.items(), key=lambda kv: sum(kv[1].values())) if groups else (None, Counter())
    )
    return h, sum(sparsest[1].values()), str(sparsest[0])


def held_out_cross_entropy(records: list[BeatRecord], key) -> float:
    """Bits per beat when each file's beats are scored on a table counted
    from the OTHER files (two folds by file), add-half smoothed over the
    figures seen anywhere. The honest version of the conditional entropy:
    a conditioning with many cells looks sharp in-sample and is not."""
    files = sorted({r.file for r in records})
    folds = [{f for i, f in enumerate(files) if i % 2 == k} for k in (0, 1)]
    alphabet = {r.figure for r in records}
    bits = 0.0
    for fold in folds:
        train = [r for r in records if r.file not in fold]
        test = [r for r in records if r.file in fold]
        tables: dict = defaultdict(Counter)
        for r in train:
            tables[key(r)][r.figure] += 1
        for r in test:
            table = tables.get(key(r), Counter())
            total = sum(table.values()) + UNSEEN * len(alphabet)
            bits -= math.log2((table[r.figure] + UNSEEN) / total)
    return bits / len(records) if records else 0.0


def figure_class(figure: str | None) -> str:
    """A figure's family, for a bigram small enough to ship: what grid the
    beat before was written on."""
    if figure is None:
        return "(gap)"
    if figure == "-":
        return "empty"
    if figure == "0 1/2":
        return "pair"
    if figure in ("0", "1/2"):
        return "single"
    if "/3" in figure or "/6" in figure:
        return "ternary"
    if "/4" in figure or "/8" in figure:
        return "sixteenths"
    return "other"


def conditioning_report(records: list[BeatRecord]) -> dict:
    quarter = [r for r in records if not is_cut_time(r) and r.figure != "-"]
    marked = [r for r in quarter if tempo_band(r.tempo) is not None]
    conditionings = {
        "nothing": lambda r: "all",
        "tempo band": lambda r: tempo_band(r.tempo),
        "onset density": lambda r: density_bucket(r.density),
        "previous figure": lambda r: r.previous or "(gap)",
        "previous class": lambda r: figure_class(r.previous),
        "density+prev class": lambda r: (density_bucket(r.density), figure_class(r.previous)),
        "meter": lambda r: f"{r.signature[0]}/{r.signature[1]}",
        "source": lambda r: r.source,
    }
    # The quantizer never chooses between a two-onset figure and a
    # three-onset one -- the onset count is the beat's own -- so the bits a
    # conditioning carries about the CHOICE are the bits it carries beyond
    # the count: H(F | count) against H(F | count, c), held out.
    count_of = lambda r: onset_count(r.figure)  # noqa: E731
    out = {}
    for name, key in conditionings.items():
        subset = marked if name == "tempo band" else quarter
        h, sparse_n, sparse_cell = conditional_entropy(subset, key)
        h0 = entropy(tally(subset))
        out[name] = {
            "beats": len(subset),
            "files": len({r.file for r in subset}),
            "unigram_bits": round(h0, 4),
            "conditional_bits": round(h, 4),
            "gain_bits": round(h0 - h, 4),
            "held_out_bits": round(held_out_cross_entropy(subset, key), 4),
            "held_out_unigram_bits": round(held_out_cross_entropy(subset, lambda r: "all"), 4),
            "held_out_given_count_bits": round(
                held_out_cross_entropy(subset, lambda r, k=key: (count_of(r), k(r))), 4
            ),
            "held_out_count_only_bits": round(held_out_cross_entropy(subset, count_of), 4),
            "sparsest_cell": sparse_cell,
            "sparsest_cell_beats": sparse_n,
            "cells": len({key(r) for r in subset}),
        }
    # The same three on the marked files only, so tempo and density are
    # compared on one set.
    for name in ("onset density", "previous figure"):
        key = conditionings[name]
        h, _n, _c = conditional_entropy(marked, key)
        out[name]["on_marked_files"] = {
            "beats": len(marked),
            "gain_bits": round(entropy(tally(marked)) - h, 4),
            "held_out_bits": round(held_out_cross_entropy(marked, key), 4),
        }
    out["tempo band"]["on_marked_files"] = {
        "beats": len(marked),
        "held_out_unigram_bits": round(held_out_cross_entropy(marked, lambda r: "all"), 4),
    }
    # Per-band tables, counts behind every cell.
    per_band: dict = {}
    for r in marked:
        per_band.setdefault(tempo_band(r.tempo), []).append(r)
    out["per_tempo_band"] = {
        band: _table_block(rs, top=15) | {"files": len({r.file for r in rs})}
        for band, rs in sorted(per_band.items(), key=lambda kv: kv[0])
    }
    per_density: dict = {}
    for r in quarter:
        per_density.setdefault(density_bucket(r.density), []).append(r)
    out["per_density"] = {
        bucket: _table_block(rs, top=15)
        for bucket, rs in sorted(per_density.items(), key=lambda kv: str(kv[0]))
    }
    return out


# ── the prior (task 4's table) ───────────────────────────────────────────────


def prior_table(records: list[BeatRecord]) -> dict:
    """The aggregate that ships: counts per figure over beats WITH an onset,
    quarter-beat metres, plain filter. The quantizer only ever compares
    candidates for a beat that has notes, so the empty beat never competes;
    it is kept in the file for the record."""
    quarter = [r for r in records if not is_cut_time(r)]
    counter = tally(quarter)
    with_onset = {k: n for k, n in counter.items() if k != "-"}
    return {
        "source": "benchmark/Transcriptions_Other/musicxml, scripts/figure_prior.py",
        "files": len({r.file for r in quarter}),
        "beats": len(quarter),
        "beats_with_onset": sum(with_onset.values()),
        "empty_beats": counter.get("-", 0),
        "unseen": UNSEEN,
        "counts": dict(sorted(with_onset.items(), key=lambda kv: (-kv[1], kv[0]))),
    }


# ── the other humans, and us (task 2) ────────────────────────────────────────


def figures_from_positions(positions: list[float], beats_per_bar: float, bars: int) -> Counter:
    """Figures from onset positions in quarter notes since bar 1 (a parsed
    score); every quarter beat up to the last bar counts, empty ones too."""
    counter: Counter = Counter()
    by_beat: dict[int, list[Fraction]] = defaultdict(list)
    for p in positions:
        exact = Fraction(p).limit_denominator(48)
        by_beat[int(exact)].append(exact - int(exact))
    last = max(int(round(bars * beats_per_bar)), max(by_beat) + 1 if by_beat else 0)
    for beat in range(last):
        inside = tuple(sorted(set(by_beat.get(beat, []))))
        counter[figure_key(inside)] += 1
    return counter


def figures_from_notation(notation) -> Counter:
    """Our page: voice 1, a tied-into note is not an onset, per quarter beat."""
    counter: Counter = Counter()
    for bar in notation.bars:
        num, den = bar.time_signature
        if den not in (2, 4):
            continue
        length = Fraction(num * 4, den)
        onsets = sorted(
            {
                Fraction(n.beat).limit_denominator(48)
                for n in bar.notes
                if n.voice == 1 and not n.is_rest and not n.tie_stop
            }
        )
        for beat in range(int(length)):
            inside = tuple(o - beat for o in onsets if beat <= o < beat + 1)
            counter[figure_key(inside)] += 1
    return counter


def compare_report(db_path: Path | None, grids_path: Path | None) -> dict:
    """Humans against humans (the corpus, the twelve hand scores, the
    Omnibook), then us against each, over the pages the harness builds."""
    import contextlib
    import io
    import logging

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    sys.path.insert(0, str(REPO_ROOT / "src"))
    import run_eval

    from swingscribe import mscz

    logging.disable(logging.CRITICAL)
    quiet = lambda *_: None  # noqa: E731
    out: dict = {"humans": {}, "ours": {}}
    corpus = load_corpus(log=quiet)
    records = [r for t in corpus for r in beat_records(t)]
    out["humans"]["corpus"] = _table_block([r for r in records if not is_cut_time(r)])

    with contextlib.redirect_stdout(io.StringIO()):
        cache = run_eval.notes_cache(0.2, 0.0)
        runs = run_eval.transcribe_all(cache, 0.2, 0.0, log=quiet)
        grids = run_eval.beat_grids(grids_path or run_eval.GRIDS_CACHE, log=quiet)
    hand: Counter = Counter()
    book: Counter = Counter()
    ours_hand: Counter = Counter()
    ours_book: Counter = Counter()
    n_hand = n_book = 0
    per_page: dict = {}
    for key, run in sorted(runs.items()):
        if run_eval.take_of(key) is not None:
            continue
        sidecar_path = run_eval.BENCH / f"{run_eval.track_of(key)}.swingscribe.json"
        if not sidecar_path.is_file():
            continue
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        score_path = sidecar.get("score")
        if not score_path or not Path(score_path).is_file():
            continue
        track = run_eval.track_of(key)
        if track not in grids:
            continue
        is_book = run_eval.is_omnibook(key)
        score = Path(score_path)
        if not is_book and score.suffix.lower() not in (".mscz", ".mscx"):
            continue
        with contextlib.redirect_stdout(io.StringIO()):
            notation = run_eval.notate_run(key, run, grids[track])
        if notation is None or not notation.bars:
            continue
        ours = figures_from_notation(notation)
        if is_book:
            t = read_transcription(score)
            theirs = tally(beat_records(t))
            book += theirs
            ours_book += ours
            n_book += 1
        else:
            parsed = mscz.parse_any(score)
            theirs = figures_from_positions(
                [n.position for n in parsed.melody], parsed.beats_per_bar, parsed.bars
            )
            hand += theirs
            ours_hand += ours
            n_hand += 1
        per_page[key] = {"ours": dict(ours.most_common(12)), "theirs": dict(theirs.most_common(12))}
    out["humans"]["hand scores"] = _counter_block(hand, n_hand)
    out["humans"]["Omnibook"] = _counter_block(book, n_book)
    out["ours"]["hand-score set"] = _counter_block(ours_hand, n_hand)
    out["ours"]["Omnibook set"] = _counter_block(ours_book, n_book)

    if db_path is not None:
        with contextlib.redirect_stdout(io.StringIO()):
            located = run_eval.wjazz_scores(db_path, runs, grids, run_eval.default_jobs())
        ours_wjazz: Counter = Counter()
        n = 0
        for key, entry in sorted(located.items()):
            if "melid" not in entry:
                continue
            name = entry.get("run") or key.split(" [")[0]
            track = run_eval.track_of(name)
            if name not in runs or track not in grids:
                continue
            window = (
                entry["solo_start"] - run_eval.SOLO_MARGIN_S,
                entry["solo_end"] + run_eval.SOLO_MARGIN_S,
            )
            with contextlib.redirect_stdout(io.StringIO()):
                notation = run_eval.notate_run(name, runs[name], grids[track], region=window)
            if notation is None or not notation.bars:
                continue
            ours_wjazz += figures_from_notation(notation)
            n += 1
        out["ours"]["WJazzD set"] = _counter_block(ours_wjazz, n)
    out["ratios"] = ratio_table(out)
    return out


def _counter_block(counter: Counter, files: int, top: int = 30) -> dict:
    with_onset = sum(n for k, n in counter.items() if k != "-")
    return {
        "beats": sum(counter.values()),
        "beats_with_onset": with_onset,
        "files": files,
        "figures": len(counter),
        "top": [(k, n, round(p, 2)) for k, n, p in share_table(counter, top)],
        "counts": dict(counter.most_common()),
    }


def ratio_table(report: dict) -> dict:
    """figure, human share, our share, ratio -- over beats WITH an onset, on
    the same pages, for each pairing the harness offers."""
    pairs = [
        ("hand scores", "hand-score set"),
        ("Omnibook", "Omnibook set"),
        ("corpus", "hand-score set"),
        ("corpus", "Omnibook set"),
    ]
    if "WJazzD set" in report["ours"]:
        pairs.append(("corpus", "WJazzD set"))
    out = {}
    for human, ours in pairs:
        h = report["humans"][human]["counts"]
        o = report["ours"][ours]["counts"]
        hn = sum(n for k, n in h.items() if k != "-") or 1
        on = sum(n for k, n in o.items() if k != "-") or 1
        rows = []
        for figure in sorted(set(h) | set(o), key=lambda k: -(h.get(k, 0) / hn + o.get(k, 0) / on)):
            if figure == "-":
                continue
            hs, os_ = 100.0 * h.get(figure, 0) / hn, 100.0 * o.get(figure, 0) / on
            if hs < 0.1 and os_ < 0.1:
                continue
            ratio = round(os_ / hs, 2) if hs else None
            rows.append(
                (figure, h.get(figure, 0), round(hs, 2), o.get(figure, 0), round(os_, 2), ratio)
            )
        out[f"{human} vs {ours}"] = {"human_beats": hn, "our_beats": on, "rows": rows[:40]}
    return out


# ── rendering ────────────────────────────────────────────────────────────────


def render_block(title: str, block: dict, top: int = 20) -> None:
    print(
        f"\n== {title}: {block['beats']} beats ({block['beats_with_onset']} with an onset) "
        f"over {block['files']} files, {block['figures']} distinct figures"
    )
    print(f"  {'figure':22} {'n':>7} {'share':>7}")
    for figure, n, pct in block["top"][:top]:
        print(f"  {figure:22} {n:7d} {pct:6.2f}%")


def render_count(result: dict) -> None:
    s = result["summary"]
    print("== Corpus ==")
    print(f"  transcriptions {s['transcriptions']} {s['per_source']}")
    print(
        f"  notes {s['notes']}, rests {s['rests']}, tuplet notes {s['tuplet_notes']} "
        f"({100 * s['tuplet_share']:.1f}%), tied-into {s['tied_into']}"
    )
    print(
        f"  bars {s['bars']}, filling their signature {s['bars_full']} "
        f"({100 * s['bars_full_share']:.1f}%), engines disagree on {s['bars_disagreeing']}, "
        f"doubted by tuplet bookkeeping {s['bars_doubted_by_tuplet_bookkeeping']}"
    )
    print(
        f"  tempo on {s['files_with_tempo']} files {s['tempo_bands']}; "
        f"marks under {MIN_TEMPO:.0f} dropped: {s['tempo_marks_under_min']}"
    )
    print(f"  signatures {s['signatures']}")
    for name in ("plain", "strict"):
        tables = result[name]
        render_block(f"{name} filter, pooled quarter-beat metres", tables["pooled"])
        for source, block in tables["per_source"].items():
            render_block(f"{name} filter, {source}", block, top=12)
        render_block(f"{name} filter, 2/2 per quarter", tables["cut_time"], top=12)
        rests = result[f"rests_{name}"]
        print(f"\n== {name} filter, rests: {rests['rests']} in the counted 4/4, 3/4, 2/4 bars")
        print(
            "  by position in beat: "
            + ", ".join(f"{k} {p:.1f}%" for k, _n, p in rests["position_in_beat"])
        )
        print("  by value: " + ", ".join(f"{k} {p:.1f}%" for k, _n, p in rests["values"]))
        print(f"\n== {name} filter, vocabulary per source")
        for source, v in result[f"vocabulary_{name}"].items():
            if v["notes"]:
                print(
                    f"  {source:22} notes {v['notes']:6d} tuplets {100 * v['tuplet_share']:.1f}% "
                    f"tie rate {v['tie_rate']:.3f}"
                )


def render_condition(report: dict) -> None:
    print("\n== Conditioning: figure entropy over beats with an onset (bits) ==")
    print(
        f"  {'conditioning':18} {'beats':>7} {'files':>5} {'cells':>5} {'H(F)':>7} {'H(F|c)':>7} "
        f"{'gain':>6} {'held-out':>9} {'unigram':>8} {'|count':>7} {'|count,c':>9}  sparsest cell"
    )
    for name, row in report.items():
        if name in ("per_tempo_band", "per_density"):
            continue
        print(
            f"  {name:18} {row['beats']:7d} {row['files']:5d} {row['cells']:5d} "
            f"{row['unigram_bits']:7.3f} "
            f"{row['conditional_bits']:7.3f} {row['gain_bits']:6.3f} {row['held_out_bits']:9.3f} "
            f"{row['held_out_unigram_bits']:8.3f} {row['held_out_count_only_bits']:7.3f} "
            f"{row['held_out_given_count_bits']:9.3f}  {row['sparsest_cell']} "
            f"({row['sparsest_cell_beats']})"
        )
        if "on_marked_files" in row:
            print(f"    on the tempo-marked files: {row['on_marked_files']}")
    for band, block in report["per_tempo_band"].items():
        render_block(f"tempo band {band}", block, top=10)
    for bucket, block in report["per_density"].items():
        render_block(f"onset density {bucket}", block, top=8)


def render_compare(report: dict) -> None:
    for name, block in report["humans"].items():
        render_block(f"human: {name}", block, top=16)
    for name, block in report["ours"].items():
        render_block(f"ours: {name}", block, top=16)
    for pairing, table in report["ratios"].items():
        print(
            f"\n== {pairing}: {table['human_beats']} human beats, "
            f"{table['our_beats']} of ours (with an onset)"
        )
        print(f"  {'figure':22} {'human n':>8} {'%':>6} {'ours n':>8} {'%':>6} {'ratio':>6}")
        for figure, hn, hp, on, op, ratio in table["rows"]:
            shown = f"{ratio:6.2f}" if ratio is not None else "     -"
            print(f"  {figure:22} {hn:8d} {hp:6.2f} {on:8d} {op:6.2f} {shown}")


def count(folder: Path, log=print) -> dict:
    corpus = load_corpus(folder, log=log)
    result = {"summary": corpus_summary(corpus)}
    for name, strict in (("plain", False), ("strict", True)):
        records = [r for t in corpus for r in beat_records(t, strict=strict)]
        result[name] = stratum_tables(records)
        result[f"rests_{name}"] = rest_tables(corpus, strict)
        result[f"vocabulary_{name}"] = vocabulary(corpus, strict)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "mode", nargs="?", default="count", choices=("count", "condition", "compare", "build")
    )
    parser.add_argument("--corpus", type=Path, default=CORPUS)
    parser.add_argument("--json", type=Path, default=None, help="write every count here")
    parser.add_argument(
        "--db", type=Path, default=None, help="wjazzd.db, for compare's WJazzD pages"
    )
    parser.add_argument("--grids", type=Path, default=None)
    args = parser.parse_args()

    if args.mode == "count":
        result = count(args.corpus)
        render_count(result)
    elif args.mode == "condition":
        corpus = load_corpus(args.corpus)
        result = conditioning_report([r for t in corpus for r in beat_records(t)])
        render_condition(result)
    elif args.mode == "compare":
        result = compare_report(args.db, args.grids)
        render_compare(result)
    else:
        corpus = load_corpus(args.corpus)
        result = prior_table([r for t in corpus for r in beat_records(t)])
        PRIOR_PATH.write_text(json.dumps(result, indent=1), encoding="utf-8")
        print(
            f"wrote {PRIOR_PATH}: {len(result['counts'])} figures over "
            f"{result['beats_with_onset']} beats with an onset from {result['files']} files"
        )
    if args.json:
        args.json.write_text(json.dumps(result, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
