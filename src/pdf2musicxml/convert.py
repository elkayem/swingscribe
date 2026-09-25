"""One PDF in, one MusicXML per transcription out.

The steps, per PDF:

1. Every page is rendered once (`work/pages/`) and read for staves, the
   first staff's position and its text layer (`layout.PageInfo`).
2. The pages are grouped into transcriptions -- by the manifest beside the
   output if one names them, by `--split`, else by `layout.group_pages`.
3. Each transcription's pages go to the primary engine (homr reads page
   images; Audiveris reads a PDF of them written by `pdfpages.write_gray_pdf`),
   the readings are joined, mended and named (`musicxml`), and written.
4. With `check` on, the other engine reads the same pages and the two
   readings are compared bar by bar; the bars they disagree on are the
   proofreader's list. The second reading is kept beside the first.
5. A manifest (`<pdf>.pdf2musicxml.json`) records the grouping, titles and
   instruments, so a wrong guess can be corrected by hand and re-run.

Outputs go to `<pdf folder>/musicxml/` unless told otherwise; engine
output, page images, logs and the cross-check reading stay under
`<out>/.work/<pdf stem>/`.
"""

from __future__ import annotations

import datetime as dt
import fnmatch
import json
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from pdf2musicxml import __version__, layout, musicxml, pdfpages, vector
from pdf2musicxml.engines import EngineError, audiveris, homr
from pdf2musicxml.instruments import Instrument, find_instrument, parse_instrument

Log = Callable[[str], None]

JAZZ_FONT_MARKERS = ("inkpen", "reprise", "jazz", "petaluma", "broadway", "swing")


@dataclass
class Options:
    engine: str = "homr"
    check: bool = True
    font: str = "auto"  # Audiveris music family: auto | standard | jazz
    concert: bool = False
    force: bool = False
    long_side: int = 3300
    out_dir: Path | None = None
    split: str | None = None
    single: bool = False
    instrument: str | None = None
    time_signature: str | None = None
    title: str | None = None
    redetect: bool = False
    printed_pitch: bool = True  # correct pitches to the text layer's noteheads


