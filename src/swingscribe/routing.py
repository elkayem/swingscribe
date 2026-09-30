"""Who is leading this span? A suggested ensemble and lead stem, from the stems.

`ensemble` decides whether the piano model is consulted (`uses_piano_oracle`),
and it defaults to horn-led, so every piano solo loses the oracle unless the
listener remembers to change the menu -- three benchmark piano solos once
skipped it exactly that way (CLAUDE.md, `ensemble: null`). The stems already
on disk say who is playing: over a piano solo the `piano` stem carries the
span and the stems a horn, guitar or voice is filed under go quiet.

This module turns per-stem levels over a span into a SUGGESTION with its
reason. It never sets anything. The asymmetry that shapes every threshold:

- suggesting horn-led for a piano solo is the status quo -- the default is
  already horn-led -- and costs the oracle's gain;
- suggesting trio for a HORN costs the whole line: a piano model asked about a
  saxophone vouches for nothing and rejection deletes every note (CLAUDE.md,
  "NEVER route a horn to the piano oracle").

So a piano suggestion needs two independent tests to agree, each of which
alone refuses every horn span and window measured, and anything between the
bands says "no suggestion". Measured over the 111 benchmark sidecars on the
Roformer stems (docs/routing.md): the piano is the loudest melodic stem in
0.98-1.00 of a trio span's active seconds and 0.00-0.55 of a horn span's; it
sits 12.9 dB or more above the loudest other melodic stem on a trio span and
at most +0.4 dB on a horn span. Nothing is suggested from a separator the
rule was not measured on: htdemucs_6s, held out, failed in both directions.

The decision (`suggest`) and the summary (`summarize`) are pure Python so they
run in CI; only `measure`, which reads wavs, imports numpy and soundfile, and
lazily.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

# The stems a lead line can live in. Drums and bass are the rhythm section;
# they enter only the solo-piano test and the "is the piano leading at all"
# guard, never the vote for who carries the line.
MELODIC_STEMS = ("other", "vocals", "guitar", "piano")
# Every stem a separator writes. A SUM the listener asked for
# (`library.COMBINED_STEMS`, "other+vocals") is not a source: it would stand
# as the "loudest stem" over its own parts, so it is ignored wherever passed.
SEPARATED_STEMS = (*MELODIC_STEMS, "bass", "drums")

# One reading per second. 0.5 s and 2 s windows move no conclusion (horn max
# piano share 0.516 / 0.548 / 0.467, trio min 0.972 / 0.983 / 0.966): the
# window only has to be longer than a note and shorter than a phrase.
WINDOW_S = 1.0

# A second counts toward the shares when its loudest melodic stem is within
# this many dB of the span's loud level (95th percentile of that per-second
# maximum). Silence and bleed between phrases then vote for nobody. 20, 30
# and 40 dB all give the same worst horn (0.548) and worst trio (0.983) at
# one-second windows.
ACTIVE_RANGE_DB = 30.0
# Below this nothing is playing, whatever the span's own loud level is: a
# span-scoped stem set is digital zero outside its span, and a stem the
# separator moved a source out of is digital zero where it left (CLAUDE.md,
# Oleo).
SILENCE_DB = -80.0
# The floor a mean square is clipped to before the log: -120 dBFS.
_EPS = 1e-12

# --- the piano side: BOTH must hold -------------------------------------
# The piano is the loudest melodic stem in at least this share of the
# span's active seconds. Trio spans 0.983-1.000 (n=11); horn spans at most
# 0.548 (n=100), and at most 0.824 over any window with MIN_ACTIVE_S of
# melody inside a horn span (n=200,966 windows).
PIANO_SHARE_MIN = 0.9
# ... and at least this many dB above the loudest OTHER melodic stem over the
# span. Trio spans +12.9 to +90.6 dB; horn spans at most +0.4 dB, and at
# most +3.0 dB over any judged window inside one.
PIANO_MARGIN_DB = 6.0
# ... and a LEAD, not a comp under a bass solo: within this many dB of the
# loudest of all the stems. Trio spans sit at most 5.6 dB under it (Flanagan's
# Giant Steps, under the bass), and at most 7.6 dB over any judged window
# inside one. No sidecar labels a bass solo, but three stretches of whole
# files TRACE as one (the piano sparse, the bass steady: Soul Station
# 390-455 s, Flanagan's Giant Steps 170-230 s, Melody for C 370-400 s).
# Selected whole they read 11.5, 16.0 and 13.3 dB under the bass, and at a
# 12 dB guard the first was called trio; at 9 dB all three are no
# suggestion, but some 20-30 s windows inside them still read trio, up to
# 8.9 dB under (docs/routing.md). Those stretches are the author's reading
# of a level trace, not a listener's label, and a bass solo called trio
# suggests the piano stem -- it sends no horn to the piano model -- so the
# guard is not tuned on them. Piano trading fours with the drums sits 6-8 dB
# under them over 20 s and is rightly still a piano call.
PIANO_LEAD_DB = 9.0

# --- the horn side: BOTH must hold --------------------------------------
# Horn spans 0.000-0.548 piano share, margin -96 to +0.4 dB (n=100); the
# band between these and the piano side's is "no suggestion". A wrong horn-led
# suggestion is the default's own failure, so this side may sit closer.
HORN_SHARE_MAX = 0.6
HORN_MARGIN_DB = 3.0
# Past this piano share a horn-led span is two leads taking turns -- a horn
# solo selected together with the piano solo after it reads 0.51-0.57 -- and
# the reason says so instead of "carries the span".
MIXED_SHARE = 0.4
# The separators the rule was measured on, and the only ones it answers for.
# bsroformer_sw (the default): all 11 benchmark piano solos in `piano`, and
# no horn window passing either piano test alone (margin at most +3.0 dB
# against 6, share at most 0.824 against 0.9). htdemucs_6s, held out, failed
# BOTH ways: it filed three of five piano solos under `guitar` (Hancock's
# Dolores and Orbits, Garland's Oleo), so a quiet piano stem there does not
# mean no piano; and inside Coltrane's soprano solo on My Favorite Things
# eight horn windows passed the share test, and the loudest horn window came
# 0.9 dB short of a trio call (+5.1 dB against 6; the Roformer's loudest
# window in that solo reads +0.4). A separator joins this set when
# scripts/routing_survey.py, run with --model, says so.
SUGGEST_MODELS = frozenset({"bsroformer_sw"})

# Too little melody to judge: the floor on ACTIVE seconds. Placed by every
# window inside the labelled spans, 10-40, 45, 50 and 60 s long at 1 s
# steps, on the Roformer stems (scripts/routing_survey.py, the floor sweep).
# Under 12 s one horn second in ten or eleven is all that keeps a horn
# window under the share test -- nine horn windows pass it at a 10 s floor,
# the loudest at +3.6 dB (Adam's Apple), 2.4 dB from the level test, which
# then stands alone between a horn and the piano model. At 12-14 s none
# passes but the share still reaches 0.857. From 15 s no horn window passes
# EITHER piano test on its own: piano share at most 0.824 (My Favorite
# Things, 17 s) and margin at most +3.0 dB (Adam's Apple, 16 s) over
# 200,966 judged horn windows, while every judged trio window (18,359) is
# still called trio, share 0.933 and margin +6.8 dB at the least. The
# shortest benchmark span is Carl Perkins' 17.4 s (17 active).
MIN_ACTIVE_S = 15.0

# --- trio or solo piano: the rhythm section ------------------------------
# Both route to the piano model (`uses_piano_oracle`), so this choice is
# cosmetic -- a wrong one costs nothing. On the eleven trio spans the bass
# stem sits at most 5.4 dB under the piano and the drums up to 31.4 dB under
# it (Sonny Clark's brushes), so the drums alone cannot say "no rhythm
# section". No solo-piano recording is in the benchmark (n=0).
SOLO_BASS_UNDER_DB = 20.0
SOLO_DRUMS_UNDER_DB = 30.0


@dataclass(frozen=True)
class StemLevels:
    """What the suggestion is made from: per-stem levels over one span.

    `level_db` is each stem's RMS over the span in dBFS; `lead_share` is, for
    each melodic stem present, the share of the span's active seconds in which
    it was the loudest melodic stem; `active_s` is how many seconds counted.
    """

    level_db: dict[str, float]
    lead_share: dict[str, float]
    active_s: float
    span_s: float


@dataclass(frozen=True)
class Suggestion:
    """A suggestion, never a setting. `ensemble` and `stem` are None when the
    stems cannot decide; `reason` says why either way, in the listener's
    words. `confidence` is 0.5 at a decision boundary rising to 1.0 a full
    band past it -- a normalised distance from the thresholds, NOT a
    probability (eleven piano spans cannot calibrate one). 0.0 with no
    suggestion."""

    ensemble: str | None
    stem: str | None
    confidence: float
    reason: str
    evidence: dict[str, float] = field(default_factory=dict)


def _db(mean_square: float) -> float:
    return 10.0 * math.log10(max(mean_square, 0.0) + _EPS)


def _percentile(values: Sequence[float], q: float) -> float:
    """Linear-interpolated percentile (numpy's default), without numpy."""
    ordered = sorted(values)
    if not ordered:
        return float("-inf")
    pos = (len(ordered) - 1) * q / 100.0
    lo = math.floor(pos)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def summarize(power: Mapping[str, Sequence[float]], window_s: float = WINDOW_S) -> StemLevels:
    """Per-stem mean squares, one per window, into the levels `suggest` reads.

    `power` maps a stem name to its mean square (mono, full scale 1.0)
    in each consecutive window of `window_s` seconds; stems of unequal length
    are cut to the shortest, and any stem not in `SEPARATED_STEMS` (a summed
    stem) is dropped. Pure Python: a span is a few hundred windows.
    """
    power = {s: v for s, v in power.items() if s in SEPARATED_STEMS}
    if not power:
        return StemLevels({}, {}, 0.0, 0.0)
    count = min(len(values) for values in power.values())
    level_db = {
        stem: _db(sum(values[:count]) / count) if count else _db(0.0)
        for stem, values in power.items()
    }
    melodic = [stem for stem in MELODIC_STEMS if stem in power]
    wins = dict.fromkeys(melodic, 0)
    active = 0
    if melodic and count:
        top_db = [max(_db(power[s][i]) for s in melodic) for i in range(count)]
        floor = max(_percentile(top_db, 95.0) - ACTIVE_RANGE_DB, SILENCE_DB)
        for i in range(count):
            if top_db[i] < floor:
                continue
            active += 1
            leader = max(melodic, key=lambda s: power[s][i])
            wins[leader] += 1
    lead_share = {stem: (wins[stem] / active if active else 0.0) for stem in melodic}
    return StemLevels(level_db, lead_share, active * window_s, count * window_s)


def measure(
    stem_paths: Mapping[str, str | Path],
    region: tuple[float, float | None] | None = None,
    window_s: float = WINDOW_S,
) -> StemLevels:
    """Read each stem over `region` (seconds; None is the whole file) and
    summarize it: what a caller holding a stems directory hands `suggest`.

    Pass every stem the separator wrote, the rhythm section included: the
    bass and drums are what tell a piano solo from a comp under a bass solo,
    and trio from solo piano. Summed stems are skipped unread.
    """
    separated = {s: p for s, p in stem_paths.items() if s in SEPARATED_STEMS}
    return summarize(window_power(separated, region, window_s), window_s)


def window_power(
    stem_paths: Mapping[str, str | Path],
    region: tuple[float, float | None] | None = None,
    window_s: float = WINDOW_S,
) -> dict[str, list[float]]:
    """Each stem's mono mean square per `window_s` window over `region`.

    Block by block, so a ten-minute file of six stems never sits in memory as
    float (1.3 GB). Reading wavs is all this does -- no model, no CREPE: 0.54 s
    for a 75-second span of six stems, 2.8 s for a nine-minute file (warm
    disk cache).
    """
    import numpy as np
    import soundfile

    power: dict[str, list[float]] = {}
    for stem, path in stem_paths.items():
        info = soundfile.info(str(path))
        rate = info.samplerate
        hop = max(1, int(round(window_s * rate)))
        lo = 0.0 if region is None else max(0.0, float(region[0]))
        hi_s = info.duration if region is None or region[1] is None else float(region[1])
        start = int(lo * rate)
        stop = min(int(hi_s * rate), info.frames)
        values: list[float] = []
        block = hop * 30
        for offset in range(start, stop, block):
            data, _ = soundfile.read(
                str(path),
                dtype="float32",
                always_2d=True,
                start=offset,
                stop=min(offset + block, stop),
            )
            mono = data.mean(axis=1, dtype=np.float64)
            whole = len(mono) // hop
            if whole:
                frames = mono[: whole * hop].reshape(whole, hop)
                values.extend(float(v) for v in (frames**2).mean(axis=1))
        power[stem] = values
    return power


def _ramp(value: float, edge: float, width: float) -> float:
    """0 at `edge`, 1 a `width` past it (negative width: below it), clipped."""
    return min(1.0, max(0.0, (value - edge) / width))


def _pct(share: float) -> str:
    return f"{round(100 * share)}%"


def _none(reason: str, evidence: dict[str, float]) -> Suggestion:
    return Suggestion(None, None, 0.0, reason, evidence)


def suggest(levels: StemLevels, model: str | None = None) -> Suggestion:
    """The ensemble and lead stem these levels point to, or no suggestion.

    Never a setting: the GUI shows it beside the menus with its reason, and a
    listener's own choice always wins. Nothing is suggested from a partial
    stem set, from under `MIN_ACTIVE_S` of melody, or from a separator the
    rule was not measured on (`SUGGEST_MODELS`). A piano call needs the share,
    the level and the lead tests together (module docstring), a horn call both
    of its own; anything else is unsure, and says so.
    """
    level = levels.level_db
    evidence: dict[str, float] = {"active_s": levels.active_s}

    missing = [stem for stem in SEPARATED_STEMS if stem not in level]
    if missing == ["guitar", "piano"]:
        return _none(
            "This separation has no piano stem (a four-stem model), so a piano solo "
            "cannot be told from a horn. Separate with bsroformer_sw for a suggestion.",
            evidence,
        )
    if missing:
        # A partial set -- one stem copied across from another cache is a
        # legitimate state (CLAUDE.md). Judged anyway, it is the dangerous
        # direction: with no other melodic stem the piano leads 100% of the
        # seconds by default, and with no bass the lead guard cannot see a
        # bass solo the piano is comping under.
        return _none(
            f"No suggestion: this stem set is missing {', '.join(missing)}. The piano "
            "is judged against every other stem a lead could be in, and the bass and "
            "drums tell a piano lead from a comp, so the whole set is needed.",
            evidence,
        )
    if levels.active_s < MIN_ACTIVE_S:
        return _none(
            f"Only {levels.active_s:.0f} s of the span has any melody in it; select at "
            f"least {MIN_ACTIVE_S:.0f} s of the solo for a suggestion.",
            evidence,
        )

    # Every stem is present from here on, so every number below is finite.
    share = {stem: levels.lead_share.get(stem, 0.0) for stem in MELODIC_STEMS}
    rivals = [s for s in MELODIC_STEMS if s != "piano"]
    piano_share = share["piano"]
    rival = max(rivals, key=lambda s: level[s])
    margin = level["piano"] - level[rival]
    loudest = max(level, key=level.get)
    under_loudest = level[loudest] - level["piano"]
    # The line's stem if a horn, guitar or voice leads: the non-piano stem
    # that was loudest most often (a level would favour a bleed-heavy stem).
    lead = max(rivals, key=lambda s: (share[s], level[s]))
    evidence.update(
        piano_share=piano_share,
        piano_margin_db=margin,
        piano_under_loudest_db=under_loudest,
    )
    rival_name = f"`{rival}`"

    # After the evidence, so a survey still sees what another separator's
    # stems would have said; before any call, so the listener never does.
    if model not in SUGGEST_MODELS:
        return _none(
            f"No suggestion: {model or 'this separation'} is not a separator the "
            "suggestion was measured on. On htdemucs_6s a piano solo can land in "
            "`guitar`, and a soprano saxophone read within 1 dB of a piano call, so "
            "those stems cannot say who is playing. Separate with bsroformer_sw for "
            "a suggestion.",
            evidence,
        )

    if (
        piano_share >= PIANO_SHARE_MIN
        and margin >= PIANO_MARGIN_DB
        and under_loudest <= PIANO_LEAD_DB
    ):
        confidence = 0.5 + 0.5 * min(
            _ramp(piano_share, PIANO_SHARE_MIN, 1.0 - PIANO_SHARE_MIN),
            _ramp(margin, PIANO_MARGIN_DB, PIANO_MARGIN_DB),
        )
        heard = (
            f"The piano carries this span: it is the loudest melodic stem in "
            f"{_pct(piano_share)} of its active seconds and {margin:.0f} dB above the "
            f"next ({rival_name})."
        )
        bass_under = level["piano"] - level["bass"]
        drums_under = level["piano"] - level["drums"]
        evidence.update(bass_under_piano_db=bass_under, drums_under_piano_db=drums_under)
        if bass_under >= SOLO_BASS_UNDER_DB and drums_under >= SOLO_DRUMS_UNDER_DB:
            return Suggestion(
                "solo-piano",
                "piano",
                confidence,
                heard + " No bass or drums are heard under it: solo piano, which "
                "consults the piano model.",
                evidence,
            )
        return Suggestion(
            "trio",
            "piano",
            confidence,
            heard + " A piano solo with the rhythm section: trio, which consults the piano model.",
            evidence,
        )

    if piano_share >= PIANO_SHARE_MIN and margin >= PIANO_MARGIN_DB:
        return _none(
            f"No suggestion: the piano leads {_pct(piano_share)} of the active "
            f"seconds but sits {under_loudest:.0f} dB under `{loudest}`, so it may be "
            "comping under a bass or drum solo.",
            evidence,
        )

    if piano_share <= HORN_SHARE_MAX and margin <= HORN_MARGIN_DB:
        confidence = 0.5 + 0.5 * min(
            _ramp(piano_share, HORN_SHARE_MAX, -HORN_SHARE_MAX),
            _ramp(margin, HORN_MARGIN_DB, -4 * HORN_MARGIN_DB),
        )
        relation = (
            f"level with {rival_name}"
            if abs(margin) < 1.0
            else f"{abs(margin):.0f} dB {'under' if margin < 0 else 'over'} {rival_name}"
        )
        if level["piano"] <= SILENCE_DB:
            heard = f"`{lead}` carries this span and the piano is silent"
        elif piano_share < MIXED_SHARE:
            heard = (
                f"`{lead}` carries this span (the loudest melodic stem in "
                f"{_pct(share[lead])} of its active seconds) and the piano is {relation}"
            )
        else:
            heard = (
                f"`{lead}` leads {_pct(share[lead])} of the active seconds and the piano "
                f"{_pct(piano_share)}, {relation}: a horn, guitar or voice is in this "
                "span. If part of the selection is a piano solo, select that part alone"
            )
        return Suggestion(
            "horn-led",
            lead,
            confidence,
            f"{heard}. Horn-led, which leaves the piano model out.",
            evidence,
        )

    return _none(
        f"No suggestion: the piano is the loudest melodic stem in {_pct(piano_share)} "
        f"of the active seconds at {margin:+.0f} dB against {rival_name}, so a horn may "
        "share the span. Keep horn-led unless the whole selection is a piano solo: a "
        "horn sent to the piano model loses its whole line.",
        evidence,
    )
