"""What a SCANNED page prints that both engines miss: its tuplet numbers.

A notation-program PDF prints its noteheads and tuplet digits in a text
layer (`vector.py`); a scan has none, and on the handwritten jazz font of
the Anderson scans homr reads no tuplet number at all and Audiveris a few
triplets (Joe Henderson's Punjab: 14 of its 44 numbers, no 5 and no 13;
2026-10-07). The page still shows where every note is: homr's own
detection, before its transformer reads the music, finds the staves,
each notehead with its staff position and the bar lines. A tuplet number
is a small isolated mark a space or so tall, beside a staff, and RapidOCR
(homr's title reader) reads it. Together they are the inputs
`vector.apply_printed_tuplets` already takes from a text layer.

The font's 5 is a 3 with a flat top. A bar's arithmetic cannot tell
them apart -- five 16ths as a 5:4 save one 16th, and three of them as a
3:2 save one too -- so the digit is taken as OCR reads it, and its crop
holds only its own strokes: with a beam beside it in the crop, OCR read
Punjab's bar 8 "3" as a 5. homr, numpy, OpenCV and RapidOCR are imported
inside the functions that need them (the `omr` group); the rest is
arithmetic.
"""

from __future__ import annotations

import json
from pathlib import Path

from pdf2musicxml import vector

# Bump to re-read the pages cached beside their images (pNNN_scan.json):
# SEGMENT_VERSION for homr's staves, heads and bar lines (seconds a page),
# DIGITS_VERSION for the numbers only.
SEGMENT_VERSION = 3
DIGITS_VERSION = 5
STEPS = "CDEFGAB"
# homr's staff position: the bottom line of a treble staff (E4) is 1.
E4_DIATONIC = 4 * 7 + STEPS.index("E")
# The counts a scanned number may be. Chord symbols print 7, 9 and 11
# constantly, and a lone 7 was a chord's every time it was checked (25 on
# Lullaby in Rhythm, "Cm7" with the m too wide to count as its letter);
# a 13 beside its letter is read as "A13" and fails.
TUPLET_COUNTS = {3, 5, 6, 13}

_ocr = None


def _reader():
    global _ocr  # noqa: PLW0603
    if _ocr is None:
        from rapidocr import RapidOCR

        _ocr = RapidOCR()
    return _ocr


def read_page(png: Path) -> dict:
    """homr's staves, noteheads and bar lines on one page image, and the digits beside each staff.

    Coordinates are homr's (its page is resized to 1,920 px wide, y down).
    """
    out = _segment(png)
    _add_digits(out, page_gray(png))
    return out


def page_gray(png: Path):
    """The page as homr's segmentation sees it: cropped, resized, contrast-adjusted, grey."""
    import cv2
    from homr.autocrop import autocrop
    from homr.color_adjust import apply_clahe
    from homr.resize import resize_image

    image = apply_clahe(resize_image(autocrop(cv2.imread(str(png)))))
    return image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def _add_digits(page: dict, gray) -> None:
    for staff in page["staffs"]:
        staff["digits"] = []
    if gray.shape[0] != page["height"]:
        return  # not the image the staves were found on
    for index, digit in _digits(gray, page["staffs"]):
        page["staffs"][index]["digits"].append(digit)
    page["digits_version"] = DIGITS_VERSION