@dataclass
class Result:
    pdf: str
    pages: list[int]  # 1-based, as a reader counts them
    title: str
    instrument: str | None
    output: str
    engine: str
    measures: int
    notes: int
    ties: int
    tuplets: int
    harmonies: int
    time_signature: str | None
    time_note: str
    off_bars: list[str]
    ties_from_slurs: int
    dropped_parts: list[str]
    chords_read: int = 0
    check_engine: str | None = None
    check_output: str | None = None
    check_agreement: float | None = None
    check_disagreeing: list[int] = field(default_factory=list)
    engine_warnings: int = 0
    printed_noteheads: int = 0  # from the text layer; 0 for a scan
    pitch_corrections: int = 0  # pitches set to the printed ones (vector.py)
    unread_printed: int = 0  # printed heads no read note aligned with
    unprinted_read: int = 0  # read notes no printed head aligned with
    tuplets_printed: int = 0  # tuplet numbers on the page
    tuplets_from_page: int = 0  # groups the reading had plain, made tuplets from the page
    tuplets_unapplied: int = 0  # printed numbers the reading's notes could not take
    tuplets_unprinted: int = 0  # the reading's tuplet groups under no printed number
    tuplets_revalued: int = 0  # groups whose one read value the bar's length moved a level
    bars_merged: int = 0  # read measures joined because the page has one bar there
    bars_split: int = 0  # read measures divided because the page has two bars there
    bar_notes: list[str] = field(default_factory=list)  # which bars, from the page's bar lines
    printed_time: str | None = None  # the page's time signature
    tempo: str | None = None  # the page's metronome mark, e.g. "Fast Swing half = 128"
    tuplet_notes: list[str] = field(default_factory=list)  # per printed number: done or why not
    barlines_printed: int = 0  # bar lines the page's paths gave; about one per bar when read right
    alters_from_engine_bars: int = 0  # sounding alters decided by the reading's bar ends
    bars_from_check: int = 0  # bars taken from the other engine's reading, bar for bar
    bars_from_check_list: list[str] = field(default_factory=list)
    time_changes: int = 0  # changes of signature carried from the page
    time_notes: list[str] = field(default_factory=list)
    rest_bars_from_page: int = 0  # bars of multi-bar rest the page prints, given their bars
    rest_notes: list[str] = field(default_factory=list)
    rest_bars_filled: int = 0  # empty or whole-rest bars written as whole-measure rests
    repeats_dropped: int = 0  # the engine's repeat marks the cross-check did not read
    seconds: float = 0.0
    error: str | None = None

    @property
    def coverage(self) -> float | None:
        """Notes read per notehead printed, when the PDF says how many it printed."""
        if not self.printed_noteheads:
            return None
        return (self.notes + self.chords_read) / self.printed_noteheads

    @property
    def summary(self) -> str:
        if self.error:
            return f"FAILED: {self.error}"
        parts = [
            f"{self.measures} bars",
            f"{self.notes} notes",
            f"{self.ties} ties",
            f"{self.tuplets} tuplets",
        ]
        if self.harmonies:
            parts.append(f"{self.harmonies} chords")
        parts.append(f"time {self.time_signature or '?'}")
        parts.append(f"{len(self.off_bars)} bars off")
        if self.coverage is not None:
            parts.append(f"{self.printed_noteheads} noteheads printed, {self.coverage:.0%} read")
        if self.pitch_corrections or self.unread_printed or self.unprinted_read:
            parts.append(
                f"{self.pitch_corrections} pitches set from the page, "
                f"{self.unread_printed} printed notes unread, "
                f"{self.unprinted_read} read notes unprinted"
            )
        if self.tuplets_printed:
            parts.append(
                f"{self.tuplets_printed} tuplet numbers printed, "
                f"{self.tuplets_from_page} groups made tuplets from the page, "
                f"{self.tuplets_unapplied} numbers unapplied, "
                f"{self.tuplets_unprinted} read tuplets unprinted"
            )
        if self.bars_merged or self.bars_split:
            parts.append(
                f"{self.bars_merged} read bars joined and {self.bars_split} divided "
                "by the page's bar lines"
            )
        if self.bars_from_check:
            parts.append(f"{self.bars_from_check} bars taken from the {self.check_engine} reading")
        if self.time_changes:
            parts.append(f"{self.time_changes} time changes from the page")
        if self.rest_bars_from_page:
            parts.append(f"{self.rest_bars_from_page} bars of multi-bar rest from the page")
        if self.repeats_dropped:
            parts.append(f"{self.repeats_dropped} repeat marks dropped")
        if self.tempo:
            parts.append(f"tempo {self.tempo}")
        if self.check_agreement is not None:
            parts.append(f"{self.check_engine} agrees on {self.check_agreement:.0%}")
        return ", ".join(parts)


