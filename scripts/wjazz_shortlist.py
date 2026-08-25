"""Pick a spanning shortlist of WJazzD solos to match against a CD collection.

    uv run python scripts/wjazz_shortlist.py --db path/to/wjazzd.db [-n 25]

Plan §6 layer 2 wants "~20 solos spanning eras, tempos, and instruments,
including at least 4 piano solos". Matching all 456 by hand is not a
reasonable ask, so this picks a set that covers the space: it walks
(instrument × tempo band) cells in turn, taking the most canonical unused
solo from each — canonical meaning by an artist WJazzD itself transcribed
often, which correlates well with being in any serious jazz collection.

Every matched recording is worth a lot. WJazzD gives per-note onsets and
pitches AND `solostart_sec`, so a matched track needs no manual span
selection and arrives with note-level ground truth attached — which is what
finally allows onset F1, pitch accuracy and note F1 to be scored on real
audio at scale rather than on three tunes.

The printed list is discographic metadata, but it is extracted from an ODbL
database, so keep generated lists out of the repo along with everything else
WJazzD (plan §12).
"""

import argparse
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

TEMPO_BANDS = [
    ("slow", 0, 120),
    ("medium", 120, 190),
    ("fast", 190, 260),
    ("burning", 260, 999),
]
INSTRUMENTS = ["ts", "as", "tp", "p", "g", "cl", "ss", "tb", "vib"]
# Taken FIRST and in full, before the round-robin. WJazzD is a wind database:
# 157 tenor and 102 trumpet solos against **6 piano and 6 guitar**. Plan §6
# says "WJazzD covers pianists" — it barely does, and all six piano solos are
# 262-294bpm with five of them Herbie Hancock. But polyphonic soloists are
# exactly the case our benchmark scores worst (Giant Steps) and the one M7b
# exists for, so the handful that exist are worth more than another tenor.
SCARCE = ["p", "g"]
LONG_NAME = {
    "ts": "tenor sax",
    "as": "alto sax",
    "tp": "trumpet",
    "p": "piano",
    "g": "guitar",
    "cl": "clarinet",
    "ss": "soprano sax",
    "tb": "trombone",
    "vib": "vibraphone",
    "bs": "bari sax",
    "cor": "cornet",
    "bcl": "bass clarinet",
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pick a spanning WJazzD shortlist to match against a collection."
    )
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("-n", "--count", type=int, default=25)
    args = parser.parse_args()

    db = sqlite3.connect(args.db)
    rows = list(
        db.execute(
            """select s.melid, s.performer, s.title, s.instrument, s.style,
                      s.avgtempo, s.rhythmfeel, r.recordtitle, r.label,
                      t.recordingdate, ti.solostart_sec, ti.solotime
               from solo_info s
               left join track_info t on t.trackid = s.trackid
               left join record_info r on r.recordid = s.recordid
               left join transcription_info ti on ti.melid = s.melid"""
        )
    )
    # Note count per solo decides ties: a longer solo is more evidence.
    lengths = dict(db.execute("select melid, count(*) from melody group by melid"))
    canonical = Counter(r[1] for r in rows)

    cells: dict[tuple[str, str], list] = defaultdict(list)
    for row in rows:
        melid, performer, title, inst, style, tempo, feel = row[:7]
        if not tempo or not feel or not feel.startswith("SWING"):
            continue  # a straight-eighths solo teaches the swing model nothing
        if lengths.get(melid, 0) < 150:
            continue
        band = next((n for n, lo, hi in TEMPO_BANDS if lo <= tempo < hi), None)
        if band:
            cells[(inst, band)].append(row)
    for key in cells:
        cells[key].sort(key=lambda r: (-canonical[r[1]], -lengths.get(r[0], 0)))

    # Round-robin over (instrument, band) so the shortlist spans the space
    # instead of filling up with tenor players.
    order = [(i, b) for b in [n for n, _, _ in TEMPO_BANDS] for i in INSTRUMENTS]
    picked, seen_performers = [], Counter()

    # Scarce instruments first, and without the per-performer cap: there are
    # only six piano solos in the whole database and five are by one player,
    # so capping would throw away most of the polyphonic evidence available.
    for instrument in SCARCE:
        for key in [k for k in cells if k[0] == instrument]:
            for candidate in list(cells[key]):
                picked.append(candidate)
                seen_performers[candidate[1]] += 1
                cells[key].remove(candidate)

    while len(picked) < args.count:
        progressed = False
        for key in order:
            if len(picked) >= args.count:
                break
            bucket = cells.get(key) or []
            for candidate in bucket:
                # At most two solos per performer, so one artist you happen not
                # to own cannot cost the whole shortlist.
                if seen_performers[candidate[1]] >= 2:
                    continue
                picked.append(candidate)
                seen_performers[candidate[1]] += 1
                bucket.remove(candidate)
                progressed = True
                break
        if not progressed:
            break

    picked.sort(key=lambda r: (LONG_NAME.get(r[3], r[3]), r[5]))
    print(
        f"{len(picked)} solos spanning "
        f"{len({r[3] for r in picked})} instruments and "
        f"{len({r[4] for r in picked})} styles\n"
    )
    header = f"{'#':>3s}  {'instrument':<12s} {'bpm':>5s}  {'performer':<22s} {'title':<28s} album"
    print(header)
    print("-" * len(header))
    for index, row in enumerate(picked, 1):
        melid, performer, title, inst, style, tempo, feel, album, label, date, start, _ = row
        print(
            f"{index:3d}  {LONG_NAME.get(inst, inst):<12s} {tempo:5.0f}  "
            f"{performer:<22s} {title[:28]:<28s} {(album or '?')[:44]}"
        )
    print()
    print("solo locations, for the ones you have:")
    for index, row in enumerate(picked, 1):
        start = row[10]
        # -1 is WJazzD's "not annotated" sentinel, not a timestamp.
        where = (
            f"solo starts {start:.1f}s ({int(start) // 60}:{int(start) % 60:02d})"
            if start is not None and start >= 0
            else "solo start not annotated — find it by ear"
        )
        print(f"  {index:3d}. {row[1]} - {row[2]}: {where}, {lengths.get(row[0], 0)} notes")


if __name__ == "__main__":
    main()