def _segment(png: Path) -> dict:
    """homr's staves, noteheads (x, y, staff position) and bar lines, digits left empty."""
    import numpy as np
    from homr.bar_line_detection import detect_bar_lines
    from homr.main import load_and_preprocess_predictions, predict_symbols
    from homr.note_detection import add_notes_to_staffs, combine_noteheads_with_stems
    from homr.staff_detection import break_wide_fragments, detect_staff

    predictions, debug = load_and_preprocess_predictions(str(png), False, False, False)
    symbols = predict_symbols(debug, predictions)
    symbols.staff_fragments = break_wide_fragments(symbols.staff_fragments)
    heads = combine_noteheads_with_stems(symbols.noteheads, symbols.stems_rest)
    if not heads:
        return {"version": SEGMENT_VERSION, "height": 0, "staffs": []}
    head_height = float(np.median([h.notehead.size[1] for h in heads]))
    noteheads = [h.notehead for h in heads]
    stems = [h.stem for h in heads if h.stem is not None]
    candidates = [
        line
        for line in symbols.bar_lines
        if not line.is_overlapping_with_any(noteheads) and not line.is_overlapping_with_any(stems)
    ]
    bar_boxes = detect_bar_lines(candidates, head_height)
    staffs = detect_staff(
        debug, predictions.staff, symbols.staff_fragments, symbols.clefs_keys, bar_boxes
    )
    add_notes_to_staffs(staffs, heads, predictions.symbols, predictions.notehead)
    staffs = sorted(staffs, key=lambda s: s.min_y)
    image = predictions.preprocessed
    out = {
        "version": SEGMENT_VERSION,
        "height": int(image.shape[0]),
        "staffs": [
            {
                "min_x": float(s.min_x),
                "max_x": float(s.max_x),
                "min_y": float(s.min_y),
                "max_y": float(s.max_y),
                "unit": float(s.average_unit_size),
                "notes": sorted(
                    [float(n.center[0]), float(n.center[1]), int(n.position)] for n in s.get_notes()
                ),
                "bars": [],
                "digits": [],
            }
            for s in staffs
        ],
    }
    for box in bar_boxes:
        x, y = box.center
        for staff in out["staffs"]:
            if staff["min_y"] - staff["unit"] <= y <= staff["max_y"] + staff["unit"]:
                staff["bars"].append(float(x))
                break
    for staff in out["staffs"]:
        staff["bars"].sort()
    return out


def _nearest_staff(staffs: list[dict], y: float) -> tuple[int, float]:
    """The staff whose band is nearest y, and the distance to it (0 inside)."""
    best = (0, float("inf"))
    for index, staff in enumerate(staffs):
        distance = max(staff["min_y"] - y, y - staff["max_y"], 0.0)
        if distance < best[1]:
            best = (index, distance)
    return best