def safe_name(text: str, limit: int = 80) -> str:
    cleaned = re.sub(r"[^\w\s\-'&(),.!]", " ", text, flags=re.UNICODE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned[:limit].rstrip(" .") or "untitled"


def output_dir_for(pdf: Path, options: Options) -> Path:
    return Path(options.out_dir) if options.out_dir else pdf.parent / "musicxml"


def work_dir_for(pdf: Path, out_dir: Path) -> Path:
    return out_dir / ".work" / safe_name(pdf.stem)


def manifest_path(pdf: Path, out_dir: Path) -> Path:
    return out_dir / f"{pdf.stem}.pdf2musicxml.json"


# ---------------------------------------------------------------- pages


def analyze_pages(
    pdf: Path, work: Path, long_side: int, force: bool, log: Log
) -> list[layout.PageInfo]:
    """Render every page once and read it for staves and text."""
    from PIL import Image

    pages_dir = work / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    count = pdfpages.page_count(pdf)
    infos = []
    for index in range(count):
        image_path = pages_dir / f"p{index + 1:03d}.png"
        if force or not image_path.is_file():
            image = pdfpages.render_page(pdf, index, long_side)
            image.save(image_path)
        else:
            image = Image.open(image_path).convert("L")
        top = layout.staff_top(image)
        lines = pdfpages.page_text(pdf, index)
        printed = vector.printed_noteheads(pdf, index) if lines else 0
        infos.append(layout.PageInfo(index, top is not None, top, lines, printed))
    staffed = sum(1 for p in infos if p.has_staves)
    log(
        f"  {count} pages, {staffed} with staves, "
        f"text layer: {'yes' if any(p.text_lines for p in infos) else 'no'}"
    )
    return infos


def page_image(work: Path, index: int) -> Path:
    return work / "pages" / f"p{index + 1:03d}.png"


def jazz_fonts(pages: list[layout.PageInfo]) -> bool:
    fonts = {line.font.lower() for page in pages for line in page.lines}
    return any(marker in font for font in fonts for marker in JAZZ_FONT_MARKERS)


# ---------------------------------------------------------------- grouping


def load_manifest(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def plan_groups(
    pdf: Path, pages: list[layout.PageInfo], options: Options, manifest: dict | None, log: Log
) -> list[dict]:
    """[{pages: [0-based], title, instrument}] from the manifest, --split, or the layout guess."""
    count = len(pages)
    entries = (manifest or {}).get("transcriptions") or []
    # A manifest's groups are a human's correction only when they differ
    # from what the tool itself detected and recorded beside them; the
    # tool's own earlier guess never outranks its current one.
    edited = manifest_edited(manifest)
    if manifest and not options.redetect and edited:
        groups = []
        for entry in entries:
            indices = [int(p) - 1 for p in entry.get("pages", [])]
            if indices:
                groups.append(
                    {
                        "pages": indices,
                        "title": entry.get("title"),
                        "instrument": entry.get("instrument"),
                    }
                )
        if groups:
            log(f"  page groups from {manifest_path(pdf, output_dir_for(pdf, options)).name}")
            return groups
    if options.split:
        return [
            {"pages": g, "title": None, "instrument": None}
            for g in layout.parse_split(options.split, count)
        ]
    groups = layout.group_pages(pages, single=options.single)
    return [{"pages": g, "title": None, "instrument": None} for g in groups]


def plausible_title(text: str) -> bool:
    """Readable words, not what a decorative title font OCRs into ("lllll ll. um - Ill!")."""
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 3 or len(text) < 4:
        return False
    if sum(c.isalnum() or c == " " for c in text) / len(text) < 0.7:
        return False
    strokes = sum(1 for c in letters if c in "lI|")
    return strokes / len(letters) <= 0.4


def manifest_edited(manifest: dict | None) -> bool:
    """True when the groups, titles or instruments differ from what was detected."""
    if not manifest:
        return False
    entries = manifest.get("transcriptions") or []
    detected = manifest.get("detected")
    if not entries or detected is None:
        return False
    current = [
        {"pages": e.get("pages"), "title": e.get("title"), "instrument": e.get("instrument")}
        for e in entries
    ]
    return current != detected


def guess_title(
    pages: list[layout.PageInfo], group: list[int], credits: list[tuple[int, float, str]], tree
) -> str | None:
    first = pages[group[0]]
    if first.title:
        return first.title
    # OCR'd credits: the largest plausible line on the first page of the group.
    for page, _size, text in credits:
        if page == 1 and plausible_title(text):
            return text
    title = tree.getroot().findtext("work/work-title") if tree is not None else None
    if title and len(title) >= 4 and not re.search(r"\d", title):
        return title
    return None


INSTRUMENT_MAP = "pdf2musicxml.instruments.json"


def folder_instrument(pdf: Path) -> Instrument | None:
    """The instrument a `pdf2musicxml.instruments.json` beside the PDF names for it.

    {"instruments": {"Charlie-Parker-*.pdf": "Alto Saxophone", ...}} --
    for a site that files its transcriptions by instrument and prints
    none on the page. Patterns are fnmatch; the first match wins.
    """
    path = pdf.parent / INSTRUMENT_MAP
    if not path.is_file():
        return None
    try:
        mapping = json.loads(path.read_text(encoding="utf-8")).get("instruments") or {}
    except (OSError, ValueError):
        return None
    for pattern, name in mapping.items():
        if fnmatch.fnmatch(pdf.name, pattern) or pdf.name == pattern:
            return parse_instrument(name)
    return None


def guess_instrument(
    pages: list[layout.PageInfo],
    group: list[int],
    credits: list[tuple[int, float, str]],
    pdf: Path | None = None,
) -> Instrument | None:
    """The page's own text first, then OCR'd credits, then the file name, then the folder map."""
    lines = [line.text for index in group for line in pages[index].text_lines]
    lines += [text for _page, _size, text in credits]
    found = find_instrument(lines)
    if found is None and pdf is not None:
        # "Whisper-Not-Art-Farmers-Trumpet-Solo.pdf" names its instrument;
        # "A Night in Tunisia - Jackie McLean Solo.pdf" does not.
        found = find_instrument([pdf.stem.replace("-", " ").replace("_", " ")])
    if found is None and pdf is not None:
        found = folder_instrument(pdf)
    return found


# ---------------------------------------------------------------- one transcription


def _read_with(engine: str, images: list[Path], tdir: Path, font: str, force: bool = False):
    """The engine's readings of these page images, joined into one tree, plus its warnings.

    Readings already on disk are reused unless `force`: re-running after a
    manifest edit or a post-processing change costs seconds, not minutes.
    """
    if engine == "homr":
        files = homr.run(images, tdir / "homr", reuse=not force)
        warnings = 0
    else:
        from PIL import Image

        book = tdir / "audiveris" / "input.pdf"
        book.parent.mkdir(parents=True, exist_ok=True)
        # The book is the transcription's pages; a regrouping changes them,
        # and a reading of other pages must not be served in its place.
        stamp = book.with_suffix(".pages.json")
        wanted = json.dumps([p.name for p in images])
        if book.is_file() and not stamp.is_file() and pdfpages.page_count(book) == len(images):
            stamp.write_text(wanted)  # a book from before the stamps, with the same page count
        fresh = force or not book.is_file() or not stamp.is_file() or stamp.read_text() != wanted
        if fresh:
            pdfpages.write_gray_pdf([Image.open(p) for p in images], book)
            stamp.write_text(wanted)
        files = audiveris.run(book, tdir / "audiveris", font=font, reuse=not fresh)
        warnings = len(audiveris.warnings(tdir / "audiveris" / "audiveris.log"))
    return musicxml.concat([musicxml.read(f) for f in files]), warnings


def _mend(
    tree,
    options: Options,
    instrument: Instrument | None,
    title: str | None,
    printed: vector.PrintedPages | None = None,
):
    root = tree.getroot()
    dropped = musicxml.keep_main_part(root)
    part = musicxml.first_part(root)
    ties = musicxml.slurs_to_ties(part)
    musicxml.repair_chords(part)
    musicxml.repair_tuplets(part)
    musicxml.strip_spanning_tremolos(part)
    # The page's own time signature outranks what the bars fill (2/2 and
    # 4/4 fill the same bars); the listener's --time outranks both.
    printed_time = printed.time.text if printed is not None and printed.time else None
    time_fix = musicxml.fix_time_signature(part, options.time_signature or printed_time)
    if printed_time and not options.time_signature:
        time_fix.note = f"printed {printed_time}"
    if printed is not None and printed.tempo is not None:
        tempo = printed.tempo
        musicxml.set_tempo(root, tempo.unit, tempo.per_minute, dots=tempo.dots, words=tempo.words)
    if instrument is not None:
        musicxml.apply_instrument(root, instrument, concert=options.concert)
    if title:
        musicxml.set_title(root, title)
    return part, dropped, ties, time_fix


def _printed(
    pdf: Path,
    pages: list[layout.PageInfo],
    indices: list[int],
    options: Options,
    dropped: list[str],
) -> vector.PrintedPages | None:
    """What the pages print -- pitches, tuplet numbers, time signature, tempo --
    when every page prints its noteheads and the reading is one line.

    Skipped for a scan (no text layer), for a page whose staves the reader
    cannot find, and for a reading that had extra parts dropped (a score
    with several staves per system interleaves its lines).
    """
    if not options.printed_pitch or dropped:
        return None
    if any(pages[i].printed_noteheads == 0 for i in indices):
        return None
    prints = []
    for index in indices:
        page = vector.read_page(pdf, index)
        if page is None or not page.notes:
            return None
        if len(set(page.clefs)) > 1:
            return None  # treble and bass on one page: a piano score, not a line
        prints.append(page)
    return vector.collect(prints)


def convert_group(
    pdf: Path,
    pages: list[layout.PageInfo],
    group: dict,
    number: int,
    total: int,
    options: Options,
    out_dir: Path,
    work: Path,
    log: Log,
) -> Result:
    started = time.time()
    indices: list[int] = group["pages"]
    readable = [i + 1 for i in indices]
    tdir = work / f"t{number:02d}"
    tdir.mkdir(parents=True, exist_ok=True)
    images = [page_image(work, i) for i in indices]
    font = options.font
    if font == "auto":
        font = "jazz" if jazz_fonts([pages[i] for i in indices]) else "standard"
    primary = options.engine
    secondary = "audiveris" if primary == "homr" else "homr"
    base = Result(
        pdf=str(pdf),
        pages=readable,
        title="",
        instrument=None,
        output="",
        engine=primary,
        measures=0,
        notes=0,
        ties=0,
        tuplets=0,
        harmonies=0,
        time_signature=None,
        time_note="",
        off_bars=[],
        ties_from_slurs=0,
        dropped_parts=[],
    )
    log(f"  [{number}/{total}] pages {readable[0]}-{readable[-1]}: reading with {primary}...")
    try:
        tree, warnings = _read_with(primary, images, tdir, font, options.force)
    except EngineError as error:
        base.error = str(error)
        base.seconds = time.time() - started
        log(f"    {base.error}")
        return base
    # The second reading comes BEFORE naming: on a scan the only text is
    # what Audiveris OCR'd into its credits, whichever engine it is here.
    other = None
    if options.check:
        try:
            log(f"    cross-checking with {secondary}...")
            other, _ = _read_with(secondary, images, tdir, font, options.force)
        except EngineError as error:
            log(f"    cross-check skipped: {error}")
    credits = musicxml.credit_lines(tree.getroot())
    if other is not None:
        credits += musicxml.credit_lines(other.getroot())

    title = options.title or group.get("title") or guess_title(pages, indices, credits, tree)
    if group.get("instrument"):
        instrument = parse_instrument(group["instrument"])
    elif options.instrument:
        instrument = parse_instrument(options.instrument)
    else:
        instrument = guess_instrument(pages, indices, credits, pdf)
    if title is None:
        title = pdf.stem if total == 1 else f"{pdf.stem} - part {number}"

    try:
        # The page is read before the mend so its time signature and tempo
        # reach the mend; a reading with extra parts gets no page reading.
        dropped = musicxml.keep_main_part(tree.getroot())
        printed = _printed(pdf, pages, indices, options, dropped)
        part, _, ties, time_fix = _mend(tree, options, instrument, title, printed)
        correction = vector.correct_pitches(part, printed.heads) if printed else None
        time_change = vector.apply_printed_times(part, printed) if printed else None
        bar_fix = vector.align_bars(part, printed) if printed else None
        rest_fix = vector.expand_multirests(part, printed) if printed else None
        tuplet_fix = vector.apply_printed_tuplets(part, printed) if printed else None
        filled = musicxml.fill_rest_bars(part)
        musicxml.drop_redundant_times(part)
        if time_change is not None:
            # Named by the final bar numbers, after any bars the rests added.
            time_change.changes = [
                c for c in time_change.changes if not c.startswith("bar ")
            ] + musicxml.time_changes(part)
        other_part = agreement = merge = None
        repeats_dropped = 0
        if other is not None:
            other_part, _, _, _ = _mend(other, options, instrument, title, printed)
            if printed:
                vector.correct_pitches(other_part, printed.heads)
                vector.apply_printed_times(other_part, printed)
                vector.align_bars(other_part, printed)
                vector.expand_multirests(other_part, printed)
                vector.apply_printed_tuplets(other_part, printed)
            musicxml.fill_rest_bars(other_part)
            musicxml.drop_redundant_times(other_part)
            repeats_dropped = musicxml.strip_repeats(part, musicxml.repeat_directions(other_part))
            # Agreement is measured before the merge, or it would measure the merge.
            agreement = musicxml.agreement(
                musicxml.bar_signatures(part), musicxml.bar_signatures(other_part)
            )
            merge = musicxml.merge_readings(
                part,
                other_part,
                vector.printed_count_per_measure(part, printed) if printed else None,
            )
            filled += musicxml.fill_rest_bars(part)
        else:
            repeats_dropped = musicxml.strip_repeats(part)
        validation = musicxml.validate(part)
    except Exception as error:  # one bad reading must not end the batch
        base.error = f"{type(error).__name__}: {error}"
        base.title = title
        base.seconds = time.time() - started
        log(f"    {base.error}")
        return base
    if total == 1:
        name = safe_name(pdf.stem)
    else:
        name = f"{safe_name(pdf.stem)} - {number:02d} {safe_name(title)}"
    output = out_dir / f"{name}.musicxml"
    musicxml.write(tree, output)

    result = Result(
        pdf=str(pdf),
        pages=readable,
        title=title,
        instrument=instrument.name if instrument else None,
        output=str(output),
        engine=primary,
        measures=validation.measures,
        notes=validation.notes,
        ties=validation.ties,
        tuplets=validation.tuplets,
        harmonies=validation.harmonies,
        time_signature=validation.time_signature,
        time_note=time_fix.note,
        off_bars=validation.off_bars,
        ties_from_slurs=ties,
        dropped_parts=dropped,
        chords_read=validation.chords,
        engine_warnings=warnings,
        printed_noteheads=sum(pages[i].printed_noteheads for i in indices),
        pitch_corrections=correction.changed if correction else 0,
        unread_printed=correction.unread if correction else 0,
        unprinted_read=correction.unprinted if correction else 0,
        tuplets_printed=tuplet_fix.marks if tuplet_fix else 0,
        tuplets_from_page=tuplet_fix.applied if tuplet_fix else 0,
        tuplets_unapplied=(
            tuplet_fix.unplaced + tuplet_fix.unaligned + tuplet_fix.uneven if tuplet_fix else 0
        ),
        tuplets_unprinted=tuplet_fix.unprinted if tuplet_fix else 0,
        tuplets_revalued=tuplet_fix.revalued if tuplet_fix else 0,
        bars_merged=bar_fix.merged if bar_fix else 0,
        bars_split=bar_fix.split if bar_fix else 0,
        bar_notes=bar_fix.changes if bar_fix else [],
        printed_time=printed.time.text if printed and printed.time else None,
        tempo=printed.tempo.text if printed and printed.tempo else None,
        tuplet_notes=tuplet_fix.changes if tuplet_fix else [],
        barlines_printed=printed.barline_count if printed else 0,
        alters_from_engine_bars=correction.alters_from_engine_bars if correction else 0,
        bars_from_check=merge.taken if merge else 0,
        bars_from_check_list=merge.bars if merge else [],
        time_changes=time_change.placed if time_change else 0,
        time_notes=time_change.changes if time_change else [],
        rest_bars_from_page=rest_fix.bars if rest_fix else 0,
        rest_notes=rest_fix.changes if rest_fix else [],
        rest_bars_filled=filled,
        repeats_dropped=repeats_dropped,
    )
    if other is not None and agreement is not None:
        # The cross-check lives under .work, not beside the primary: the
        # listener uses the folder elsewhere and two readings of one solo
        # side by side were a confusion (2026-09-24).
        check_output = tdir / f"{name}.{secondary}.musicxml"
        musicxml.write(other, check_output)
        result.check_engine = secondary
        result.check_output = str(check_output)
        result.check_agreement = agreement.share
        result.check_disagreeing = agreement.disagreeing
    result.seconds = time.time() - started
    log(f"    -> {output.name}: {result.summary} ({result.seconds:.0f} s)")
    return result


# ---------------------------------------------------------------- one pdf


def convert_pdf(pdf: Path, options: Options, log: Log = print) -> list[Result]:
    # Absolute from here on: the engines run in their own working directories.
    pdf = Path(pdf).resolve()
    out_dir = output_dir_for(pdf, options).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    work = work_dir_for(pdf, out_dir)
    log(f"{pdf.name}")
    manifest = load_manifest(manifest_path(pdf, out_dir))
    if manifest and not options.force and manifest.get("transcriptions"):
        outputs = [Path(t["output"]) for t in manifest["transcriptions"] if t.get("output")]
        if (
            outputs
            and all(o.is_file() and o.stat().st_mtime >= pdf.stat().st_mtime for o in outputs)
            and not options.redetect
            and manifest.get("engine") == options.engine
            and manifest.get("tool") == __version__
        ):
            log(f"  up to date ({len(outputs)} files in {out_dir}); use --force to redo")
            return []
    pages = analyze_pages(pdf, work, options.long_side, options.force, log)
    groups = plan_groups(pdf, pages, options, manifest, log)
    if not groups:
        log("  no pages with staves; nothing to transcribe")
        return []
    log(
        f"  {len(groups)} transcription(s): "
        + ", ".join(
            f"p{g['pages'][0] + 1}" + (f"-{g['pages'][-1] + 1}" if len(g["pages"]) > 1 else "")
            for g in groups
        )
    )
    if options.check and not (audiveris.is_installed() and homr.is_installed()):
        missing = (
            "Audiveris (run `pdf2musicxml setup`)"
            if not audiveris.is_installed()
            else "homr (uv sync --group omr)"
        )
        log(f"  cross-check off: {missing} is not installed")
        options = Options(**{**asdict(options), "check": False})
    results = []
    for number, group in enumerate(groups, start=1):
        results.append(
            convert_group(pdf, pages, group, number, len(groups), options, out_dir, work, log)
        )
    remove_stale_outputs(manifest, results, log)
    write_manifest(pdf, out_dir, pages, options, results)
    return results


def remove_stale_outputs(manifest: dict | None, results: list[Result], log: Log) -> None:
    """Delete the files an earlier run wrote for this PDF that this run did not rewrite.

    A better title or a new page grouping renames a transcription's files;
    only files the previous manifest itself recorded are touched.
    """
    if not manifest:
        return
    current = set()
    for result in results:
        current.update(p for p in (result.output, result.check_output) if p)
    for entry in manifest.get("transcriptions", []):
        for key in ("output", "check_output"):
            old = entry.get(key)
            if old and old not in current and Path(old).is_file():
                Path(old).unlink()
                log(f"  removed {Path(old).name} (superseded)")


def write_manifest(
    pdf: Path, out_dir: Path, pages: list[layout.PageInfo], options: Options, results: list[Result]
) -> None:
    data = {
        "pdf": str(pdf),
        "generated": dt.datetime.now().isoformat(timespec="seconds"),
        "tool": __version__,
        "engine": options.engine,
        "check": options.check,
        "concert": options.concert,
        "pages": len(pages),
        "staff_pages": [p.index + 1 for p in pages if p.has_staves],
        "first_staff_top": {
            p.index + 1: round(p.first_staff_top, 3) for p in pages if p.first_staff_top is not None
        },
        "note": "Edit 'pages', 'title' or 'instrument' below and re-run to correct a wrong "
        "split; the edit counts only where it differs from 'detected'.",
        "detected": [
            {"pages": r.pages, "title": r.title, "instrument": r.instrument} for r in results
        ],
        "transcriptions": [asdict(r) for r in results],
    }
    manifest_path(pdf, out_dir).write_text(json.dumps(data, indent=2), encoding="utf-8")


def unique_pdfs(folder: Path) -> tuple[list[Path], list[tuple[Path, Path]]]:
    """The folder's PDFs in name order, each byte-identical copy dropped in favour of the first."""
    import hashlib

    seen: dict[str, Path] = {}
    unique: list[Path] = []
    duplicates: list[tuple[Path, Path]] = []
    for pdf in sorted(p for p in folder.iterdir() if p.suffix.lower() == ".pdf"):
        digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
        if digest in seen:
            duplicates.append((pdf, seen[digest]))
        else:
            seen[digest] = pdf
            unique.append(pdf)
    return unique, duplicates


def convert_path(target: Path, options: Options, log: Log = print) -> list[Result]:
    target = Path(target)
    if target.is_dir():
        pdfs, duplicates = unique_pdfs(target)
        for copy_of, original in duplicates:
            log(f"{copy_of.name}: byte-identical to {original.name}, skipped")
        if not pdfs:
            log(f"no PDFs in {target}")
        results = []
        for pdf in pdfs:
            results.extend(convert_pdf(pdf, options, log))
        return results
    return convert_pdf(target, options, log)


def summary_rows(out_dir: Path) -> list[dict]:
    """One row per transcription from every manifest in `out_dir`, worst first.

    Worst is lowest coverage (notes read per notehead printed), then lowest
    agreement between the two engines, then most bars off -- the order a
    proofreader should take them in.
    """
    rows = []
    for manifest in sorted(Path(out_dir).glob("*.pdf2musicxml.json")):
        data = load_manifest(manifest) or {}
        for entry in data.get("transcriptions", []):
            printed = entry.get("printed_noteheads") or 0
            read = (entry.get("notes") or 0) + (entry.get("chords_read") or 0)
            rows.append(
                {
                    "file": Path(entry.get("output") or "").name
                    or Path(entry.get("pdf", "?")).name,
                    "pages": f"{entry['pages'][0]}-{entry['pages'][-1]}"
                    if entry.get("pages")
                    else "",
                    "bars": entry.get("measures") or 0,
                    "notes": entry.get("notes") or 0,
                    "coverage": (read / printed) if printed else None,
                    "agreement": entry.get("check_agreement"),
                    "off": len(entry.get("off_bars") or []),
                    "time": entry.get("time_signature") or "?",
                    "instrument": entry.get("instrument") or "?",
                    "title": entry.get("title") or "",
                    "error": entry.get("error"),
                }
            )
    rows.sort(
        key=lambda r: (
            r["error"] is None,
            r["coverage"] if r["coverage"] is not None else 2.0,
            r["agreement"] if r["agreement"] is not None else 2.0,
            -r["off"],
        )
    )
    return rows


def summary_table(rows: list[dict]) -> str:
    """The rows as a Markdown table, plus totals."""
    lines = [
        "| file | pages | bars | notes | read/printed | agree | bars off | time | instrument |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        if r["error"]:
            lines.append(f"| {r['file']} | {r['pages']} | FAILED: {r['error'][:60]} | | | | | | |")
            continue
        coverage = f"{r['coverage']:.0%}" if r["coverage"] is not None else "-"
        agreement = f"{r['agreement']:.0%}" if r["agreement"] is not None else "-"
        lines.append(
            f"| {r['file']} | {r['pages']} | {r['bars']} | {r['notes']} | {coverage} | {agreement} "
            f"| {r['off']} | {r['time']} | {r['instrument']} |"
        )
    done = [r for r in rows if not r["error"]]
    with_coverage = [r["coverage"] for r in done if r["coverage"] is not None]
    with_agreement = [r["agreement"] for r in done if r["agreement"] is not None]
    lines.append("")
    lines.append(
        f"{len(done)} transcriptions, {sum(r['bars'] for r in done)} bars, "
        f"{sum(r['notes'] for r in done)} notes; "
        f"{len([r for r in rows if r['error']])} failed."
    )
    if with_coverage:
        lines.append(
            f"Coverage (notes read per notehead printed) over {len(with_coverage)} with a text "
            f"layer: median {sorted(with_coverage)[len(with_coverage) // 2]:.1%}, "
            f"min {min(with_coverage):.1%}, max {max(with_coverage):.1%}."
        )
    if with_agreement:
        lines.append(
            f"Engine agreement over {len(with_agreement)}: median "
            f"{sorted(with_agreement)[len(with_agreement) // 2]:.0%}."
        )
    return "\n".join(lines)


def report(results: list[Result]) -> str:
    """A proofreader's summary: one line per transcription, then the bars to look at."""
    lines = []
    for result in results:
        lines.append(f"{Path(result.output).name if result.output else result.pdf}")
        lines.append(
            f"  pages {result.pages[0]}-{result.pages[-1]}, {result.title!r}, "
            f"instrument {result.instrument or 'unknown'}"
        )
        lines.append(f"  {result.summary}")
        if result.time_note:
            lines.append(f"  time signature: {result.time_note}")
        if result.off_bars:
            shown = ", ".join(result.off_bars[:20]) + (" ..." if len(result.off_bars) > 20 else "")
            lines.append(f"  bars whose notes do not fill the bar: {shown}")
        if result.check_disagreeing:
            shown = ", ".join(str(b) for b in result.check_disagreeing[:30])
            shown += " ..." if len(result.check_disagreeing) > 30 else ""
            lines.append(f"  bars {result.check_engine} reads differently: {shown}")
        if result.dropped_parts:
            lines.append(f"  extra parts dropped: {', '.join(result.dropped_parts)}")
    return "\n".join(lines)