def _digits(gray, staffs: list[dict]) -> list[tuple[int, list]]:
    """[(staff index, [x, y, text, score])]: lone small marks beside a staff, read by OCR.

    A mark is a connected component a staff space tall or so, half a
    space to eight spaces off its nearest staff, past the clef and bar
    number at the line's start and before its first note; marks side by
    side on one line are one
    number (a 13). A number stands ALONE: a letter-sized mark on its line
    beside it makes it a chord symbol's (Benny Goodman's Indiana prints
    "G 7" with a gap, and 14 of its 7s were read as septuplets). Brackets,
    beams and stems are wider or taller than a letter and do not count.
    Whatever OCR makes of a lone mark is kept; `printed_pages` keeps the
    numbers.
    """
    import cv2
    import numpy as np

    _, ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    count, labels, stats, centroids = cv2.connectedComponentsWithStats(ink, connectivity=8)
    marks: dict[int, list[list]] = {}
    for i in range(1, count):
        x, y, w, h, _area = (int(v) for v in stats[i])
        cx, cy = (float(v) for v in centroids[i])
        index, distance = _nearest_staff(staffs, cy)
        staff = staffs[index]
        unit = staff["unit"]
        if not (0.6 * unit <= h <= 1.6 * unit and 0.15 * unit <= w <= 1.3 * unit):
            continue
        if not 0.5 * unit <= distance <= 8 * unit:
            continue
        if cx < staff["min_x"] + 4 * unit or cx > staff["max_x"]:
            continue
        # A bar number sits before the line's first note; a tuplet number
        # never does. homr finds "notes" in the clef too (Cherokee).
        first = next((n[0] for n in staff["notes"] if n[0] > staff["min_x"] + 4 * unit), None)
        if first is not None and cx < first - 0.5 * unit:
            continue
        marks.setdefault(index, []).append([x, y, x + w, y + h, [i]])
    out = []
    for index, boxes in marks.items():
        unit = staffs[index]["unit"]
        boxes.sort()
        groups: list[list] = []
        for box in boxes:
            last = groups[-1] if groups else None
            if (
                last is not None
                and box[0] - last[2] < 1.0 * unit
                and abs((box[1] + box[3]) / 2 - (last[1] + last[3]) / 2) < 0.5 * unit
            ):
                last[0], last[1] = min(last[0], box[0]), min(last[1], box[1])
                last[2], last[3] = max(last[2], box[2]), max(last[3], box[3])
                last[4] = last[4] + box[4]
            else:
                groups.append(list(box))
        for left, top, right, bottom, members in groups:
            if _beside(stats, members, (left, top, right, bottom), unit):
                continue
            # Only the mark's own strokes, on white: a beam or stem beside
            # it in the crop reads as a 5's flat top (Punjab bar 8's "3").
            pad = int(unit)
            y0, x0 = max(0, int(top) - pad), max(0, int(left) - pad)
            window = labels[y0 : int(bottom) + pad, x0 : int(right) + pad]
            own = cv2.dilate(np.isin(window, members).astype(np.uint8), np.ones((3, 3), np.uint8))
            shade = gray[y0 : int(bottom) + pad, x0 : int(right) + pad]
            crop = np.where(own > 0, shade, 255).astype(np.uint8)
            crop = cv2.resize(crop, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
            crop = cv2.copyMakeBorder(crop, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
            result = _reader()(crop, use_det=False, use_cls=False, use_rec=True)
            text = result.txts[0] if result is not None and result.txts else ""
            score = float(result.scores[0]) if result is not None and result.scores else 0.0
            out.append((index, [(left + right) / 2, (top + bottom) / 2, text, score]))
    return out


def _beside(stats, members: list[int], box: tuple, unit: float) -> bool:
    """Whether a letter-sized mark sits on the box's line within a space of it.

    A letter is up to three spaces tall, no more than twice as wide as
    tall, and fills a sixth or more of its box (Indiana's chord "C" is
    2.4 spaces tall and fills 0.18); half a tuplet bracket, a flat line
    with a hook, is not. "On its line" reaches half a space
    above and below (a chord's 6 is raised: "Gm6" on Hipsippy Blues) and
    a space and a half to each side (Indiana's "C 6").
    """
    left, top, right, bottom = box
    for i in range(1, len(stats)):
        if i in members:
            continue
        x, y, w, h, area = (int(v) for v in stats[i])
        if not (0.4 * unit <= h <= 3 * unit and w <= 2.5 * unit and w <= 2 * h):
            continue
        if area < 0.15 * w * h:
            continue
        if x > right + 1.5 * unit or x + w < left - 1.5 * unit:
            continue
        if y < bottom + 0.5 * unit and y + h > top - 0.5 * unit:
            return True
    return False


def cached_page(png: Path, force: bool = False) -> dict:
    """`read_page`, kept beside the image as pNNN_scan.json; its parts re-read by version."""
    cache = png.with_name(f"{png.stem}_scan.json")
    data = None
    if not force and cache.is_file() and cache.stat().st_mtime >= png.stat().st_mtime:
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
    if data is None or data.get("version") != SEGMENT_VERSION:
        data = read_page(png)
    elif data.get("digits_version") != DIGITS_VERSION:
        _add_digits(data, page_gray(png))
    else:
        return data
    cache.write_text(json.dumps(data), encoding="utf-8")
    return data


def printed_pages(pages: list[dict]) -> vector.PrintedPages:
    """The scanned pages as `vector.PrintedPages`: noteheads, bar lines, tuplet numbers.

    y is turned upward, as the text layer's is. A head's letter and octave
    come from homr's staff position on a treble staff; a bass-clef page
    simply fails to align, and nothing is changed. A digit that is a
    tuplet count becomes a mark.
    """
    heads: list[vector.Printed] = []
    marks: list[vector.TupletMark] = []
    barlines: dict[tuple[int, int], list[float]] = {}
    for page_index, page in enumerate(pages):
        height = page.get("height", 0)
        for staff_index, staff in enumerate(page.get("staffs", [])):
            barlines[(page_index, staff_index)] = list(staff["bars"])
            for x, y, position in staff["notes"]:
                diatonic = E4_DIATONIC + position - 1
                heads.append(
                    vector.Printed(
                        x=x,
                        y=height - y,
                        staff=staff_index,
                        step=position - 1,
                        kind="head",
                        grace=False,
                        letter=STEPS[diatonic % 7],
                        octave=diatonic // 7,
                        page=page_index,
                    )
                )
            for x, y, text, _score in staff["digits"]:
                text = text.strip()
                if not text.isdigit() or int(text) not in TUPLET_COUNTS:
                    continue
                count = int(text)
                marks.append(
                    vector.TupletMark(
                        x=x,
                        y=height - y,
                        staff=staff_index,
                        count=count,
                        spacing=staff["unit"],
                        page=page_index,
                    )
                )
    heads.sort(key=lambda h: (h.page, h.staff, h.x))
    marks.sort(key=lambda m: (m.page, m.staff, m.x))
    return vector.PrintedPages(heads, marks, barlines, None, None)
