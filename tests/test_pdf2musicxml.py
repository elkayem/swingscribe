"""pdf2musicxml: the arithmetic around the OMR engines, held by synthetic MusicXML.

No engine runs here (Audiveris is a Java download, homr a 200 MB group);
what is tested is everything the tool does to an engine's output and to a
PDF's pages before and after: joining pages, mending ties and time
signatures, naming the instrument, validating bars, comparing two readings,
grouping pages into transcriptions, and the command lines it builds.
"""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from pdf2musicxml import convert, layout, musicxml, pdfpages, scanpage, vector
from pdf2musicxml.instruments import Instrument, find_instrument, parse_instrument
from pdf2musicxml.pdfpages import TextLine, is_music_font

# ---------------------------------------------------------------- helpers


def note(step: str, octave: int, duration: int, alter: int = 0, **extra: str) -> str:
    alter_xml = f"<alter>{alter}</alter>" if alter else ""
    notations = extra.get("notations", "")
    tie = extra.get("tie", "")
    return (
        f"<note><pitch><step>{step}</step>{alter_xml}<octave>{octave}</octave></pitch>"
        f"<duration>{duration}</duration>{tie}<voice>1</voice><type>quarter</type>"
        f"{('<notations>' + notations + '</notations>') if notations else ''}</note>"
    )


def rest(duration: int) -> str:
    return (
        f"<note><rest/><duration>{duration}</duration><voice>1</voice><type>quarter</type></note>"
    )


def score(
    measures: list[str], divisions: int = 4, time: str | None = "4/4", parts_extra: str = ""
) -> ET.ElementTree:
    attributes = f"<divisions>{divisions}</divisions><key><fifths>0</fifths></key>"
    if time:
        beats, beat_type = time.split("/")
        attributes += f"<time><beats>{beats}</beats><beat-type>{beat_type}</beat-type></time>"
    attributes += "<clef><sign>G</sign><line>2</line></clef>"
    body = ""
    for number, content in enumerate(measures, start=1):
        head = f"<attributes>{attributes}</attributes>" if number == 1 else ""
        body += f'<measure number="{number}">{head}{content}</measure>'
    xml = (
        '<score-partwise version="4.0"><part-list><score-part id="P1"><part-name>Voice</part-name>'
        f'</score-part>{parts_extra}</part-list><part id="P1">{body}</part></score-partwise>'
    )
    return ET.ElementTree(ET.fromstring(xml))


def quarters(measures: int, divisions: int = 4) -> list[str]:
    return [note("C", 4, divisions) * 4 for _ in range(measures)]


# ---------------------------------------------------------------- ties


def test_slur_between_equal_adjacent_pitches_becomes_a_tie():
    tree = score(
        [
            note("C", 4, 4) * 3 + note("D", 4, 4, notations='<slur type="start" number="1"/>'),
            note("D", 4, 4, notations='<slur type="stop" number="1"/>') + note("E", 4, 4) * 3,
        ]
    )
    part = musicxml.first_part(tree.getroot())
    assert musicxml.slurs_to_ties(part) == 1
    notes = part.findall("measure/note")
    assert notes[3].find('tie[@type="start"]') is not None
    assert notes[3].find('notations/tied[@type="start"]') is not None
    assert notes[4].find('tie[@type="stop"]') is not None
    assert notes[3].find("notations/slur") is None
    # <tie> sits after <duration>, where the schema puts it
    tags = [child.tag for child in notes[3]]
    assert tags.index("tie") == tags.index("duration") + 1


def test_slur_across_a_change_of_pitch_or_a_rest_stays_a_slur():
    tree = score(
        [
            note("C", 4, 4, notations='<slur type="start" number="1"/>')
            + note("D", 4, 4, notations='<slur type="stop" number="1"/>')
            + note("E", 4, 4, notations='<slur type="start" number="1"/>')
            + rest(4),
            note("E", 4, 4, notations='<slur type="stop" number="1"/>') + note("F", 4, 4) * 3,
        ]
    )
    part = musicxml.first_part(tree.getroot())
    assert musicxml.slurs_to_ties(part) == 0
    assert len(part.findall("measure/note/notations/slur")) == 4


# ---------------------------------------------------------------- time signatures


def test_misread_time_signature_is_replaced_by_what_the_bars_fill():
    tree = score(quarters(8), time="6/8")
    part = musicxml.first_part(tree.getroot())
    fix = musicxml.fix_time_signature(part)
    assert (fix.declared, fix.used, fix.changed) == ("6/8", "4/4", True)
    assert musicxml.validate(part).time_signature == "4/4"


def test_missing_time_signature_is_inferred_from_the_bars():
    tree = score([note("C", 4, 4) * 3 for _ in range(6)], time=None)
    part = musicxml.first_part(tree.getroot())
    fix = musicxml.fix_time_signature(part)
    assert fix.used == "3/4" and fix.declared is None
    assert part.find("measure/attributes/time/beats").text == "3"


def test_time_signature_the_bars_agree_with_is_left_alone():
    tree = score(quarters(5))
    part = musicxml.first_part(tree.getroot())
    fix = musicxml.fix_time_signature(part)
    assert not fix.changed and fix.used == "4/4"


def test_mid_piece_change_the_bars_do_not_fill_is_dropped():
    measures = quarters(8)
    measures[4] = (
        "<attributes><time><beats>3</beats><beat-type>4</beat-type></time></attributes>"
        + measures[4]
    )
    tree = score(measures)
    part = musicxml.first_part(tree.getroot())
    fix = musicxml.fix_time_signature(part)
    assert fix.dropped_changes == 1
    assert part.findall("measure")[4].find("attributes") is None
    assert musicxml.validate(part).off_bars == []


def test_eighth_note_signature_that_fills_the_bar_is_written_in_quarters():
    tree = score(quarters(6), time="8/8")
    part = musicxml.first_part(tree.getroot())
    fix = musicxml.fix_time_signature(part)
    assert (fix.declared, fix.used, fix.changed) == ("8/8", "4/4", True)
    compound = score([note("C", 4, 2) * 6 for _ in range(6)], divisions=4, time="6/8")
    part = musicxml.first_part(compound.getroot())
    assert musicxml.fix_time_signature(part).used == "6/8"


def test_implausible_signature_yields_to_the_commonest_bar_even_when_irregular():
    measures = [
        note("C", 4, 4) * 4,
        note("C", 4, 4) * 3,
        note("C", 4, 4) * 4,
        note("C", 4, 4) * 5,
        note("C", 4, 4) * 4,
        note("C", 4, 4) * 2,
        note("C", 4, 4) * 3,
    ]
    part = musicxml.first_part(score(measures, time="1/2").getroot())
    fix = musicxml.fix_time_signature(part)
    assert fix.used == "4/4" and fix.changed
    part = musicxml.first_part(score(measures, time="3/4").getroot())
    assert musicxml.fix_time_signature(part).used == "3/4"  # plausible: left to the reader


def test_forced_time_signature_wins():
    tree = score(quarters(4), time="6/8")
    part = musicxml.first_part(tree.getroot())
    fix = musicxml.fix_time_signature(part, force="4/4")
    assert fix.used == "4/4" and fix.changed


# ---------------------------------------------------------------- joining pages


def test_concat_rescales_divisions_and_renumbers():
    first = score([note("C", 4, 2) * 4], divisions=2)
    second = score([note("D", 4, 3) * 4, note("E", 4, 3) * 4], divisions=3)
    joined = musicxml.concat([first, second])
    part = musicxml.first_part(joined.getroot())
    measures = part.findall("measure")
    assert [m.get("number") for m in measures] == ["1", "2", "3"]
    assert part.find("measure/attributes/divisions").text == "6"
    durations = [n.findtext("duration") for n in part.iter("note")]
    assert durations == ["6"] * 12
    # the second page's repeated clef/key/time are dropped, so no courtesy signatures
    assert measures[1].find("attributes") is None
    assert len(musicxml.bars(part)) == 3 and all(b.length == 4 for b in musicxml.bars(part))


def test_concat_keeps_a_real_key_change_at_a_page_turn():
    first = score([note("C", 4, 4) * 4])
    second = score([note("C", 4, 4) * 4])
    second.getroot().find("part/measure/attributes/key/fifths").text = "2"
    joined = musicxml.concat([first, second])
    measures = musicxml.first_part(joined.getroot()).findall("measure")
    assert measures[1].find("attributes/key/fifths").text == "2"
    assert measures[1].find("attributes/time") is None


# ---------------------------------------------------------------- instrument


@pytest.mark.parametrize(
    "text, name",
    [
        ("Alto Saxophone (Eb)", "Alto Saxophone"),
        ("Aho Saxophone(Eb)", "Alto Saxophone"),  # OCR'd
        ("Clarinet in Bb", "Bb Clarinet"),
        ("TRUMPET", "Bb Trumpet"),
        ("Trumpet in C", "Trumpet in C"),
        ("Tenor Sax", "Tenor Saxophone"),
        ("Bass Clarinet", "Bass Clarinet"),
        ("Cannonball Adderley - Alto Sax", "Alto Saxophone"),
        ("Bill Evans - Piano", "Piano"),
        ("Composed by Gigi Gryce", None),
        ("CLFFORD BROWN TRUVPET SOLO", "Bb Trumpet"),  # OCR'd
        ("Cannonbal Adderley - Alto Saxophome", "Alto Saxophone"),
        ("This also has no instrument", None),  # "also" must not become "alto"
        ("LEE MORGAN - TERRIBLE T", None),  # not an organ
    ],
)
def test_instrument_names_are_read_off_the_page(text, name):
    found = parse_instrument(text)
    assert (found.name if found else None) == name


def test_part_label_beats_the_soloist_credit():
    lines = ["Minority (Take 3)", "Alto Saxophone (Eb)", "Bill Evans - Piano", "Sam Jones - Bass"]
    assert find_instrument(lines).name == "Alto Saxophone"
    # a book written for trumpet, whatever the soloist played
    lines = ["FRIED BANANAS", "DEXTER GORDON TENOR SOLO", "TRUMPET", "Transcribed by Bob Aron"]
    assert find_instrument(lines).name == "Bb Trumpet"
    assert find_instrument(["As you will notice, the solos"]) is None


def test_fifths_shift_follows_the_interval():
    assert Instrument("Bb Trumpet", -2, -1).fifths_shift == -2
    assert Instrument("Alto Saxophone", -9, -5).fifths_shift == -3
    assert Instrument("Tenor Saxophone", -14, -8).fifths_shift == -2
    assert Instrument("Piano", 0, 0).fifths_shift == 0


def test_apply_instrument_writes_transpose_and_names_the_part():
    tree = score(quarters(2))
    musicxml.apply_instrument(tree.getroot(), Instrument("Bb Trumpet", -2, -1))
    root = tree.getroot()
    assert root.findtext("part-list/score-part/part-name") == "Bb Trumpet"
    transpose = root.find("part/measure/attributes/transpose")
    assert transpose.findtext("diatonic") == "-1" and transpose.findtext("chromatic") == "-2"
    assert root.find("part/measure/pitch") is None  # pitches untouched


def test_concert_pitch_shifts_notes_chords_and_key_with_spelling():
    # Written D major for alto (2 sharps) sounds F major (1 flat); written F#4 sounds A3.
    measures = [
        "<harmony><root><root-step>D</root-step></root></harmony>"
        + note("F", 4, 4, alter=1)
        + note("C", 5, 4) * 3
    ]
    tree = score(measures)
    tree.getroot().find("part/measure/attributes/key/fifths").text = "2"
    musicxml.apply_instrument(tree.getroot(), Instrument("Alto Saxophone", -9, -5), concert=True)
    root = tree.getroot()
    assert root.find("part/measure/attributes/transpose") is None
    assert root.findtext("part/measure/attributes/key/fifths") == "-1"
    first = root.find("part/measure/note/pitch")
    assert (first.findtext("step"), first.findtext("alter"), first.findtext("octave")) == (
        "A",
        None,
        "3",
    )
    chord_root = root.find("part/measure/harmony/root")
    assert chord_root.findtext("root-step") == "F" and chord_root.find("root-alter") is None
    # written C5 sounds Eb4
    second = root.findall("part/measure/note/pitch")[1]
    assert (second.findtext("step"), second.findtext("alter"), second.findtext("octave")) == (
        "E",
        "-1",
        "4",
    )


def test_guitar_octave_change_reaches_the_pitch_in_concert():
    tree = score([note("E", 4, 4) * 4])
    musicxml.apply_instrument(
        tree.getroot(), Instrument("Guitar", 0, 0, octave_change=-1), concert=True
    )
    assert tree.getroot().findtext("part/measure/note/pitch/octave") == "3"


# ---------------------------------------------------------------- validation and agreement


def test_validate_lists_over_and_under_full_bars_but_allows_pickup_and_last():
    measures = [
        note("C", 4, 4),
        note("C", 4, 4) * 4,
        note("C", 4, 4) * 5,
        note("C", 4, 4) * 3,
        note("C", 4, 4) * 2,
    ]
    part = musicxml.first_part(score(measures).getroot())
    validation = musicxml.validate(part)
    assert validation.off_bars == ["3", "4"]
    assert validation.measures == 5 and validation.notes == 15


def test_agreement_aligns_by_content_across_a_dropped_bar():
    a = [(("C", 1),), (("D", 1),), (("E", 1),), (("F", 1),)]
    b = [(("C", 1),), (("E", 1),), (("F", 1),)]
    result = musicxml.agreement(a, b)
    assert result.matched == 3 and result.disagreeing == [2]
    assert result.share == 0.75


def test_bar_signatures_take_voice_one_without_chords_or_grace_notes():
    measure = (
        note("C", 4, 4) + "<note><chord/><pitch><step>E</step><octave>4</octave></pitch>"
        "<duration>4</duration><voice>1</voice></note>"
        + "<note><grace/><pitch><step>G</step><octave>4</octave></pitch><voice>1</voice></note>"
        + rest(4)
    )
    part = musicxml.first_part(score([measure]).getroot())
    assert musicxml.bar_signatures(part) == [((60, Fraction(1)), (0, Fraction(1)))]


def test_keep_main_part_keeps_the_part_with_the_notes_first():
    tree = score(
        quarters(2), parts_extra='<score-part id="P2"><part-name>Ghost</part-name></score-part>'
    )
    root = tree.getroot()
    ghost = ET.SubElement(root, "part", {"id": "P2"})
    ET.SubElement(ghost, "measure", {"number": "1"})
    assert musicxml.keep_main_part(root) == ["Ghost"]
    assert [p.get("id") for p in root.findall("part")] == ["P1"]
    assert root.find("part-list/score-part[@id='P2']") is None


# ---------------------------------------------------------------- pages and grouping


def line(text: str, size: float, top: float, font: str = "Futura") -> TextLine:
    return TextLine(text, size, font, top, 0.1)


def test_music_fonts_are_not_titles_but_text_and_script_faces_are():
    assert is_music_font("SWRSLA+Maestro") and is_music_font("OpusStd")
    assert is_music_font("Inkpen2ChordsStd") and is_music_font("Inkpen2Std")
    assert not is_music_font("Inkpen2ScriptStd") and not is_music_font("ReprisetextStd")
    assert not is_music_font("MuseJazzText") and not is_music_font("FuturaLT-Bold")
    assert not is_music_font("OpusTextStd")  # tuplet digits: never wordy anyway


def test_noteheads_are_told_by_shape_not_code():
    spacing = 5.0
    assert vector.is_notehead_box(6.85, 5.25, spacing) == "head"  # Opus black head
    assert vector.is_notehead_box(7.05, 5.45, spacing) == "head"  # half head (U+02D9)
    assert vector.is_notehead_box(8.0, 6.8, spacing) == "head"  # cross head
    assert vector.is_notehead_box(4.2, 3.2, spacing) == "grace"  # a grace head
    assert vector.is_notehead_box(5.25, 15.6, spacing) is None  # quarter rest (U+0152)
    assert vector.is_notehead_box(4.6, 12.2, spacing) is None  # flat
    assert vector.is_notehead_box(5.6, 2.4, spacing) is None  # half rest
    assert vector.is_notehead_box(1.6, 1.5, spacing) is None  # a dot
    assert vector.is_notehead_box(7.9, 9.5, spacing) is None  # a time-signature digit


def test_title_is_the_largest_wordy_line_near_the_top():
    lines = [
        line("Minority (Take 3)", 24, 0.08),
        line("Alto Saxophone (Eb)", 12, 0.10),
        line("Transcribed by Wesley Chin", 10, 0.95),
        line("&b.&b&b.&b..", 128, 0.19, font="OpusStd"),
        line("3333333", 65, 0.22, font="OpusTextStd"),
    ]
    assert layout.pick_title(lines) == "Minority (Take 3)"


def test_title_is_measured_against_words_not_tuplet_digits():
    lines = [line("Friend Like Me", 25.9, 0.04, font="Inkpen2ScriptStd")]
    lines += [line("3 3 3", 20.6, 0.1 + i * 0.05, font="Inkpen2TextStd") for i in range(12)]
    lines += [line("Transcribed by Maksym Grynchuk", 13, 0.09, font="Inkpen2ScriptStd")]
    lines += [line("Wayne Bergeron's Trumpet Solo", 16, 0.07, font="Inkpen2ScriptStd")]
    assert layout.pick_title(lines) == "Friend Like Me"


def test_no_title_when_nothing_stands_out():
    lines = [line("Dm7 G7 C", 10, 0.1), line("bar 23", 10, 0.2), line("bar 27", 10, 0.3)]
    assert layout.pick_title(lines) is None


def page(index: int, top: float | None, lines: list[TextLine] | None = None) -> layout.PageInfo:
    return layout.PageInfo(index, top is not None, top, lines or [])


def test_text_layer_titles_group_pages():
    pages = [
        page(
            0, 0.15, [line("Minority", 24, 0.08), line("Alto Sax", 10, 0.1), line("notes", 10, 0.5)]
        ),
        page(1, 0.08, [line("2 Minority", 8, 0.02), line("notes", 10, 0.5), line("x", 10, 0.6)]),
        page(2, 0.08, [line("3", 8, 0.02), line("notes", 10, 0.5), line("x", 10, 0.6)]),
    ]
    assert layout.group_pages(pages) == [[0, 1, 2]]


def test_continuation_header_beats_a_large_line():
    pages = [
        page(
            0,
            0.15,
            [line("FRIED BANANAS", 30, 0.05), line("Trumpet", 10, 0.1), line("notes", 10, 0.5)],
        ),
        page(
            1,
            0.08,
            [line("DEXTER GORDON - PG. 2", 30, 0.03), line("notes", 10, 0.5), line("x", 10, 0.6)],
        ),
    ]
    assert layout.group_pages(pages) == [[0, 1]]


def test_scanned_book_splits_where_the_first_staff_drops():
    pages = [
        page(0, None),
        page(1, None),
        page(2, 0.145),
        page(3, 0.14),
        page(4, 0.15),
        page(5, 0.085),
        page(6, 0.15),
    ]
    assert layout.group_pages(pages) == [[2], [3], [4, 5], [6]]


def test_scanned_single_transcription_with_equal_margins_is_one():
    pages = [page(0, 0.09), page(1, 0.085)]
    assert layout.group_pages(pages) == [[0, 1]]


def test_scanned_book_of_titled_single_pages_is_one_each():
    pages = [page(0, 0.15), page(1, 0.14), page(2, 0.15)]
    assert layout.group_pages(pages) == [[0], [1], [2]]


def test_single_flag_and_explicit_split():
    pages = [page(0, 0.15), page(1, 0.14)]
    assert layout.group_pages(pages, single=True) == [[0, 1]]
    assert layout.parse_split("4-5,6-8,9", 21) == [[3, 4], [5, 6, 7], [8]]
    with pytest.raises(ValueError):
        layout.parse_split("0-3", 21)


def test_staff_top_finds_five_lines_and_ignores_a_heavy_title():
    np = pytest.importorskip("numpy")
    from PIL import Image

    pixels = np.full((1000, 800), 255, dtype=np.uint8)
    pixels[100:130, 200:600] = 0  # a heavy title: one run, 50% of the width
    for k in range(5):  # a staff at 40% of the page
        pixels[400 + 12 * k : 402 + 12 * k, 40:760] = 0
    top = layout.staff_top(Image.fromarray(pixels))
    assert top == pytest.approx(0.4, abs=0.002)
    assert layout.staff_top(Image.fromarray(np.full((100, 100), 255, dtype=np.uint8))) is None
    # five thick, evenly spaced rows of body text are not a staff
    text = np.full((1000, 800), 255, dtype=np.uint8)
    for k in range(6):
        text[200 + 40 * k : 220 + 40 * k, 60:740] = 0
    assert layout.staff_top(Image.fromarray(text)) is None


def test_mixed_book_decides_page_by_page():
    # text front matter without staves, then scanned solos: titled pages sit lower
    pages = [
        page(0, None, [line("How To Use This Book", 40, 0.05), line("As you will", 12, 0.3)]),
        page(1, 0.18),
        page(2, 0.18),
        page(3, 0.093),
        page(4, 0.18),
    ]
    assert layout.group_pages(pages) == [[1], [2, 3], [4]]
    # a titled text page followed by textless continuation pages at an ordinary margin
    pages = [
        page(
            0, 0.2, [line("Minority", 24, 0.06), line("Alto Sax", 10, 0.1), line("notes", 10, 0.5)]
        ),
        page(1, 0.09),
        page(2, 0.09),
    ]
    assert layout.group_pages(pages) == [[0, 1, 2]]


# ---------------------------------------------------------------- engines and pdf


def test_audiveris_command_puts_the_jar_first_and_selects_the_jazz_family(tmp_path, monkeypatch):
    monkeypatch.setenv("PDF2MUSICXML_HOME", str(tmp_path))
    from pdf2musicxml import paths
    from pdf2musicxml.engines import audiveris

    cmd = audiveris.command(Path("book.pdf"), tmp_path / "out", font="jazz")
    classpath = cmd[cmd.index("-cp") + 1]
    assert classpath.startswith(str(paths.audiveris_dir() / "app" / "audiveris.jar"))
    assert "-batch" in cmd and "-export" in cmd
    assert "org.audiveris.omr.ui.symbol.MusicFont.defaultMusicFamily=FinaleJazz" in cmd
    assert "org.audiveris.omr.sheet.BookManager.useCompression=false" in cmd
    assert cmd[-2:] == ["--", "book.pdf"]
    assert "defaultMusicFamily" not in " ".join(audiveris.command(Path("b.pdf"), tmp_path))


def test_audiveris_exported_files_come_in_movement_order(tmp_path):
    from pdf2musicxml.engines import audiveris

    for name in ("book.mvt2.xml", "book.mvt10.xml", "book.mvt1.xml", "other.xml", "book.omr"):
        (tmp_path / name).write_text("<x/>")
    assert [p.name for p in audiveris.exported(tmp_path, "book")] == [
        "book.mvt1.xml",
        "book.mvt2.xml",
        "book.mvt10.xml",
    ]


def test_gray_pdf_round_trips_through_pypdfium2(tmp_path):
    pytest.importorskip("pypdfium2")
    from PIL import Image

    from pdf2musicxml import pdfpages

    image = Image.new("L", (300, 400), 255)
    image.paste(0, (0, 100, 300, 104))
    target = tmp_path / "pages.pdf"
    pdfpages.write_gray_pdf([image, image], target, dpi=300)
    assert pdfpages.page_count(target) == 2
    back = pdfpages.render_page(target, 0, long_side=400)
    assert back.size == (300, 400)
    assert back.getpixel((150, 102)) < 50 and back.getpixel((150, 300)) > 200


def test_read_accepts_compressed_mxl(tmp_path):
    import zipfile

    tree = score(quarters(1))
    xml = ET.tostring(tree.getroot(), encoding="unicode")
    target = tmp_path / "score.mxl"
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr(
            "META-INF/container.xml",
            '<container><rootfiles><rootfile full-path="score.xml"/></rootfiles></container>',
        )
        archive.writestr("score.xml", xml)
    assert len(musicxml.first_part(musicxml.read(target).getroot()).findall("measure")) == 1


def test_summary_orders_worst_first_and_totals(tmp_path):
    import json

    from pdf2musicxml.convert import summary_rows, summary_table

    def entry(output, notes, printed, agreement, off, error=None):
        return {
            "output": str(tmp_path / output),
            "pages": [1, 2],
            "measures": 10,
            "notes": notes,
            "chords_read": 0,
            "printed_noteheads": printed,
            "check_agreement": agreement,
            "off_bars": ["3"] * off,
            "time_signature": "4/4",
            "instrument": "Bb Trumpet",
            "title": output,
            "error": error,
            "pdf": "x.pdf",
        }

    (tmp_path / "a.pdf2musicxml.json").write_text(
        json.dumps(
            {
                "transcriptions": [
                    entry("good.musicxml", 99, 100, 0.7, 1),
                    entry("bad.musicxml", 60, 100, 0.2, 5),
                ]
            }
        )
    )
    (tmp_path / "b.pdf2musicxml.json").write_text(
        json.dumps(
            {
                "transcriptions": [
                    entry("scan.musicxml", 80, 0, 0.3, 2),
                    entry("broken.musicxml", 0, 0, None, 0, "engine died"),
                ]
            }
        )
    )
    rows = summary_rows(tmp_path)
    assert [r["file"] for r in rows] == [
        "broken.musicxml",
        "bad.musicxml",
        "good.musicxml",
        "scan.musicxml",
    ]
    table = summary_table(rows)
    assert "| bad.musicxml | 1-2 | 10 | 60 | 60% | 20% | 5 | 4/4 | Bb Trumpet |" in table
    assert "3 transcriptions, 30 bars, 239 notes; 1 failed." in table
    assert "FAILED: engine died" in table


def test_instrument_falls_back_to_the_file_name_then_the_folder_map(tmp_path):
    import json

    from pdf2musicxml.convert import INSTRUMENT_MAP, guess_instrument

    pages = [page(0, 0.15, [line("Cherokee", 24, 0.05), line("notes", 10, 0.5)])]
    named = tmp_path / "Whisper-Not-Art-Farmers-Trumpet-Solo.pdf"
    assert guess_instrument(pages, [0], [], named).name == "Bb Trumpet"
    unnamed = tmp_path / "Charlie-Parker-Ballade.pdf"
    assert guess_instrument(pages, [0], [], unnamed) is None
    (tmp_path / INSTRUMENT_MAP).write_text(
        json.dumps({"instruments": {"Charlie-Parker-*.pdf": "Alto Saxophone"}})
    )
    assert guess_instrument(pages, [0], [], unnamed).name == "Alto Saxophone"
    # the page's own text still wins over the map
    labelled = [page(0, 0.15, [line("Tenor Sax", 10, 0.1), line("notes", 10, 0.5)])]
    assert guess_instrument(labelled, [0], [], unnamed).name == "Tenor Saxophone"


def test_junk_ocr_titles_are_rejected():
    from pdf2musicxml.convert import plausible_title

    assert plausible_title("FRIED BANANAS") and plausible_title("TOTEM POI-E")
    assert plausible_title("BLUEBERRY [Ill].")
    assert not plausible_title("lllll ll. um - Ill! 111mm")
    assert not plausible_title("III'I'I OI TIE OI. mm - Hill ll !")
    assert not plausible_title("7") and not plausible_title("&b.&b&b")


def test_homr_child_environment_makes_a_relative_pythonpath_absolute(monkeypatch, tmp_path):
    import os

    from pdf2musicxml.engines import homr

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join([".venv/Lib/site-packages", "src"]))
    env = homr.environment()
    entries = env["PYTHONPATH"].split(os.pathsep)
    assert all(os.path.isabs(entry) for entry in entries)
    assert entries[1] == str(tmp_path / "src")
    assert homr.command(Path("p001.png"))[-1] == "p001.png"


def text_pdf(path: Path, lines: list[tuple[str, float, float]]) -> None:
    """A one-page PDF with Helvetica text: (text, size, y from the bottom in points)."""
    content = "\n".join(f"BT /F1 {size} Tf 72 {y} Td ({text}) Tj ET" for text, size, y in lines)
    body = content.encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]"
        b" /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d >>\nstream\n" % len(body) + body + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    path.write_bytes(bytes(out))


def test_page_text_keeps_a_small_caps_title_on_one_line(tmp_path):
    pytest.importorskip("pypdfium2")
    from pdf2musicxml import pdfpages

    pdf = tmp_path / "caps.pdf"
    # one line whose capitals are set larger than its lower case, as a
    # script face does: "A" at 20 pt, "night" at 15 pt, on one baseline
    content = "BT /F1 20 Tf 72 700 Td (A) Tj /F1 15 Tf ( NIGHT IN TUNISIA) Tj ET"
    text_pdf(pdf, [])
    data = pdf.read_bytes().replace(
        b"stream\n\nendstream", b"stream\n" + content.encode() + b"\nendstream"
    )
    pdf.write_bytes(data)
    lines = pdfpages.page_text(pdf, 0)
    assert [line.text for line in lines] == ["A NIGHT IN TUNISIA"]
    assert lines[0].size == pytest.approx(20, abs=3)


def test_page_text_groups_words_into_lines_with_sizes_in_points(tmp_path):
    pytest.importorskip("pypdfium2")
    from pdf2musicxml import pdfpages
    from pdf2musicxml.instruments import find_instrument

    pdf = tmp_path / "text.pdf"
    text_pdf(
        pdf,
        [("Minority (Take 3)", 24, 730), ("Alto Saxophone (Eb)", 10, 700), ("Fast Swing", 10, 685)],
    )
    lines = pdfpages.page_text(pdf, 0)
    texts = [line.text for line in lines]
    assert texts == ["Minority (Take 3)", "Alto Saxophone (Eb)", "Fast Swing"]
    assert lines[0].size == pytest.approx(24, abs=3) and lines[1].size == pytest.approx(10, abs=2)
    assert lines[0].top < lines[1].top < lines[2].top < 0.2
    assert layout.pick_title(lines) == "Minority (Take 3)"
    assert find_instrument([line.text for line in lines]).name == "Alto Saxophone"


# ---------------------------------------------------------------- printed pitches


def test_staff_steps_and_clefs():
    staff = vector.Staff(bottom=100.0, spacing=5.0, left=50.0, right=550.0)
    assert staff.top == 120.0
    assert staff.step_of(100.0) == 0 and staff.step_of(102.5) == 1 and staff.step_of(120.0) == 8
    assert staff.step_of(95.0) == -2 and staff.holds(85.0) and not staff.holds(60.0)


def test_key_signature_is_a_circle_of_fifths_prefix():
    marks = [(60.0, "B", -1), (66.0, "E", -1), (72.0, "G", -1)]
    key, leftover = vector.key_signature(marks)
    assert key == {"B": -1, "E": -1} and [m[1] for m in leftover] == ["G"]
    assert vector.key_signature([(60.0, "F", 1), (66.0, "C", 1)])[0] == {"F": 1, "C": 1}
    assert vector.key_signature([(60.0, "G", 1)]) == ({}, [(60.0, "G", 1)])
    assert vector.key_signature([]) == ({}, [])


def printed(x, step, alter=None, staff=0, grace=False):
    return vector.Printed(
        x=x, y=0.0, staff=staff, step=step, kind="black", grace=grace, alter=alter
    )


def test_accidentals_hold_to_the_bar_line_and_the_key_holds_elsewhere():
    staff = vector.Staff(bottom=100.0, spacing=5.0, left=0.0, right=600.0)
    heads = [
        printed(10, 4, -1),
        printed(20, 4),
        printed(30, 11),
        printed(40, 5, 1),
        printed(60, 5),
        printed(70, 4),
    ]
    page = vector.PagePrint([staff], heads, ["treble"], [{"F": 1}], [[50.0]])
    seq = vector.resolve_pitches([page])
    pitches = [(h.letter, h.octave, h.sounding_alter) for h in seq]
    # step 4 = B4; the explicit flat holds for the next B4 but not B5; F# is the key
    assert pitches[:3] == [("B", 4, -1), ("B", 4, -1), ("B", 5, 0)]
    assert pitches[3] == ("C", 5, 1) and pitches[4] == ("C", 5, 0)  # bar line at 50
    assert pitches[5] == ("B", 4, 0)
    bass = vector.PagePrint([staff], [printed(10, 0)], ["bass"], [{}], [[]])
    low = vector.resolve_pitches([bass])[0]
    assert (low.letter, low.octave) == ("G", 2)


def test_correct_pitches_fixes_aligned_notes_and_counts_the_rest():
    tree = score(
        [note("B", 4, 4, alter=-1) + note("D", 5, 4) + note("F", 5, 4, alter=1) + note("G", 5, 4)]
    )
    part = musicxml.first_part(tree.getroot())
    staff = vector.Staff(bottom=100.0, spacing=5.0, left=0.0, right=600.0)
    # printed: B4 natural, D5, F5 natural, G5, then an A5 the reading lacks
    heads = [printed(10, 4), printed(20, 6), printed(30, 8), printed(40, 9), printed(50, 10)]
    page = vector.PagePrint([staff], heads, ["treble"], [{}], [[]])
    correction = vector.correct_pitches(part, vector.resolve_pitches([page]))
    assert (correction.aligned, correction.changed, correction.unread, correction.unprinted) == (
        4,
        2,
        1,
        0,
    )
    pitches = [(p.findtext("step"), p.findtext("alter")) for p in part.iter("pitch")]
    assert pitches == [("B", None), ("D", None), ("F", None), ("G", None)]


def test_correct_pitches_keeps_a_tied_note_on_its_pitch():
    first = note("B", 4, 4, alter=-1, tie='<tie type="start"/>')
    second = note("B", 4, 4, alter=-1, tie='<tie type="stop"/>')
    tree = score([first, second + note("C", 5, 4) * 3])
    part = musicxml.first_part(tree.getroot())
    staff = vector.Staff(bottom=100.0, spacing=5.0, left=0.0, right=600.0)
    # the tied-into B4 carries no accidental on the page; the bar line sits between
    heads = [printed(10, 4, -1), printed(60, 4), printed(70, 5), printed(80, 5), printed(90, 5)]
    page = vector.PagePrint([staff], heads, ["treble"], [{}], [[50.0]])
    vector.correct_pitches(part, vector.resolve_pitches([page]))
    pitches = [p.findtext("alter") for p in part.iter("pitch")]
    assert pitches[0] == "-1" and pitches[1] == "-1" and pitches[2] is None


def test_long_mismatched_stretches_are_reported_not_paired():
    tree = score([note("C", 4, 4) * 6])
    part = musicxml.first_part(tree.getroot())
    staff = vector.Staff(bottom=100.0, spacing=5.0, left=0.0, right=600.0)
    heads = [printed(10 * k, 10 + k) for k in range(6)]  # six quite different notes
    page = vector.PagePrint([staff], heads, ["treble"], [{}], [[]])
    correction = vector.correct_pitches(part, vector.resolve_pitches([page]))
    assert correction.changed == 0 and correction.unread == 6 and correction.unprinted == 6


def test_concat_drops_repeated_signatures_split_over_two_attribute_blocks():
    # homr's first measure: divisions in one <attributes>, key/time/clef in another
    def page() -> ET.ElementTree:
        xml = (
            '<score-partwise><part-list><score-part id="P1"><part-name>V</part-name>'
            '</score-part></part-list><part id="P1"><measure number="1">'
            "<attributes><divisions>6</divisions></attributes>"
            "<attributes><key><fifths>-1</fifths></key><time><beats>4</beats>"
            '<beat-type>4</beat-type></time><clef number="1"><sign>G</sign><line>2</line>'
            "</clef></attributes>" + note("C", 4, 6) * 4 + "</measure></part></score-partwise>"
        )
        return ET.ElementTree(ET.fromstring(xml))

    joined = musicxml.concat([page(), page()])
    measures = musicxml.first_part(joined.getroot()).findall("measure")
    assert len(measures) == 2
    assert measures[1].find("attributes") is None
    assert measures[0].find("attributes/divisions").text == "6"
    assert (
        measures[0].find("attributes/clef") is not None
        or measures[0].findall("attributes")[1].find("clef") is not None
    )


def test_byte_identical_pdfs_are_converted_once(tmp_path):
    from pdf2musicxml.convert import unique_pdfs

    (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4 same")
    (tmp_path / "b.pdf").write_bytes(b"%PDF-1.4 same")
    (tmp_path / "c.pdf").write_bytes(b"%PDF-1.4 other")
    unique, duplicates = unique_pdfs(tmp_path)
    assert [p.name for p in unique] == ["a.pdf", "c.pdf"]
    assert [(d.name, o.name) for d, o in duplicates] == [("b.pdf", "a.pdf")]


def test_superseded_outputs_are_removed(tmp_path):
    from pdf2musicxml.convert import Result, remove_stale_outputs

    old = tmp_path / "book - 01 lllll ll.musicxml"
    kept = tmp_path / "book - 02 FRIED BANANAS.musicxml"
    unrelated = tmp_path / "other.musicxml"
    for f in (old, kept, unrelated):
        f.write_text("<x/>")
    manifest = {"transcriptions": [{"output": str(old)}, {"output": str(kept)}]}

    def result(output):
        return Result(
            pdf="book.pdf",
            pages=[1],
            title="",
            instrument=None,
            output=str(output),
            engine="homr",
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

    remove_stale_outputs(
        manifest,
        [result(tmp_path / "book - 01 BLUEBERRY HILL.musicxml"), result(kept)],
        lambda _m: None,
        tmp_path,
    )
    assert not old.exists() and kept.exists() and unrelated.exists()

    # A manifest copied beside a conversion into ANOTHER folder names the
    # originals by absolute path: they are not this run's to remove.
    elsewhere = tmp_path / "scratch"
    elsewhere.mkdir()
    remove_stale_outputs(
        {"transcriptions": [{"output": str(kept)}]},
        [result(elsewhere / kept.name)],
        lambda _m: None,
        elsewhere,
    )
    assert kept.exists()


def test_render_command_and_detection(tmp_path, monkeypatch):
    from pdf2musicxml import render

    exe = tmp_path / "MuseScore4.exe"
    exe.write_bytes(b"")
    monkeypatch.setenv("PDF2MUSICXML_MUSESCORE", str(exe))
    assert render.find_musescore() == exe
    cmd = render.command(exe, tmp_path / "a.musicxml", tmp_path / "a.pdf")
    assert cmd == [str(exe), "-o", str(tmp_path / "a.pdf"), str(tmp_path / "a.musicxml")]


def test_numbered_running_headers_are_continuation_pages():
    first = page(
        0, 0.15, [line("Strode Rode", 24, 0.05), line("Alto Sax", 10, 0.1), line("notes", 10, 0.5)]
    )
    second = page(1, 0.05, [line("2 Strode Rode", 14, 0.04)])
    third = page(2, 0.05, [line("Strode Rode 3", 14, 0.04)])
    assert layout.group_pages([first, second, third]) == [[0, 1, 2]]
    # a page whose text is bar numbers only is a continuation page, not a scan
    numbers = page(1, 0.18, [line("81", 13, 0.07), line("3 3", 13, 0.2, font="OpusTextStd")])
    assert layout.group_pages([first, numbers]) == [[0, 1]]


def test_octave_misread_still_aligns_on_letters():
    tree = score([note("E", 6, 4) + note("G", 6, 4) + note("E", 6, 4) + note("G", 6, 4)])
    part = musicxml.first_part(tree.getroot())
    staff = vector.Staff(bottom=100.0, spacing=5.0, left=0.0, right=600.0)
    heads = [printed(10, 0), printed(20, 2), printed(30, 0), printed(40, 2)]  # E4 G4 E4 G4
    page = vector.PagePrint([staff], heads, ["treble"], [{}], [[]])
    correction = vector.correct_pitches(part, vector.resolve_pitches([page]))
    assert correction.aligned == 4 and correction.changed == 4
    assert [p.findtext("octave") for p in part.iter("pitch")] == ["4", "4", "4", "4"]


def test_accent_stacked_on_a_head_is_not_a_note():
    staff = vector.Staff(bottom=100.0, spacing=5.0, left=0.0, right=600.0)
    head = vector.Printed(x=50.0, y=110.0, staff=0, step=4, kind="head", grace=False, char="\u0153")
    accent = vector.Printed(x=50.5, y=122.0, staff=0, step=9, kind="head", grace=False, char=">")
    half = vector.Printed(x=90.0, y=110.0, staff=0, step=4, kind="head", grace=False, char="\u02d9")
    kept = vector.drop_articulations([head, accent, half], [staff])
    assert [h.char for h in kept] == ["\u0153", "\u02d9"]


def _head(x: float, step: int, char: str = "œ", staff: vector.Staff | None = None):
    staff = staff or vector.Staff(bottom=100.0, spacing=5.0, left=0.0, right=600.0)
    y = staff.bottom + step * staff.spacing / 2
    return vector.Printed(x=x, y=y, staff=0, step=step, kind="head", grace=False, char=char)


def _ledger(x: float, step: int, thick: float = 0.3, spacing: float = 5.0, bottom: float = 100.0):
    """A ledger stroke's box at that staff step, 2.4 spaces wide, centred on x."""
    y = bottom + step * spacing / 2
    return (x - 1.2 * spacing, y - thick / 2, x + 1.2 * spacing, y + thick / 2)


def test_an_8va_mark_out_of_the_staff_is_not_a_note():
    """Shade of Jade, bar 85: the 8va's "8" is a notehead's size and shape
    where an F6 would sit, with no ledger near it. Read as a note, it slid
    the note alignment one head late and bar 84's quarter-note triplet went
    unread."""
    staff = vector.Staff(bottom=100.0, spacing=5.0, left=0.0, right=600.0)
    eight = _head(72.0, 15, char="“")
    real = _head(140.0, 15)
    paths = [_ledger(140.0, 10), _ledger(140.0, 12), _ledger(140.0, 14)]
    kept = vector.drop_unledgered([eight, real], [staff], paths)
    assert kept == [real]


def test_a_hand_drawn_ledger_counts_and_notes_on_the_staff_are_never_judged():
    """Inkpen2 and Broadway Copyist draw a ledger 0.7 of a space thick."""
    staff = vector.Staff(bottom=100.0, spacing=5.0, left=0.0, right=600.0)
    high = _head(200.0, 11)
    low = _head(250.0, -3)
    inside = [_head(300.0, step) for step in (-1, 0, 4, 9)]
    paths = [_ledger(200.0, 10, thick=3.5), _ledger(250.0, -2, thick=3.5)]
    heads = [high, low, *inside]
    assert vector.drop_unledgered(heads, [staff], paths) == heads
    assert vector.drop_unledgered(heads, [staff], []) == inside


def test_a_note_filed_under_the_wrong_staff_keeps_its_ledgers_on_the_far_side():
    """A high note of the staff below, nearer the staff above's centre: its
    ledgers lie between it and its own staff, not the one it was filed
    under. Near is near, whichever side."""
    staff = vector.Staff(bottom=100.0, spacing=5.0, left=0.0, right=600.0)
    head = _head(150.0, -9)  # 4.5 spaces under the staff it was filed under
    own_ledger = (150.0 - 6.0, head.y - 0.15, 150.0 + 6.0, head.y + 0.15)  # through it
    assert vector.drop_unledgered([head], [staff], [own_ledger]) == [head]
    # A stem or a beam is not a ledger: too narrow, too thick.
    stem = (149.5, head.y - 20.0, 150.5, head.y + 2.0)
    beam = (140.0, head.y - 3.0, 160.0, head.y + 3.0)
    assert vector.drop_unledgered([head], [staff], [stem, beam]) == []


def test_audiveris_book_is_rebuilt_when_the_pages_change(tmp_path, monkeypatch):
    pytest.importorskip("PIL")  # _read_with opens the pages and writes the book with it
    from PIL import Image

    from pdf2musicxml import convert

    pages = []
    for k in range(3):
        image = tmp_path / f"p00{k + 1}.png"
        Image.new("L", (40, 60), 255).save(image)
        pages.append(image)
    calls = []

    def fake_run(book, out_dir, *, font="standard", timeout=3600, reuse=True):
        calls.append(reuse)
        target = out_dir / "input.xml"
        target.write_text(
            '<score-partwise><part-list><score-part id="P1"><part-name>V</part-name>'
            '</score-part></part-list><part id="P1"><measure number="1"><attributes>'
            "<divisions>1</divisions></attributes></measure></part></score-partwise>"
        )
        return [target]

    monkeypatch.setattr(convert.audiveris, "run", fake_run)
    monkeypatch.setattr(convert.audiveris, "warnings", lambda _log: [])
    tdir = tmp_path / "t01"
    convert._read_with("audiveris", pages[:1], tdir, "standard")
    convert._read_with("audiveris", pages[:1], tdir, "standard")
    convert._read_with("audiveris", pages, tdir, "standard")
    assert calls == [False, True, False]  # fresh, reused, fresh again for the new page set


def test_manifest_groups_count_only_when_edited():
    from pdf2musicxml.convert import manifest_edited

    entry = {"pages": [1, 2], "title": "Minority", "instrument": "Alto Saxophone"}
    detected = [{"pages": [1, 2], "title": "Minority", "instrument": "Alto Saxophone"}]
    assert not manifest_edited({"transcriptions": [entry], "detected": detected})
    assert not manifest_edited({"transcriptions": [entry]})  # an older manifest: no record
    changed = {**entry, "pages": [1, 2, 3]}
    assert manifest_edited({"transcriptions": [changed], "detected": detected})
    renamed = {**entry, "title": "Minority (Take 3)"}
    assert manifest_edited({"transcriptions": [renamed], "detected": detected})


def test_repeated_title_in_the_header_is_a_continuation_page():
    first = page(
        0, 0.15, [line("Light Green", 24, 0.05), line("Alto Sax", 10, 0.1), line("notes", 10, 0.5)]
    )
    # a running header without a number, and a performance word larger than it
    fourth = page(1, 0.06, [line("Light Green", 13.3, 0.03), line("Glissando", 13.4, 0.068)])
    # a numbered header beside another word on the page
    third = page(2, 0.06, [line("Light Green 3", 16.8, 0.03), line("Rubato", 16.8, 0.15)])
    assert layout.group_pages([first, fourth, third]) == [[0, 1, 2]]
    assert layout.title_key("2  Strode Rode") == layout.title_key("Strode Rode 3") == "strode rode"


def test_a_watermark_below_the_title_zone_is_not_a_title():
    lines = [
        line("STRAIGHT", 8.3, 0.078, font="Inkpen2ScriptStd"),
        line("ESLEY CHIN", 74.0, 0.226),
        line("ESLEYCHIN.COM", 77.6, 0.305),
        line("Transcribed by Wesley Chin", 14.0, 0.93),
    ]
    assert layout.pick_title(lines) is None


def test_render_removes_proof_sheets_of_superseded_files(tmp_path, monkeypatch):
    from pdf2musicxml import render

    exe = tmp_path / "MuseScore4.exe"
    exe.write_bytes(b"")
    monkeypatch.setenv("PDF2MUSICXML_MUSESCORE", str(exe))
    out = tmp_path / ".render"
    out.mkdir()
    (out / "old - 01 lllll.pdf").write_bytes(b"%PDF")
    live = tmp_path / "live.musicxml"
    live.write_text("<x/>")
    (out / "live.pdf").write_bytes(b"%PDF")
    import os

    os.utime(out / "live.pdf", None)  # newer than its source: reused, MuseScore never called
    report = render.render_folder(tmp_path)
    assert [p.name for p in report.rendered] == ["live.pdf"] and not report.failed
    assert not (out / "old - 01 lllll.pdf").exists()


def tuplet_note(step, duration, kind, mark=None, actual=3, normal=2):
    notations = f'<tuplet type="{mark}"/>' if mark else ""
    return (
        f"<note><pitch><step>{step}</step><octave>4</octave></pitch><duration>{duration}</duration>"
        f"<voice>1</voice><type>{kind}</type><time-modification><actual-notes>{actual}"
        f"</actual-notes><normal-notes>{normal}</normal-notes></time-modification>"
        f"<notations>{notations}</notations></note>"
    )


def test_tuplet_brackets_that_do_not_add_up_are_stripped_and_good_ones_kept():
    good = (
        tuplet_note("C", 4, "eighth", "start")
        + tuplet_note("D", 4, "eighth")
        + tuplet_note("E", 4, "eighth", "stop")
    )
    bad = (
        tuplet_note("A", 4, "eighth", "start")
        + tuplet_note("A", 4, "eighth")
        + tuplet_note("F", 8, "quarter", "stop")
    )
    mixed = tuplet_note("G", 8, "quarter", "start") + tuplet_note("A", 4, "eighth", "stop")
    tree = score(
        [good + note("C", 4, 12) * 2, bad + note("C", 4, 12) * 2, mixed + note("C", 4, 12) * 3],
        divisions=12,
    )
    part = musicxml.first_part(tree.getroot())
    assert musicxml.repair_tuplets(part) == 1
    measures = part.findall("measure")
    assert len(measures[0].findall("note/time-modification")) == 3  # the triplet stays
    assert measures[0].find("note/time-modification/normal-type").text == "eighth"
    assert len(measures[1].findall("note/time-modification")) == 0  # the bad bracket goes
    assert [n.findtext("duration") for n in measures[1].findall("note")][:3] == ["4", "4", "8"]
    # quarter + eighth under 3:2 adds up to three eighths: kept, with the base written in
    assert measures[2].find("note/time-modification/normal-type").text == "eighth"


def test_unclosed_tuplet_is_stripped():
    tree = score(
        [tuplet_note("C", 4, "eighth", "start") + tuplet_note("D", 4, "eighth") + note("E", 4, 12)],
        divisions=12,
    )
    part = musicxml.first_part(tree.getroot())
    assert musicxml.repair_tuplets(part) == 1
    assert part.find("measure/note").find("time-modification") is None


def test_unbracketed_tuplet_runs_must_make_whole_tuplets():
    four_quarters = "".join(tuplet_note(s, 8, "quarter") for s in "EDCA")  # 4 x 3:2 quarters
    six_eighths = "".join(tuplet_note(s, 4, "eighth") for s in "CDEFGA")  # two whole triplets
    tree = score([four_quarters + note("C", 4, 12), six_eighths + note("C", 4, 12)], divisions=12)
    part = musicxml.first_part(tree.getroot())
    assert musicxml.repair_tuplets(part) == 1
    measures = part.findall("measure")
    assert len(measures[0].findall("note/time-modification")) == 0
    assert len(measures[1].findall("note/time-modification")) == 6


def test_middle_notes_of_a_good_bracket_are_not_taken_for_a_bare_run():
    good = (
        tuplet_note("C", 4, "eighth", "start")
        + tuplet_note("D", 4, "eighth")
        + tuplet_note("E", 4, "eighth", "stop")
    )
    part = musicxml.first_part(score([good + note("C", 4, 12) * 3], divisions=12).getroot())
    assert musicxml.repair_tuplets(part) == 0


def test_mixed_values_in_a_bare_run_are_not_several_tuplets():
    run = "".join(tuplet_note(s, 4, "eighth") for s in "CDEF") + tuplet_note("G", 2, "16th")
    part = musicxml.first_part(score([run + note("C", 4, 12)], divisions=12).getroot())
    assert musicxml.repair_tuplets(part) == 1
    assert part.find("measure/note").find("time-modification") is None


def test_chord_tones_on_a_rest_or_after_a_backup_are_unchorded():
    chord_tone = (
        "<note><chord/><pitch><step>E</step><octave>4</octave></pitch><duration>4</duration>"
        "<voice>1</voice><type>quarter</type></note>"
    )
    measures = [
        rest(4)
        + chord_tone
        + note("C", 4, 4)
        + chord_tone
        + note("D", 4, 4),  # on a rest: no; on C: yes
        note("C", 4, 4) + "<backup><duration>4</duration></backup>" + chord_tone + note("D", 4, 12),
        chord_tone + note("D", 4, 12),  # first in the bar
    ]
    part = musicxml.first_part(score(measures).getroot())
    assert musicxml.repair_chords(part) == 3
    chords = [len(m.findall("note/chord")) for m in part.findall("measure")]
    assert chords == [1, 0, 0]


def test_dotted_values_never_become_a_tuplet_unit():
    dotted = (
        "<note><pitch><step>C</step><octave>4</octave></pitch><duration>6</duration>"
        "<voice>1</voice><type>eighth</type><dot/><time-modification><actual-notes>3"
        "</actual-notes><normal-notes>2</normal-notes></time-modification></note>"
    )
    part = musicxml.first_part(score([dotted * 3 + note("C", 4, 12)], divisions=12).getroot())
    assert musicxml.repair_tuplets(part) == 1  # three dotted eighths under 3:2: stripped, no crash
    assert part.find("measure/note").find("time-modification") is None


def test_mixed_quarter_and_eighth_run_gets_its_unit_named():
    run = "".join(tuplet_note(s, 8, "quarter") for s in "GA") + "".join(
        tuplet_note(s, 4, "eighth") for s in "BC"
    )
    part = musicxml.first_part(score([run + note("C", 4, 12) * 2], divisions=12).getroot())
    assert musicxml.repair_tuplets(part) == 0
    assert {m.text for m in part.iter("normal-type")} == {"quarter"}


def test_two_note_tremolos_are_stripped_single_note_ones_kept():
    start = note("B", 4, 4, notations='<ornaments><tremolo type="start">3</tremolo></ornaments>')
    stop = note("B", 4, 4, notations='<ornaments><tremolo type="stop">3</tremolo></ornaments>')
    single = note("C", 4, 4, notations="<ornaments><tremolo>3</tremolo></ornaments>")
    part = musicxml.first_part(
        score([start + note("C", 4, 4) * 3, stop + single + note("C", 4, 4) * 2]).getroot()
    )
    assert musicxml.strip_spanning_tremolos(part) == 2
    assert len(part.findall("measure/note/notations/ornaments/tremolo")) == 1


def test_convert_command_prints_the_report(tmp_path, monkeypatch, capsys):
    from pdf2musicxml import cli
    from pdf2musicxml.convert import Result

    pdf = tmp_path / "solo.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    fake = Result(
        pdf=str(pdf),
        pages=[1],
        title="Solo",
        instrument="Bb Trumpet",
        output=str(tmp_path / "solo.musicxml"),
        engine="homr",
        measures=3,
        notes=12,
        ties=1,
        tuplets=0,
        harmonies=0,
        time_signature="4/4",
        time_note="",
        off_bars=["2"],
        ties_from_slurs=1,
        dropped_parts=[],
    )
    monkeypatch.setattr(cli, "convert_path", lambda target, options: [fake])
    assert cli.main(["convert", str(pdf)]) == 0
    out = capsys.readouterr().out
    assert "solo.musicxml" in out and "3 bars, 12 notes" in out and "bars whose notes" in out


def test_summary_command_survives_a_console_that_cannot_encode_a_ligature(tmp_path, monkeypatch):
    """A title with a fi ligature (as PDFs print them) on a cp1252 console."""
    import io
    import json
    import sys

    from pdf2musicxml.cli import main

    (tmp_path / "a.pdf2musicxml.json").write_text(
        json.dumps(
            {
                "transcriptions": [
                    {
                        "output": str(tmp_path / "Conﬁrmation.musicxml"),
                        "pages": [1],
                        "measures": 4,
                        "notes": 10,
                        "chords_read": 0,
                        "printed_noteheads": 10,
                        "check_agreement": 0.5,
                        "off_bars": [],
                        "time_signature": "4/4",
                        "instrument": "Alto Saxophone",
                        "title": "Conﬁrmation",
                        "error": None,
                        "pdf": "x.pdf",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    console = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", console)
    assert main(["summary", str(tmp_path)]) == 0
    console.flush()
    printed = console.buffer.getvalue().decode("cp1252")
    assert "Con?rmation.musicxml" in printed
    assert "Conﬁrmation.musicxml" in (tmp_path / "SUMMARY.md").read_text(encoding="utf-8")


# ---------------------------------------------------------------- what else the page prints


def glyph(char, font, left, bottom, width, height):
    return vector.Glyph(char, font, left, bottom, left + width, bottom + height)


def test_music_family_takes_in_the_text_faces_that_is_music_font_leaves_out():
    from pdf2musicxml.pdfpages import music_family

    assert music_family("OpusTextStd") and music_family("Inkpen2ScriptStd")
    assert music_family("EngraverTextT") and not music_family("FuturaLT-Bold")


def test_tuplet_marks_are_lone_digits_in_the_band_among_the_notes():
    staff = vector.Staff(bottom=100.0, spacing=5.0, left=0.0, right=600.0)
    heads = [printed(x, 4) for x in (100, 112, 124, 200)]
    glyphs = [
        glyph("3", "OpusTextStd", 109, 85, 5, 7),  # under the first three: a triplet
        glyph("1", "Assistant-Regular", 40, 130, 4, 7),  # a bar number, two digits
        glyph("3", "Assistant-Regular", 45, 130, 5, 7),
        glyph("7", "Inkpen2ChordsStd", 150, 135, 4, 7),  # a chord symbol's
        glyph("3", "OpusTextStd", 150, 200, 5, 7),  # far above the staff
        glyph("3", "Times-BoldItalic", 250, 85, 5, 7),  # past the last note
    ]
    marks = vector.tuplet_marks(glyphs, [staff], heads)
    assert [(round(m.x, 1), m.staff, m.count) for m in marks] == [(111.5, 0, 3)]


def test_time_signature_from_stacked_digits_a_glyph_or_a_lone_numerator():
    staff = vector.Staff(bottom=100.0, spacing=5.0, left=0.0, right=600.0)
    stacked = [glyph("6", "OpusStd", 30, 110, 8, 10), glyph("8", "OpusStd", 30, 100, 8, 10)]
    assert [m.text for m in vector.time_signatures(stacked, [staff])] == ["6/8"]
    common = [glyph("c", "OpusStd", 30, 105, 8, 10)]
    assert [(m.text, m.symbol) for m in vector.time_signatures(common, [staff])] == [
        ("4/4", "common")
    ]
    cut = [glyph("C", "Maestro", 30, 104, 8, 11)]
    assert [(m.text, m.symbol) for m in vector.time_signatures(cut, [staff])] == [("2/2", "cut")]
    # pdfium drops the second of two identical characters whose boxes touch:
    # a lone numerator with a text object right under it is N/N ...
    lone = [glyph("4", "Inkpen2Std", 30, 110, 8, 10)]
    assert [m.text for m in vector.time_signatures(lone, [staff], [(30, 100, 38, 110.5)])] == [
        "4/4"
    ]
    # ... and nothing without one, or when the digit is a tuplet number's face.
    assert vector.time_signatures(lone, [staff]) == []
    text_face = [glyph("3", "OpusTextStd", 30, 110, 5, 7), glyph("4", "OpusTextStd", 30, 100, 5, 7)]
    assert vector.time_signatures(text_face, [staff]) == []
    twelve = [
        glyph("1", "OpusStd", 30, 110, 6, 10),
        glyph("2", "OpusStd", 36, 110, 6, 10),
        glyph("8", "OpusStd", 33, 100, 6, 10),
    ]
    assert [m.text for m in vector.time_signatures(twelve, [staff])] == ["12/8"]


def _tempo_line(beat="h", beat_font="OpusTextStd", number="128", words="Fast Swing", dot=False):
    glyphs = []
    x = 20.0
    for word in words.split():
        for char in word:
            glyphs.append(glyph(char, "FuturaLT-Bold", x, 700, 5, 8))
            x += 5.5
        x += 3.0
    glyphs.append(glyph(beat, beat_font, x + 4, 698, 4, 11))
    x += 10
    if dot:
        glyphs.append(glyph(".", beat_font, x, 700, 1.5, 1.5))
        x += 3
    glyphs.append(glyph("=", "OpusTextStd", x + 2, 703, 5, 3))
    x += 12
    for char in number:
        glyphs.append(glyph(char, "FuturaLT-Light", x, 702, 5, 8))
        x += 6
    return glyphs


def test_tempo_mark_reads_the_beat_glyph_the_number_and_the_words():
    tempo = vector.tempo_mark(_tempo_line())
    assert (tempo.unit, tempo.dots, tempo.per_minute, tempo.words) == ("half", 0, 128, "Fast Swing")
    assert tempo.quarters_per_minute == 256
    assert tempo.text == "Fast Swing half = 128"
    dotted = vector.tempo_mark(_tempo_line(beat="q", number="60", words="Medium", dot=True))
    assert (dotted.unit, dotted.dots, dotted.per_minute, dotted.words) == (
        "quarter",
        1,
        60,
        "Medium",
    )
    assert dotted.quarters_per_minute == 90
    # Finale sets the beat in Engraver Text; a Sibelius jazz score sets the
    # words in the family's Script face, which are words all the same.
    finale = vector.tempo_mark(_tempo_line(beat="q", beat_font="EngraverTextT", number="200"))
    assert (finale.unit, finale.per_minute) == ("quarter", 200)
    script = _tempo_line(beat="q", beat_font="Inkpen2TextStd", number="102", words="Swing")
    script = [
        vector.Glyph(g.char, "Inkpen2ScriptStd", g.left, g.bottom, g.right, g.top)
        if g.font == "FuturaLT-Bold"
        else g
        for g in script
    ]
    assert vector.tempo_mark(script).words == "Swing"
    # No beat glyph in a notation face, or a number no tempo is: nothing.
    assert vector.tempo_mark(_tempo_line(beat_font="FuturaLT-Bold")) is None
    assert vector.tempo_mark(_tempo_line(number="3")) is None


def test_set_tempo_writes_the_metronome_mark_and_the_playback_tempo():
    tree = score(quarters(2))
    root = tree.getroot()
    musicxml.set_tempo(root, "half", 128, words="Fast Swing")
    musicxml.set_tempo(root, "half", 128, words="Fast Swing")  # once only
    first = musicxml.first_part(root).find("measure")
    directions = first.findall("direction")
    assert len(directions) == 1
    assert [c.tag for c in first][:2] == ["attributes", "direction"]
    direction = directions[0]
    assert direction.findtext("direction-type/words") == "Fast Swing"
    assert direction.findtext("direction-type/metronome/beat-unit") == "half"
    assert direction.findtext("direction-type/metronome/per-minute") == "128"
    assert direction.find("sound").get("tempo") == "256"
    musicxml.set_tempo(root, "quarter", 60, dots=1)
    assert first.find("direction/direction-type/metronome/beat-unit-dot") is not None
    assert first.find("direction/sound").get("tempo") == "90"


def plain(step, octave, duration, kind):
    return (
        f"<note><pitch><step>{step}</step><octave>{octave}</octave></pitch>"
        f"<duration>{duration}</duration><voice>1</voice><type>{kind}</type></note>"
    )


def head(x, letter, octave=4, staff=0, page=0):
    return vector.Printed(
        x=x,
        y=0.0,
        staff=staff,
        step=0,
        kind="head",
        grace=False,
        letter=letter,
        octave=octave,
        page=page,
    )


def pages_with(heads, marks, barlines=None):
    return vector.PrintedPages(heads, marks, barlines or {(0, 0): []}, None, None)


def test_printed_triplet_number_makes_three_plain_eighths_a_triplet():
    letters = "CDEFGABCD"
    bar = "".join(plain(s, 4 if i < 7 else 5, 6, "eighth") for i, s in enumerate(letters))
    part = musicxml.first_part(score([bar], divisions=12).getroot())
    heads = [head(100 + 12 * i, s, 4 if i < 7 else 5) for i, s in enumerate(letters)]
    mark = vector.TupletMark(x=112.0, y=0.0, staff=0, count=3, spacing=5.0)
    result = vector.apply_printed_tuplets(part, pages_with(heads, [mark]))
    assert (result.marks, result.applied, result.unprinted) == (1, 1, 0)
    notes = part.findall("measure/note")
    assert [n.findtext("duration") for n in notes[:4]] == ["4", "4", "4", "6"]
    assert [n.findtext("time-modification/actual-notes") for n in notes[:3]] == ["3"] * 3
    assert notes[0].find('notations/tuplet[@type="start"]') is not None
    assert notes[2].find('notations/tuplet[@type="stop"]') is not None
    assert musicxml.bars(part)[0].length == 4  # the bar that held one eighth too many adds up
    assert result.changes == ["bar 1: 3 eighths made a 3:2 from the page"]


def test_printed_number_over_a_group_the_engine_split_wrong_equalises_the_values():
    # 16th 16th eighth under a "3": the total is a quarter, the split is not the page's.
    bar = plain("C", 4, 3, "16th") + plain("D", 4, 3, "16th") + plain("E", 4, 6, "eighth")
    bar += plain("F", 4, 12, "quarter") * 3
    part = musicxml.first_part(score([bar], divisions=12).getroot())
    heads = [head(100 + 12 * i, s) for i, s in enumerate("CDEFFF")]
    mark = vector.TupletMark(x=112.0, y=0.0, staff=0, count=3, spacing=5.0)
    result = vector.apply_printed_tuplets(part, pages_with(heads, [mark]))
    assert result.applied == 1
    notes = part.findall("measure/note")
    assert [(n.findtext("type"), n.findtext("duration")) for n in notes[:3]] == [
        ("eighth", "4")
    ] * 3
    assert result.changes[0].endswith("(values equalised)")


def test_printed_quintuplet_refines_the_divisions_when_the_ratio_needs_it():
    bar = "".join(plain(s, 4, 3, "16th") for s in "CDEFG") + plain("A", 4, 12, "quarter") * 3
    part = musicxml.first_part(score([bar], divisions=12).getroot())
    heads = [head(100 + 10 * i, s) for i, s in enumerate("CDEFGAAA")]
    mark = vector.TupletMark(x=120.0, y=0.0, staff=0, count=5, spacing=5.0)
    result = vector.apply_printed_tuplets(part, pages_with(heads, [mark]))
    assert result.applied == 1
    part_divisions = part.find("measure/attributes/divisions").text
    notes = part.findall("measure/note")
    assert part_divisions == "60"
    assert [n.findtext("duration") for n in notes[:6]] == ["12"] * 5 + ["60"]
    assert notes[0].findtext("time-modification/normal-notes") == "4"
    assert musicxml.bars(part)[0].length == 4


def test_printed_number_leaves_alone_what_it_cannot_claim_and_counts_why():
    triplet = "".join(
        tuplet_note(s, 4, "eighth", m) for s, m in (("C", "start"), ("D", None), ("E", "stop"))
    )
    bar1 = triplet + plain("F", 4, 12, "quarter") * 3  # the engine read it already
    bar2 = (
        plain("G", 4, 6, "eighth")
        + rest(6)
        + plain("A", 4, 6, "eighth")
        + plain("B", 4, 6, "eighth")
    )
    bar2 += plain("C", 5, 12, "quarter") * 2  # a rest inside the group
    bar3 = plain("D", 5, 12, "quarter") * 4  # a group across the bar line into bar 4
    bar4 = plain("E", 5, 12, "quarter") * 4
    part = musicxml.first_part(score([bar1, bar2, bar3, bar4], divisions=12).getroot())
    heads = [head(100 + 12 * i, s) for i, s in enumerate("CDEFFF")]
    heads += [head(200 + 12 * i, s, 4 if s in "GAB" else 5) for i, s in enumerate("GABCC")]
    heads += [head(300 + 12 * i, "D", 5) for i in range(4)] + [
        head(348 + 12 * i, "E", 5) for i in range(4)
    ]
    marks = [
        vector.TupletMark(x=112.0, y=0.0, staff=0, count=3, spacing=5.0),
        vector.TupletMark(x=212.0, y=0.0, staff=0, count=3, spacing=5.0),
        vector.TupletMark(x=348.0, y=0.0, staff=0, count=3, spacing=5.0),  # D E E: two bars
        vector.TupletMark(x=500.0, y=0.0, staff=0, count=3, spacing=5.0),  # nothing there
    ]
    barlines = {(0, 0): [190.0, 290.0]}  # the third bar line is one the finder missed
    result = vector.apply_printed_tuplets(part, pages_with(heads, marks, barlines))
    assert (result.already, result.uneven, result.unplaced, result.applied) == (1, 2, 1, 0)
    assert result.unprinted == 0
    assert "bar 2: 3 printed, another note or rest read between them" in result.changes
    assert "bar 3: 3 printed, the read notes straddle a bar line" in result.changes
    assert any("no run of 3 notes or rests" in line for line in result.changes)
    assert len(part.findall("measure/note/time-modification")) == 3  # bar 1's, untouched


def test_engine_tuplets_under_no_printed_number_are_counted_not_stripped():
    triplet = "".join(
        tuplet_note(s, 4, "eighth", m) for s, m in (("C", "start"), ("D", None), ("E", "stop"))
    )
    part = musicxml.first_part(
        score([triplet + plain("F", 4, 12, "quarter") * 3], divisions=12).getroot()
    )
    heads = [head(100 + 12 * i, s) for i, s in enumerate("CDEFFF")]
    mark = vector.TupletMark(x=148.0, y=0.0, staff=0, count=3, spacing=5.0)  # over the quarters
    result = vector.apply_printed_tuplets(part, pages_with(heads, [mark]))
    assert result.applied == 1 and result.unprinted == 1
    assert len(part.findall("measure/note/time-modification")) == 6


def test_collect_gathers_marks_time_and_tempo_across_pages():
    staff = vector.Staff(bottom=100.0, spacing=5.0, left=0.0, right=600.0)
    first = vector.PagePrint(
        [staff],
        [printed(100, 0), printed(120, 2)],
        ["treble"],
        [{}],
        [[110.0]],
        tuplets=[vector.TupletMark(105.0, 80.0, 0, 3, 5.0)],
        times=[vector.TimeMark(0, 30.0, 3, 4)],
        tempo=None,
    )
    second = vector.PagePrint(
        [staff],
        [printed(100, 4)],
        ["treble"],
        [{}],
        [[]],
        tuplets=[vector.TupletMark(100.0, 80.0, 0, 5, 5.0)],
        times=[vector.TimeMark(0, 30.0, 4, 4)],
        tempo=vector.Tempo("quarter", 0, 120),
    )
    pages = vector.collect([first, second])
    assert [(m.page, m.count) for m in pages.marks] == [(0, 3), (1, 5)]
    assert pages.time.text == "3/4" and pages.tempo.per_minute == 120
    assert pages.barlines == {(0, 0): [110.0], (1, 0): []} and pages.barline_count == 1
    assert [h.page for h in pages.heads] == [0, 0, 1]


def test_printed_number_beside_a_grace_note_is_reported_not_applied():
    grace = (
        "<note><grace/><pitch><step>B</step><octave>3</octave></pitch>"
        "<voice>1</voice><type>16th</type></note>"
    )
    bar = grace + "".join(plain(s, 4, 6, "eighth") for s in "CDEFGABC") + plain("D", 5, 6, "eighth")
    part = musicxml.first_part(score([bar], divisions=12).getroot())
    heads = [head(97, "B", 3)] + [head(100 + 12 * i, s) for i, s in enumerate("CDEFGABC")]
    heads[0].grace = True
    heads.append(head(196, "D", 5))
    # The grace head takes no place in the run, so the "3" over C D E is C D E ...
    mark = vector.TupletMark(x=112.0, y=0.0, staff=0, count=3, spacing=5.0)
    result = vector.apply_printed_tuplets(part, pages_with(heads, [mark]))
    assert result.applied == 1
    # ... and a group whose read notes include a grace note is left alone, not crashed on.
    part = musicxml.first_part(score([bar], divisions=12).getroot())
    heads[0].grace = False
    mark = vector.TupletMark(x=104.0, y=0.0, staff=0, count=3, spacing=5.0)  # over B C D
    result = vector.apply_printed_tuplets(part, pages_with(heads, [mark]))
    assert result.applied == 0
    assert "a grace note among the read notes" in result.changes[0]


def test_an_accidental_stops_holding_where_the_reading_ends_the_bar():
    # The page's paths gave no bar line; the reading's second measure starts at the third note.
    bar1 = plain("F", 4, 12, "quarter") + plain("F", 4, 12, "quarter")
    bar2 = plain("F", 4, 12, "quarter") + plain("G", 4, 12, "quarter")
    part = musicxml.first_part(score([bar1, bar2], divisions=12).getroot())
    heads = [head(100, "F"), head(120, "F"), head(200, "F"), head(220, "G")]
    heads[0].alter = 1
    vector.sounding_alters(heads, [(0, 0, 0)] * 4)  # what the page alone says
    assert [h.sounding_alter for h in heads] == [1, 1, 1, 0]
    result = vector.correct_pitches(part, heads)
    assert result.alters_from_engine_bars == 1
    alters = [n.findtext("pitch/alter") for n in part.findall("measure/note")]
    assert alters == ["1", "1", None, None]


def test_printed_number_in_a_bar_of_several_voices_is_left_alone():
    # Shortening one voice's notes would send the <backup> past the bar's start.
    voice1 = "".join(plain(s, 4, 6, "eighth") for s in "CDEFGABC")
    voice2 = "<backup><duration>48</duration></backup>" + plain("C", 3, 48, "whole")
    part = musicxml.first_part(score([voice1 + voice2], divisions=12).getroot())
    heads = [head(100 + 12 * i, s) for i, s in enumerate("CDEFGABC")] + [head(100, "C", 3)]
    mark = vector.TupletMark(x=112.0, y=0.0, staff=0, count=3, spacing=5.0)
    result = vector.apply_printed_tuplets(part, pages_with(heads, [mark]))
    assert result.applied == 0 and result.uneven == 1
    assert "the bar has several voices" in result.changes[0]
    assert part.find("measure/note").find("time-modification") is None


def printed_rest(x, value, staff=0, page=0):
    return vector.Printed(
        x=x, y=0.0, staff=staff, step=4, kind="rest", grace=False, value=value, page=page
    )


def test_printed_triplet_with_a_rest_inside_claims_the_read_rest_too():
    # eighth rest, D, D under a "3", then quarters: the rest is an onset like a head.
    bar = rest(6) + plain("D", 5, 6, "eighth") * 2 + plain("C", 5, 12, "quarter") * 3
    part = musicxml.first_part(score([bar], divisions=12).getroot())
    heads = [head(112, "D", 5), head(124, "D", 5)] + [head(140 + 12 * i, "C", 5) for i in range(3)]
    pages = vector.PrintedPages(heads, [], {(0, 0): []}, None, None, [printed_rest(100, "eighth")])
    pages.marks.append(vector.TupletMark(x=112.0, y=0.0, staff=0, count=3, spacing=5.0))
    result = vector.apply_printed_tuplets(part, pages)
    assert result.applied == 1
    kids = part.findall("measure/note")
    assert kids[0].find("rest") is not None and kids[0].findtext("duration") == "4"
    assert [k.findtext("time-modification/actual-notes") for k in kids[:3]] == ["3"] * 3
    assert kids[0].find('notations/tuplet[@type="start"]') is not None
    assert "(1 rests)" in result.changes[0]
    assert musicxml.bars(part)[0].length == 4


def test_the_beams_over_a_group_set_its_value_when_the_engine_read_it_a_level_off():
    # The page beams E D C once (eighths); the engine read sixteenths.
    bar = "".join(plain(s, 5, 3, "16th") for s in "EDC") + plain("B", 4, 12, "quarter") * 3
    part = musicxml.first_part(score([bar], divisions=12).getroot())
    heads = [head(100 + 12 * i, s, 5) for i, s in enumerate("EDC")]
    heads += [head(150 + 12 * i, "B", 4) for i in range(3)]
    mark = vector.TupletMark(x=112.0, y=0.0, staff=0, count=3, spacing=5.0)
    pages = pages_with(heads, [mark])
    pages.beams = {(0, 0): [(98.0, 14.0, 126.0, 16.5)]}  # one beam, three spaces above the heads
    result = vector.apply_printed_tuplets(part, pages)
    assert (result.applied, result.revalued) == (1, 1)
    kids = part.findall("measure/note")
    assert [(k.findtext("type"), k.findtext("duration")) for k in kids[:3]] == [("eighth", "4")] * 3
    assert musicxml.bars(part)[0].length == 4
    assert (
        "3:2 of eighths over eighth, eighth, eighth (the reading had 16th, 16th, 16th)"
        in result.changes[0]
    )
    # Two beams are sixteenths, whatever the engine read; a tie hugging the heads is no beam.
    eighths = bar.replace("16th", "eighth").replace("<duration>3<", "<duration>6<")
    part = musicxml.first_part(score([eighths], divisions=12).getroot())
    pages.beams = {
        (0, 0): [(98.0, 14.0, 126.0, 16.5), (98.0, 18.0, 126.0, 20.5), (99.0, 3.0, 125.0, 8.0)]
    }
    result = vector.apply_printed_tuplets(part, pages)
    assert [k.findtext("type") for k in part.findall("measure/note")[:3]] == ["16th"] * 3


def test_two_read_measures_on_one_printed_bar_are_joined_and_the_repeat_goes():
    first = (
        plain("C", 4, 12, "quarter") * 2
        + '<barline location="right"><bar-style>light-light</bar-style></barline>'
    )
    second = (
        '<barline location="left"><bar-style>heavy-light</bar-style>'
        '<repeat direction="forward"/></barline>' + plain("D", 4, 12, "quarter") * 2
    )
    third = plain("E", 4, 12, "quarter") * 4
    part = musicxml.first_part(score([first, second, third], divisions=12).getroot())
    heads = [head(100 + 12 * i, s) for i, s in enumerate("CCDD")] + [
        head(200 + 12 * i, "E") for i in range(4)
    ]
    for h in heads[4:]:
        h.bar = 1  # one bar line on the page, between D and E
    pages = vector.PrintedPages(heads, [], {(0, 0): [190.0]}, None, None)
    result = vector.align_bars(part, pages)
    assert (result.merged, result.split) == (1, 0)
    measures = part.findall("measure")
    assert [m.get("number") for m in measures] == ["1", "2"]
    assert len(measures[0].findall("note")) == 4 and part.find("measure/barline") is None
    assert musicxml.bars(part)[0].length == 4


def test_one_read_measure_on_two_printed_bars_is_divided_where_the_second_begins():
    part = musicxml.first_part(score([plain("C", 4, 12, "quarter") * 8], divisions=12).getroot())
    heads = [head(100 + 12 * i, "C") for i in range(8)]
    for h in heads[4:]:
        h.bar = 1
    pages = vector.PrintedPages(heads, [], {(0, 0): [145.0]}, None, None)
    result = vector.align_bars(part, pages)
    assert (result.merged, result.split) == (0, 1)
    assert [len(m.findall("note")) for m in part.findall("measure")] == [4, 4]
    assert [m.get("number") for m in part.findall("measure")] == ["1", "2"]


def test_bars_are_left_as_read_when_their_lengths_do_not_back_the_page():
    # Two full bars the page (a finder that missed a bar line) calls one: joined, 8 beats.
    part = musicxml.first_part(score(quarters(2, 12), divisions=12).getroot())
    heads = [head(100 + 12 * i, "C") for i in range(8)]
    pages = vector.PrintedPages(heads, [], {(0, 0): []}, None, None)
    result = vector.align_bars(part, pages)
    assert (result.merged, result.split) == (0, 0)
    assert len(part.findall("measure")) == 2


def test_a_bar_the_other_reading_fills_replaces_one_this_reading_does_not():
    # Bar 2 read 5 beats here and 4 there; divisions differ (12 against 6) and are unified.
    mine = score([note("C", 4, 12) * 4, note("D", 4, 12) * 5, note("E", 4, 12) * 4], divisions=12)
    theirs = score(
        [note("C", 4, 6) * 4, note("D", 4, 6) * 3 + rest(6), note("E", 4, 6) * 3], divisions=6
    )
    part, other = musicxml.first_part(mine.getroot()), musicxml.first_part(theirs.getroot())
    result = musicxml.merge_readings(part, other)
    assert (result.compared, result.taken, result.bars) == (3, 1, ["2"])
    lengths = [b.length for b in musicxml.bars(part)]
    assert lengths == [4, 4, 4]  # bar 3: theirs is short, mine stays
    assert part.find("measure/attributes/divisions").text == "12"
    assert [n.findtext("duration") for n in part.findall("measure")[1].findall("note")] == [
        "12"
    ] * 4
    assert part.findall("measure")[1].get("number") == "2"


def test_the_pages_note_count_outranks_the_fill_when_choosing_between_readings():
    # Both fill bar 1; the page prints 3 notes there and only the other reading has 3.
    mine = score([note("C", 4, 12) * 4], divisions=12)
    theirs = score([note("C", 4, 12) * 2 + note("D", 4, 24)], divisions=12)
    part, other = musicxml.first_part(mine.getroot()), musicxml.first_part(theirs.getroot())
    assert musicxml.merge_readings(part, other, [3]).taken == 1
    assert len(part.findall("measure/note")) == 3
    # Bar counts that differ, with no system breaks and no notes in common, pair nothing.
    part = musicxml.first_part(score([note("C", 4, 4) * 4] * 2).getroot())
    other = musicxml.first_part(score([note("D", 4, 4) * 4] * 3).getroot())
    assert musicxml.merge_readings(part, other).compared == 0


def test_an_overfull_bar_loses_first_to_a_reading_one_note_short_at_most():
    """0.3.25: the page prints 4 notes; this reading holds all 4 but overruns
    the bar (a quarter read as a half). An overrun moves every later note,
    a missing note costs one: a reading with 3 that fills the bar wins. One
    with only 2 of the page's 4 filling the bar says little about rhythm,
    and the count decides again."""
    overfull = note("C", 4, 12) * 3 + note("D", 4, 24)  # 4 notes, 5 beats
    mine = score([overfull], divisions=12)
    three = score([note("C", 4, 12) * 2 + note("D", 4, 24)], divisions=12)  # 3 notes, 4 beats
    part, other = musicxml.first_part(mine.getroot()), musicxml.first_part(three.getroot())
    assert musicxml.merge_readings(part, other, [4]).taken == 1
    assert [b.length for b in musicxml.bars(part)] == [4]

    mine = score([overfull], divisions=12)
    two = score([note("C", 4, 24) * 2], divisions=12)  # 2 notes, 4 beats
    part, other = musicxml.first_part(mine.getroot()), musicxml.first_part(two.getroot())
    assert musicxml.merge_readings(part, other, [4]).taken == 0
    # A scan has no page count: the overrun loses outright.
    part, other = musicxml.first_part(mine.getroot()), musicxml.first_part(two.getroot())
    assert musicxml.merge_readings(part, other).taken == 1


def test_a_taken_bar_brings_notes_and_chords_only_and_the_file_is_left_to_musescore_to_beam():
    mine = score([note("C", 4, 12) * 4, note("D", 4, 12) * 5], divisions=12)
    theirs_bar2 = (
        '<print new-system="yes"/>'
        "<direction><direction-type><words>m9;</words></direction-type></direction>"
        "<harmony><root><root-step>G</root-step></root><kind>minor-seventh</kind></harmony>"
        + note("D", 4, 12, notations="").replace("<voice>", '<beam number="1">begin</beam><voice>')
        * 4
        + '<barline location="right"><bar-style>light-heavy</bar-style></barline>'
    )
    theirs = score([note("C", 4, 12) * 4, theirs_bar2], divisions=12)
    part, other = musicxml.first_part(mine.getroot()), musicxml.first_part(theirs.getroot())
    musicxml.set_tempo(mine.getroot(), "quarter", 120)
    first_note = part.find("measure/note")
    first_note.insert(0, ET.fromstring('<beam number="1">begin</beam>'))
    result = musicxml.merge_readings(part, other)
    assert result.taken == 1
    taken = part.findall("measure")[1]
    assert [c.tag for c in taken] == ["harmony"] + ["note"] * 4
    assert (
        part.find("measure/direction/direction-type/metronome") is not None
    )  # bar 1's tempo stays
    assert part.find(".//beam") is None


def test_printed_counts_follow_the_notes_bars_not_the_measure_index():
    # The reading joined bars 1 and 2 of the page into one measure: counts by the notes.
    part = musicxml.first_part(
        score(
            [
                plain("C", 4, 12, "quarter") * 4 + plain("D", 4, 12, "quarter") * 2,
                plain("E", 4, 24, "half") * 2,
            ],
            divisions=12,
        ).getroot()
    )
    heads = [head(100 + 12 * i, "C") for i in range(4)] + [head(160, "D"), head(172, "D")]
    heads += [head(200, "E"), head(224, "E")]
    for h in heads[4:6]:
        h.bar = 1
    for h in heads[6:]:
        h.bar = 2
    pages = vector.PrintedPages(heads, [], {(0, 0): [150.0, 190.0]}, None, None)
    assert vector.printed_count_per_measure(part, pages) == [None, 2]
    # An unknown count leaves that bar to the fill test: a four-beat bar 1 beats a six-beat one.
    other = musicxml.first_part(
        score(
            [plain("C", 4, 12, "quarter") * 4, plain("E", 4, 24, "half") * 2], divisions=12
        ).getroot()
    )
    assert musicxml.merge_readings(part, other, [None, 2]).bars == ["1"]


def test_a_bracket_over_quarter_quarter_and_two_eighths_is_a_quarter_triplet_split():
    # The page: B A as quarters, G# E beamed eighths, one "3" bracket over all four
    # (broken at the number); the engine read eighth, 16th, 16th, 16th.
    bar = plain("B", 4, 6, "eighth") + plain("A", 4, 3, "16th") + plain("G", 4, 3, "16th")
    bar += plain("E", 4, 3, "16th") + rest(24)
    part = musicxml.first_part(score([bar], divisions=12).getroot())
    heads = [head(100, "B"), head(120, "A"), head(140, "G"), head(155, "E")]
    mark = vector.TupletMark(x=120.0, y=30.0, staff=0, count=3, spacing=5.0)
    pages = pages_with(heads, [mark])
    pages.beams = {
        (0, 0): [(95.0, 29.0, 116.0, 31.0), (124.0, 29.0, 160.0, 31.0), (138.0, 14.0, 158.0, 16.5)]
    }
    result = vector.apply_printed_tuplets(part, pages)
    assert result.applied == 1
    kids = part.findall("measure/note")[:4]
    assert [(k.findtext("type"), k.findtext("duration")) for k in kids] == [
        ("quarter", "8"),
        ("quarter", "8"),
        ("eighth", "4"),
        ("eighth", "4"),
    ]
    assert kids[0].findtext("time-modification/normal-type") == "quarter"
    assert kids[3].find('notations/tuplet[@type="stop"]') is not None
    assert musicxml.bars(part)[0].length == 4
    assert "3:2 of quarters over quarter, quarter, eighth, eighth" in result.changes[0]
    # A flag glyph values an unbeamed note as an eighth: quarter, eighth under a "3".
    bar = plain("F", 5, 12, "quarter") + plain("E", 5, 6, "eighth") + rest(12) * 3
    part = musicxml.first_part(score([bar], divisions=12).getroot())
    heads = [head(100, "F", 5), head(120, "E", 5)]
    mark = vector.TupletMark(x=110.0, y=30.0, staff=0, count=3, spacing=5.0)
    pages = pages_with(heads, [mark])
    pages.beams = {(0, 0): [(95.0, 29.0, 107.0, 31.0), (113.0, 29.0, 125.0, 31.0)]}
    pages.flags = {(0, 0): [(122.0, 15.0, 1)]}
    pages.beams[(0, 0)].append((60.0, 44.0, 200.0, 46.0))  # a text line over the bar: no beam
    result = vector.apply_printed_tuplets(part, pages)
    assert result.applied == 1
    kids = part.findall("measure/note")[:2]
    assert [(k.findtext("type"), k.findtext("duration")) for k in kids] == [
        ("quarter", "8"),
        ("eighth", "4"),
    ]
    assert kids[0].findtext("time-modification/normal-type") == "eighth"


def test_a_bracket_holding_more_than_its_number_without_page_values_is_left_alone():
    # Three "3" brackets in a row: only the nearest segment on each side belongs to a number.
    bar = "".join(plain(s, 5, 3, "16th") for s in "EGBDCBAGF") + plain("E", 5, 12, "quarter")
    part = musicxml.first_part(score([bar], divisions=12).getroot())
    heads = [head(100 + 10 * i, s, 5) for i, s in enumerate("EGBDCBAGF")] + [head(200, "E", 5)]
    marks = [
        vector.TupletMark(x=110.0 + 30 * k, y=30.0, staff=0, count=3, spacing=5.0) for k in range(3)
    ]
    pages = pages_with(heads, marks)
    segments = []
    for k in range(3):
        left = 97.0 + 30 * k
        segments += [(left, 29.0, left + 9.0, 31.0), (left + 16.0, 29.0, left + 26.0, 31.0)]
    pages.beams = {(0, 0): segments}
    assert vector._bracket_extent(segments, marks[0]) == (97.0, 123.0)
    result = vector.apply_printed_tuplets(part, pages)
    assert result.applied == 3
    assert all(len(g) == 3 for g in [part.findall("measure/note")[i : i + 3] for i in (0, 3, 6)])
    assert musicxml.bars(part)[0].length == Fraction(3, 2) + 1
    # A bracket that does hold six onsets, with no beam or flag on the page: not a 3:2 over six.
    part = musicxml.first_part(score([bar], divisions=12).getroot())
    pages = pages_with(heads, [marks[0]])
    pages.beams = {(0, 0): [(95.0, 29.0, 107.0, 31.0), (113.0, 29.0, 152.0, 31.0)]}
    result = vector.apply_printed_tuplets(part, pages)
    assert result.applied == 0 and result.uneven == 1
    assert "over 6 onsets, values unknown" in result.changes[0]


# ---------------------------------------------------------------- rest bars, time changes, repeats


def test_a_plurality_of_bars_outvotes_a_declared_signature_few_bars_fill():
    # A scan: homr read 3/4 off a "C"; 4 of 11 inner bars fill four quarters (under
    # the 60% that decides alone), one fills three, the rest are long by an eighth or more.
    bars_ = [note("C", 4, 4) * 4] * 6 + [note("C", 4, 4) * 3] + [note("C", 4, 4) * 5] * 3
    bars_ += [note("C", 4, 4) * 4 + note("C", 4, 2)] * 3
    part = musicxml.first_part(score(bars_, divisions=4, time="3/4").getroot())
    fix = musicxml.fix_time_signature(part)
    assert fix.used == "4/4" and "against 1 filling the declared 3/4" in fix.note


def test_a_declared_signature_stands_when_the_commonest_length_is_not_three_times_it():
    bars_ = [note("C", 4, 4) * 4] * 5 + [note("C", 4, 4) * 3] * 3 + [note("C", 4, 4) * 5] * 4
    part = musicxml.first_part(score(bars_, divisions=4, time="3/4").getroot())
    fix = musicxml.fix_time_signature(part)
    assert fix.used == "3/4" and fix.note == "bars too irregular to decide"


def test_an_empty_bar_and_a_lone_whole_rest_become_whole_measure_rests_of_the_bar():
    whole = "<note><rest/><duration>16</duration><voice>1</voice><type>whole</type></note>"
    part = musicxml.first_part(
        score([whole, "", note("C", 4, 4) * 6], divisions=4, time="12/8").getroot()
    )
    assert musicxml.fill_rest_bars(part) == 2
    for measure in part.findall("measure")[:2]:
        notes = measure.findall("note")
        assert len(notes) == 1 and notes[0].find("rest").get("measure") == "yes"
        assert notes[0].findtext("duration") == "24" and notes[0].find("type") is None
    assert [b.number for b in musicxml.bars(part) if b.length != b.expected] == []


def test_a_bar_of_notes_or_of_two_rests_is_not_touched_by_the_rest_fill():
    part = musicxml.first_part(score([rest(8) + rest(8), note("C", 4, 4) * 4]).getroot())
    assert musicxml.fill_rest_bars(part) == 0
    rests = [n for n in part.iter("note") if n.find("rest") is not None]
    assert all(n.find("rest").get("measure") is None for n in rests)


def test_repeat_marks_go_unless_the_other_reading_read_that_direction():
    forward = '<barline location="right"><repeat direction="forward"/></barline>'
    backward = (
        '<barline location="right"><bar-style>light-heavy</bar-style>'
        '<repeat direction="backward"/></barline>'
    )
    part = musicxml.first_part(
        score([note("C", 4, 4) * 4 + forward, note("D", 4, 4) * 4 + backward]).getroot()
    )
    assert musicxml.strip_repeats(part, {"backward"}) == 1
    first, second = part.findall("measure")
    assert first.find("barline/repeat") is None
    assert first.findtext("barline/bar-style") == "light-light"  # a double bar stays
    assert second.find("barline/repeat").get("direction") == "backward"
    assert musicxml.repeat_directions(part) == {"backward"}


def test_a_double_bar_line_drawn_as_two_paths_is_one_bar_line():
    class Obj:
        def __init__(self, bounds):
            self.type = 2  # FPDF_PAGEOBJ_PATH
            self._bounds = bounds

        def get_bounds(self):
            return self._bounds

    class Page:
        def get_objects(self, max_depth=4):
            # bottom line 100, spacing 5, top 120; lines overshoot 1 pt both ends
            return [Obj((x, 99.0, x + 1.0, 121.0)) for x in (150.0, 152.5, 300.0)]

    staff = vector.Staff(bottom=100.0, spacing=5.0, left=50.0, right=500.0)
    assert vector.find_barlines(Page(), [staff]) == [[151.75, 300.5]]


def test_a_thick_bar_on_the_middle_line_with_a_music_font_count_is_a_multi_bar_rest():
    staff = vector.Staff(bottom=100.0, spacing=5.0, left=50.0, right=500.0)
    barlines = [[150.0, 300.0, 450.0]]
    h_bar = (170.0, 108.0, 280.0, 111.5)  # 22 spaces wide, 0.7 thick, centred on line 3
    beam = (320.0, 108.0, 360.0, 111.5)  # same shape under a "3" that is a tuplet number
    count = glyph("7", "OpusStd", 220.0, 126.0, 6.0, 10.5)  # step 11, 2.1 spaces tall
    tuplet = glyph("3", "OpusTextStd", 335.0, 126.0, 4.0, 7.0)
    heads = [head(330.0, "C"), head(350.0, "D")]
    for h in heads:
        h.y = 110.0
    found = vector.multi_rests([h_bar, beam], [count, tuplet], [staff], barlines, heads)
    assert [(m.staff, m.count, round(m.x)) for m in found] == [(0, 7, 225)]


def test_a_count_over_a_bar_that_holds_a_notehead_is_not_a_multi_bar_rest():
    staff = vector.Staff(bottom=100.0, spacing=5.0, left=50.0, right=500.0)
    h_bar = (170.0, 108.0, 280.0, 111.5)
    count = glyph("4", "OpusStd", 220.0, 126.0, 6.0, 10.5)
    inside = head(200.0, "C")
    assert vector.multi_rests([h_bar], [count], [staff], [[150.0, 300.0]], [inside]) == []


def _times_pages(heads, times, multirests=(), rests=()):
    return vector.PrintedPages(
        heads, [], {(0, 0): []}, None, None, list(rests), {}, {}, list(times), list(multirests)
    )


def test_a_printed_change_of_signature_lands_on_the_bar_it_begins_and_unbacked_ones_go():
    # Four bars of quarters; the page prints 2/4 at bar 3 (two quarters), the engine
    # had declared 3/4 at bar 2, which no printed signature backs.
    bars_ = [note("C", 4, 4) * 4, note("C", 4, 4) * 4, note("C", 4, 4) * 2, note("C", 4, 4) * 2]
    part = musicxml.first_part(score(bars_, divisions=4).getroot())
    musicxml.set_measure_time(part.findall("measure")[1], 3, 4)
    heads = [head(100 + 10 * i, "C") for i in range(12)]
    for i, h in enumerate(heads):
        h.bar = 0 if i < 4 else 1 if i < 8 else 2 if i < 10 else 3
    times = [
        vector.TimeMark(0, 60.0, 4, 4, page=0, bar=0),
        vector.TimeMark(0, 175.0, 2, 4, page=0, bar=2),
    ]
    result = vector.apply_printed_times(part, _times_pages(heads, times))
    assert (result.placed, result.dropped) == (1, 1)
    assert musicxml.time_changes(part) == ["bar 3: 2/4"]
    assert [b.number for b in musicxml.bars(part) if b.length != b.expected] == []


def test_a_multi_bar_rest_replaces_what_the_engine_wrote_for_it_with_its_count_of_bars():
    # Notes, then one empty read bar where the page prints a 3-bar rest and a
    # bar with a whole rest beside it, then notes: four bars of rest.
    whole = "<note><rest/><duration>16</duration><voice>1</voice><type>whole</type></note>"
    part = musicxml.first_part(
        score([note("C", 4, 4) * 4, "", whole, note("D", 4, 4) * 4], divisions=4).getroot()
    )
    heads = [head(100 + 10 * i, "C") for i in range(4)]
    heads += [head(400 + 10 * i, "D") for i in range(4)]
    for h in heads[4:]:
        h.bar = 5
    multirest = vector.MultiRest(0, 250.0, 3, page=0, bar=2)
    plain_rest = printed_rest(330.0, "whole")
    plain_rest.bar = 4
    pages = _times_pages(heads, [], [multirest], [plain_rest])
    result = vector.expand_multirests(part, pages)
    assert (result.bars, result.replaced) == (4, 2)
    measures = part.findall("measure")
    assert [m.get("number") for m in measures] == ["1", "2", "3", "4", "5", "6"]
    assert all(m.find("note/rest").get("measure") == "yes" for m in measures[1:5])
    assert measures[5].findall("note")[0].findtext("pitch/step") == "D"


def test_a_rest_the_page_prints_a_signature_at_takes_that_signature():
    part = musicxml.first_part(
        score([note("C", 4, 4) * 4, "", note("D", 4, 4) * 2], divisions=4).getroot()
    )
    heads = [head(100 + 10 * i, "C") for i in range(4)] + [head(400, "D"), head(410, "D")]
    for h in heads[4:]:
        h.bar = 3
    multirest = vector.MultiRest(0, 250.0, 2, page=0, bar=1)
    mark = vector.TimeMark(0, 205.0, 2, 4, page=0, bar=1)
    result = vector.expand_multirests(part, _times_pages(heads, [mark], [multirest]))
    assert result.bars == 2
    rest_bars = part.findall("measure")[1:3]
    assert rest_bars[0].findtext("attributes/time/beats") == "2"
    assert [n.findtext("duration") for m in rest_bars for n in m.findall("note")] == ["8", "8"]


def test_a_rest_stretch_the_page_prints_notes_in_is_left_alone():
    bars_ = [note("C", 4, 4) * 4, note("E", 4, 4) * 4, note("D", 4, 4) * 4]
    part = musicxml.first_part(score(bars_, divisions=4).getroot())
    # The E bar's heads are printed (bar 1) but unread by the aligner: no C/D there.
    heads = [head(100 + 10 * i, "C") for i in range(4)]
    heads += [head(300 + 10 * i, "D") for i in range(4)]
    for h in heads[4:]:
        h.bar = 3
    unaligned = head(220.0, "G")
    unaligned.bar = 1
    multirest = vector.MultiRest(0, 250.0, 2, page=0, bar=2)
    pages = _times_pages(heads + [unaligned], [], [multirest])
    result = vector.expand_multirests(part, pages)
    assert result.bars == 0 and "prints notes" in result.changes[0]
    assert len(part.findall("measure")) == 3


def test_a_repeated_signature_is_dropped():
    part = musicxml.first_part(score([note("C", 4, 4) * 4] * 3).getroot())
    musicxml.set_measure_time(part.findall("measure")[1], 4, 4)
    musicxml.set_measure_time(part.findall("measure")[2], 2, 4)
    assert musicxml.drop_redundant_times(part) == 1
    assert musicxml.time_changes(part) == ["bar 3: 2/4"]


# ---------------------------------------------------------------- pairing the two readings


def _with_systems(bars_, breaks, divisions=4):
    """A part whose measures at the given indices start a new system."""
    marked = [
        ('<print new-system="yes"/>' if k in breaks else "") + bar for k, bar in enumerate(bars_)
    ]
    return musicxml.first_part(score(marked, divisions=divisions).getroot())


def test_readings_of_equal_bar_count_pair_by_index():
    part = musicxml.first_part(score([note("C", 4, 4) * 4] * 3).getroot())
    other = musicxml.first_part(score([note("D", 4, 4) * 4] * 3).getroot())
    assert musicxml.pair_measures(part, other) == [(0, 0), (1, 1), (2, 2)]


def test_readings_of_unequal_bar_count_pair_by_system():
    # This reading: systems of 4 and 4 bars. The other took a double bar line for
    # two bars in its first system: 5 and 4. The second systems pair; the first do not.
    part = _with_systems([note("C", 4, 4) * 4] * 8, {4})
    other = _with_systems([note("D", 4, 4) * 4] * 9, {5})
    assert musicxml.pair_measures(part, other) == [(4, 5), (5, 6), (6, 7), (7, 8)]


def test_readings_pair_by_the_printed_bar_when_both_were_aligned_to_the_page():
    part = musicxml.first_part(score([note("C", 4, 4) * 4] * 3).getroot())
    other = musicxml.first_part(score([note("D", 4, 4) * 4] * 4).getroot())
    keys = [(0, 0, 0), (0, 0, 1), (0, 0, 2)]
    other_keys = [(0, 0, 0), None, (0, 0, 1), (0, 0, 2)]  # its bar 2 was split in two
    assert musicxml.pair_measures(part, other, keys, other_keys) == [(0, 0), (1, 2), (2, 3)]


def test_a_merge_takes_a_paired_bar_the_other_reading_fills_across_a_split():
    # Four bars here, the second short; five there with the first split but bar 2 full.
    mine = _with_systems(
        [note("C", 4, 4) * 4, note("C", 4, 4) * 3] + [note("C", 4, 4) * 4] * 2, {2}
    )
    theirs = _with_systems(
        [note("D", 4, 4) * 2] * 2 + [note("D", 4, 4) * 4] + [note("D", 4, 4) * 4] * 2, {3}
    )
    result = musicxml.merge_readings(mine, theirs)
    assert (result.compared, result.taken, result.bars) == (2, 0, [])
    # Nothing pairs in the first system (2 bars against 3); the second system's
    # bars pair and are equal, so nothing is taken. Now make one of ours short.
    mine = _with_systems(
        [note("C", 4, 4) * 4] * 2 + [note("C", 4, 4) * 3, note("C", 4, 4) * 4], {2}
    )
    result = musicxml.merge_readings(mine, theirs)
    assert (result.taken, result.bars) == (1, ["3"])
    assert [n.findtext("pitch/step") for n in mine.findall("measure")[2].findall("note")] == [
        "D"
    ] * 4


# ---------------------------------------------------------------- a scan read again, thinned


def _staff_page(line_px, beam_gap=1, beam_px=6, width=400, height=200):
    """Paper with five staff lines `line_px` thick and two beams `beam_gap` apart below."""
    np = pytest.importorskip("numpy")
    pytest.importorskip("PIL")  # thin_ink hands back a PIL image
    page = np.full((height, width), 255, dtype=np.uint8)
    for k in range(5):
        top = 40 + 12 * k
        page[top : top + line_px, 20 : width - 20] = 0
    beam_top = 120
    page[beam_top : beam_top + beam_px, 100:200] = 0
    second = beam_top + beam_px + beam_gap
    page[second : second + beam_px, 100:200] = 0
    return page


def test_otsu_threshold_splits_ink_from_paper():
    np = pytest.importorskip("numpy")
    gray = np.array([[10] * 50 + [240] * 150], dtype=np.uint8)
    assert 10 <= pdfpages.otsu_threshold(gray) < 240


def test_staff_line_thickness_is_the_median_run_of_inked_rows():
    assert pdfpages.staff_line_thickness(_staff_page(4)) == 4
    assert pdfpages.staff_line_thickness(_staff_page(3)) == 3


def test_thinning_opens_the_gap_between_two_beams_and_keeps_the_staff_lines():
    np = pytest.importorskip("numpy")
    thinned = np.asarray(pdfpages.thin_ink(_staff_page(5)))
    column = thinned[:, 150] < 128
    # the beams were 6 rows with 1 row of paper between: now 4, 3, 4
    beams = column[110:140]
    runs = [len(r) for r in "".join("1" if x else "0" for x in beams).split("0") if r]
    assert runs == [4, 4]
    assert "000" in "".join("1" if x else "0" for x in beams).strip("0")
    assert pdfpages.staff_line_thickness(thinned) == 3  # 5 rows less one at each edge


def test_lines_three_pixels_thick_lose_one_row_and_thinner_pages_are_not_thinned():
    thinned = pdfpages.thin_ink(_staff_page(3))
    assert pdfpages.staff_line_thickness(thinned) == 2
    assert pdfpages.thin_ink(_staff_page(2)) is None


def test_thinned_images_are_written_beside_the_page_and_a_faint_page_keeps_its_own(tmp_path):
    pytest.importorskip("numpy")
    Image = pytest.importorskip("PIL.Image")

    bold, faint = tmp_path / "p001.png", tmp_path / "p002.png"
    Image.fromarray(_staff_page(5)).save(bold)
    Image.fromarray(_staff_page(2)).save(faint)
    out = convert._thinned_images([bold, faint])
    assert out == [tmp_path / "p001_thin.png", faint]
    stamp = out[0].stat().st_mtime
    assert convert._thinned_images([bold, faint]) == out  # reused, not rewritten
    assert out[0].stat().st_mtime == stamp


def test_two_short_bars_that_make_one_are_joined_unless_a_system_breaks_between():
    halves = [note("C", 4, 4) * 2, note("D", 4, 4) * 2, note("E", 4, 4) * 4]
    part = musicxml.first_part(score(halves, divisions=4).getroot())
    assert musicxml.join_short_pairs(part) == 1
    assert [len(m.findall("note")) for m in part.findall("measure")] == [4, 4]
    assert [m.get("number") for m in part.findall("measure")] == ["1", "2"]

    across = [note("C", 4, 4) * 2, '<print new-system="yes"/>' + note("D", 4, 4) * 2]
    part = musicxml.first_part(score(across, divisions=4).getroot())
    assert musicxml.join_short_pairs(part) == 0

    uneven = [note("C", 4, 4) * 3, note("D", 4, 4) * 2]
    part = musicxml.first_part(score(uneven, divisions=4).getroot())
    assert musicxml.join_short_pairs(part) == 0


def _run(steps, duration=4):
    return "".join(note(step, 4, duration) for step in steps)


def test_bars_holding_the_same_notes_pair_whatever_their_neighbours_did():
    # The other reading split bar 2 (D E F G) in two; bars 1 and 3 still pair by their notes.
    mine = musicxml.first_part(score([_run("CDEF"), _run("DEFG"), _run("GFED")]).getroot())
    other = musicxml.first_part(
        score([_run("CDEF"), _run("DE"), _run("FG"), _run("GFED")]).getroot()
    )
    assert musicxml.note_pairs(mine, other) == [(0, 0), (2, 3)]


def test_one_misread_pitch_in_four_still_pairs_two_do_not():
    # A match needs three agreeing notes in a row, so the misread is the bar's last.
    mine = musicxml.first_part(score([_run("CDEF"), _run("GABC")]).getroot())
    one = musicxml.first_part(score([_run("CDEF"), _run("GABD")]).getroot())
    assert (1, 1) in musicxml.note_pairs(mine, one)
    two = musicxml.first_part(score([_run("CDEF"), _run("GAED")]).getroot())
    assert (1, 1) not in musicxml.note_pairs(mine, two)


def test_a_split_bar_is_joined_back_to_the_bar_whose_notes_it_holds():
    # The halves are 2 and 1 beats (one value misread): they do not add up, the notes do.
    mine = musicxml.first_part(score([_run("CDEF"), _run("DEFG"), _run("GFED")]).getroot())
    other = musicxml.first_part(
        score([_run("CDEF"), _run("DE"), note("F", 4, 4) + note("G", 4, 2), _run("GFED")]).getroot()
    )
    assert musicxml.join_to_match(other, mine) == 1
    measures = other.findall("measure")
    assert [m.get("number") for m in measures] == ["1", "2", "3"]
    assert [n.findtext("pitch/step") for n in measures[1].findall("note")] == ["D", "E", "F", "G"]


def test_a_system_of_unequal_bar_counts_pairs_where_the_notes_agree():
    # System 2 has three bars here and four there (bar 5 split): bars 4 and 6 pair by notes.
    bars_mine = [_run("CDEF")] * 3 + [
        '<print new-system="yes"/>' + _run("EFGA"),
        _run("GABC"),
        _run("BCDE"),
    ]
    bars_other = [_run("CDEF")] * 3 + [
        '<print new-system="yes"/>' + _run("EFGA"),
        _run("GA"),
        _run("BC"),
        _run("BCDE"),
    ]
    mine = musicxml.first_part(score(bars_mine).getroot())
    other = musicxml.first_part(score(bars_other).getroot())
    pairs = musicxml.pair_measures(mine, other)
    assert (3, 3) in pairs and (5, 6) in pairs
    assert all(k != 4 for k, _ in pairs)  # the split bar pairs with neither half


# ---------------------------------------------------------------- rest values from the page


def _eighth_rest(duration=6):
    return f"<note><rest/><duration>{duration}</duration><voice>1</voice><type>eighth</type></note>"


def test_a_rest_read_as_an_eighth_takes_the_printed_quarter_and_fills_the_bar():
    # Joy Spring bar 16: six eighths, then the page's quarter rest read as an eighth.
    bars_ = [plain("C", 5, 6, "eighth") * 6 + _eighth_rest(), plain("D", 5, 12, "quarter") * 4]
    part = musicxml.first_part(score(bars_, divisions=12).getroot())
    heads = [head(100 + 10 * i, "C", 5) for i in range(6)] + [
        head(200 + 10 * i, "D", 5) for i in range(4)
    ]
    for h in heads[6:]:
        h.bar = 1
    pages = vector.PrintedPages(
        heads, [], {(0, 0): [190.0]}, None, None, [printed_rest(165, "quarter")]
    )
    result = vector.correct_rests(part, pages)
    assert (result.paired, result.changed) == (1, 1)
    rest_note = part.findall("measure")[0].findall("note")[-1]
    assert rest_note.findtext("duration") == "12" and rest_note.findtext("type") == "quarter"
    assert [b.length for b in musicxml.bars(part)] == [4, 4]
    assert result.changes == ["bar 1: eighth rest printed as a quarter"]


def test_rests_are_left_alone_when_the_counts_differ_or_the_rest_is_in_a_tuplet():
    # Two read rests where the page prints one: no pairing, nothing changed.
    bar = plain("C", 5, 6, "eighth") * 6 + _eighth_rest() * 2
    part = musicxml.first_part(score([bar, plain("D", 5, 48, "whole")], divisions=12).getroot())
    heads = [head(100 + 10 * i, "C", 5) for i in range(6)] + [head(200, "D", 5)]
    pages = vector.PrintedPages(heads, [], {(0, 0): []}, None, None, [printed_rest(165, "quarter")])
    assert vector.correct_rests(part, pages).changed == 0
    # A rest marked as a triplet member keeps the tuplet rule's value.
    triplet_rest = (
        "<note><rest/><duration>4</duration><voice>1</voice><type>eighth</type>"
        "<time-modification><actual-notes>3</actual-notes><normal-notes>2</normal-notes>"
        "</time-modification></note>"
    )
    bar = triplet_rest + plain("C", 5, 4, "eighth") * 2 + plain("C", 5, 12, "quarter") * 3
    part = musicxml.first_part(score([bar], divisions=12).getroot())
    heads = [head(112, "C", 5), head(124, "C", 5)] + [head(140 + 12 * i, "C", 5) for i in range(3)]
    pages = vector.PrintedPages(heads, [], {(0, 0): []}, None, None, [printed_rest(100, "quarter")])
    assert vector.correct_rests(part, pages).changed == 0


def test_a_triplet_number_over_a_line_opening_rest_and_its_own_notehead_is_read():
    # Friend Like Me bar 1: the "3" sits over the eighth rest that opens the
    # group, right above a G notehead, left of the line's first head.
    staff = vector.Staff(bottom=100.0, spacing=5.0, left=0.0, right=600.0)
    g = vector.Printed(x=133.0, y=121.5, staff=0, step=9, kind="head", grace=False)
    heads = [g] + [printed(x, 4) for x in (144, 160)]
    rests = [printed_rest(105, "quarter"), printed_rest(122, "eighth")]
    glyphs = [
        glyph("3", "Inkpen2TextStd", 130, 125, 4, 8),
        glyph("œ", "Inkpen2Std", 130, 119, 6, 5),  # the G's notehead, under the "3"
    ]
    marks = vector.tuplet_marks(glyphs, [staff], heads, rests)
    assert [(m.count, round(m.x)) for m in marks] == [(3, 132)]


def test_a_small_round_glyph_just_right_of_a_rest_is_its_dot():
    staff = vector.Staff(bottom=100.0, spacing=5.0, left=0.0, right=600.0)
    rests = [printed_rest(100, "quarter"), printed_rest(200, "quarter")]
    for r in rests:
        r.y = 110.0
    dot = glyph("™", "Inkpen2SpecialStd", 104.5, 111.0, 2.0, 2.2)  # 1.1 spaces right
    far = glyph("™", "Inkpen2SpecialStd", 214.0, 111.0, 2.0, 2.2)  # 3 spaces right
    head_between = vector.Printed(x=205.0, y=110.0, staff=0, step=4, kind="head", grace=False)
    vector.mark_rest_dots(rests, [dot, far], [staff], [head_between])
    assert [r.dots for r in rests] == [1, 0]


def test_a_printed_dotted_rest_gives_the_read_rest_its_dot():
    # 12/8: a dotted quarter rest read as a dotted half, then three dotted quarters' worth.
    rest_read = "<note><rest/><duration>36</duration><voice>1</voice><type>half</type><dot/></note>"
    bar = rest_read + plain("C", 5, 6, "eighth") * 9
    part = musicxml.first_part(score([bar], divisions=12, time="12/8").getroot())
    heads = [head(120 + 10 * i, "C", 5) for i in range(9)]
    printed_dotted = printed_rest(100, "quarter")
    printed_dotted.dots = 1
    pages = vector.PrintedPages(heads, [], {(0, 0): []}, None, None, [printed_dotted])
    result = vector.correct_rests(part, pages)
    assert result.changes == ["bar 1: half dotted rest printed as a dotted quarter"]
    rest_note = part.find("measure/note")
    assert rest_note.findtext("duration") == "18" and rest_note.findtext("type") == "quarter"
    assert len(rest_note.findall("dot")) == 1
    assert musicxml.bars(part)[0].length == 6


# ---------------------------------------------------------------- octave clefs, key flips, values


def test_an_octave_clef_moves_into_the_pitches_and_the_clef_becomes_plain():
    # Audiveris read a tenor's treble clef as 8vb, and as 8va on a later system.
    bar2 = (
        "<attributes><clef><sign>G</sign><line>2</line>"
        "<clef-octave-change>1</clef-octave-change></clef></attributes>"
        + plain("B", 5, 4, "quarter")
        * 4
    )
    part = musicxml.first_part(score([plain("F", 3, 4, "quarter") * 4, bar2]).getroot())
    ET.SubElement(part.find("measure/attributes/clef"), "clef-octave-change").text = "-1"
    assert musicxml.plain_clefs(part) == 8
    assert [n.findtext("pitch/octave") for n in part.iter("note")] == ["4"] * 8
    assert not list(part.iter("clef-octave-change"))


def _keyed(fifths: int, content: str) -> str:
    return (
        f'<print new-system="yes"/><attributes><key><fifths>{fifths}</fifths></key></attributes>'
        + content
    )


def test_a_key_read_for_one_system_only_is_dropped_and_its_notes_take_the_right_key():
    # Three flats on every system; homr read the second system in C (Stitt's bar 19).
    flipped = (
        plain("B", 4, 4, "quarter")
        + plain("E", 5, 4, "quarter")
        + plain("C", 5, 4, "quarter")
        + note("A", 4, 4, alter=-1)
    )
    bars_ = [plain("C", 5, 16, "whole"), _keyed(0, flipped), _keyed(-3, plain("B", 4, 16, "whole"))]
    part = musicxml.first_part(score(bars_).getroot())
    part.find("measure/attributes/key/fifths").text = "-3"
    assert musicxml.drop_key_flips(part) == ["2"]
    assert [k.findtext("fifths") for k in part.iter("key")] == ["-3"]
    bar2 = part.findall("measure")[1]
    assert [(n.findtext("pitch/step"), n.findtext("pitch/alter")) for n in bar2.iter("note")] == [
        ("B", "-1"),
        ("E", "-1"),
        ("C", None),
        ("A", "-1"),
    ]
    # A key that holds for two systems is a modulation, and stays.
    bars_ = [
        plain("C", 5, 16, "whole"),
        _keyed(0, plain("B", 4, 16, "whole")),
        '<print new-system="yes"/>' + plain("B", 4, 16, "whole"),
        _keyed(-3, plain("B", 4, 16, "whole")),
    ]
    part = musicxml.first_part(score(bars_).getroot())
    part.find("measure/attributes/key/fifths").text = "-3"
    assert musicxml.drop_key_flips(part) == []
    assert [k.findtext("fifths") for k in part.iter("key")] == ["-3", "0", "-3"]


def test_joined_pages_mark_each_later_page_turn_as_a_system_break():
    pages = [score([plain("C", 4, 16, "whole")] * 2), score([plain("D", 4, 16, "whole")] * 2)]
    part = musicxml.first_part(musicxml.concat(pages).getroot())
    marks = [m.find("print") for m in part.findall("measure")]
    assert [mark.get("new-page") if mark is not None else None for mark in marks] == [
        None,
        None,
        "yes",
        None,
    ]
    assert [len(system) for system in musicxml.systems_of(part)] == [2, 2]


def test_on_a_scan_the_nearer_bar_wins_and_an_overrun_is_one_more_miss():
    # Stitt's bar 19: the thinned reading a sixteenth long with 17 notes, the plain one 2.
    sparse = musicxml.first_part(score([plain("D", 5, 1, "32nd") * 2], divisions=8).getroot())
    full = musicxml.first_part(score([plain("C", 5, 2, "16th") * 17], divisions=8).getroot())
    assert musicxml.merge_readings(sparse, full, overfull_first=False).taken == 1
    assert len(sparse.findall("measure/note")) == 17
    # A vector file with no count for the bar keeps overfull-first.
    sparse = musicxml.first_part(score([plain("D", 5, 1, "32nd") * 2], divisions=8).getroot())
    full = musicxml.first_part(score([plain("C", 5, 2, "16th") * 17], divisions=8).getroot())
    assert musicxml.merge_readings(sparse, full).taken == 0


def test_a_taken_bar_keeps_this_readings_system_break():
    mine = score([note("C", 4, 4) * 4, '<print new-system="yes"/>' + note("D", 4, 4) * 5])
    theirs = score([note("C", 4, 4) * 4, note("D", 4, 4) * 4])
    part, other = musicxml.first_part(mine.getroot()), musicxml.first_part(theirs.getroot())
    assert musicxml.merge_readings(part, other).bars == ["2"]
    assert part.findall("measure")[1].find("print").get("new-system") == "yes"


def test_a_bar_is_filled_with_the_values_another_reading_gave_its_notes():
    # Stitt's bar 10: 32nds for 16ths in one reading, the dotted quarter's dot lost in the other.
    run = [("C", 6), ("A", 5), ("E", 5), ("C", 5)]
    dotted = (
        "<note><pitch><step>D</step><octave>5</octave></pitch><duration>12</duration>"
        "<voice>1</voice><type>quarter</type><dot/></note>"
    )
    mine_bar = (
        plain("E", 5, 4, "eighth")
        + _eighth_rest(4)
        + "".join(plain(s, o, 1, "32nd") for s, o in run)
        + dotted
        + _eighth_rest(4)
    )
    their_bar = (
        plain("E", 5, 4, "eighth")
        + _eighth_rest(4)
        + "".join(plain(s, o, 2, "16th") for s, o in run)
        + plain("D", 5, 8, "quarter")
        + _eighth_rest(4)
    )
    full = plain("C", 5, 32, "whole")
    part = musicxml.first_part(score([full, mine_bar, full], divisions=8).getroot())
    other = musicxml.first_part(score([full, their_bar, full], divisions=8).getroot())
    assert musicxml.combine_values(part, [other]) == ["2"]
    bar = part.findall("measure")[1]
    assert [(n.findtext("type"), len(n.findall("dot"))) for n in bar.findall("note")] == [
        ("eighth", 0),
        ("eighth", 0),
        ("16th", 0),
        ("16th", 0),
        ("16th", 0),
        ("16th", 0),
        ("quarter", 1),
        ("eighth", 0),
    ]
    assert musicxml.bars(part)[1].length == 4


def test_combined_values_never_make_or_unmake_a_tuplet():
    # Audiveris's bar 7 there: a rest and a triplet short of the page, it "filled"
    # by reading its one right triplet as plain eighths.
    triplet = (
        "<note><pitch><step>{}</step><octave>5</octave></pitch><duration>4</duration>"
        "<voice>1</voice><type>eighth</type><time-modification><actual-notes>3</actual-notes>"
        "<normal-notes>2</normal-notes></time-modification></note>"
    )
    opening = "".join(plain(s, 4, 6, "eighth") for s in "EFG") + "".join(
        plain(s, 4, 3, "16th") for s in "BAGF"
    )
    mine_bar = opening + "".join(triplet.format(s) for s in "CCB")
    their_bar = opening + "".join(plain(s, 5, 6, "eighth") for s in "CCB")
    full = plain("C", 5, 48, "whole")
    part = musicxml.first_part(score([full, mine_bar, full], divisions=12).getroot())
    other = musicxml.first_part(score([full, their_bar, full], divisions=12).getroot())
    assert musicxml.combine_values(part, [other]) == []
    assert musicxml.bars(part)[1].length == Fraction(7, 2)


def test_combined_values_leave_every_rest_its_value():
    # Punjab bar 44: a quarter rest, a triplet read as three plain eighths, a
    # quarter, a quarter rest; another reading's eighth rest would "fill" it.
    mine_bar = (
        rest(4) + "".join(plain(s, 5, 2, "eighth") for s in "GAB") + note("C", 6, 4) + rest(4)
    )
    their_bar = _eighth_rest(2) + "".join(plain(s, 5, 2, "eighth") for s in "GAB") + note("C", 6, 4)
    their_bar += rest(4)
    full = plain("C", 5, 16, "whole")
    part = musicxml.first_part(score([full, mine_bar, full]).getroot())
    other = musicxml.first_part(score([full, their_bar, full]).getroot())
    assert musicxml.combine_values(part, [other]) == []


# ---------------------------------------------------------------- a scan's tuplet numbers


def _scan_page(notes, digits, height=1000.0):
    staff = {"min_x": 0.0, "max_x": 2000.0, "min_y": 400.0, "max_y": 464.0, "unit": 16.0}
    return {
        "version": scanpage.SEGMENT_VERSION,
        "height": height,
        "staffs": [{**staff, "notes": notes, "bars": [], "digits": digits}],
    }


def test_a_scanned_page_becomes_heads_and_tuplet_numbers():
    # homr's position 1 is a treble staff's bottom line (E4); y turns upward.
    notes = [[100.0, 464.0, 1], [120.0, 408.0, 8]]
    digits = [
        [110.0, 500.0, "3", 0.97],
        [300.0, 500.0, "5", 0.5],
        [400.0, 380.0, "13", 0.9],
        [500.0, 500.0, "A", 0.99],
        [600.0, 500.0, "1", 0.9],
    ]
    printed = scanpage.printed_pages([_scan_page(notes, digits)])
    assert [(h.letter, h.octave, h.y) for h in printed.heads] == [("E", 4, 536.0), ("E", 5, 592.0)]
    assert [(m.count, m.x) for m in printed.marks] == [(3, 110.0), (5, 300.0), (13, 400.0)]


def test_a_thirteen_is_in_the_time_of_eight():
    bar = plain("C", 5, 8, "half") + "".join(plain("D", 5, 1, "16th") for _ in range(13))
    part = musicxml.first_part(score([bar]).getroot())
    heads = [head(100, "C", 5)] + [head(120 + 10 * i, "D", 5) for i in range(13)]
    mark = vector.TupletMark(x=180, y=0, staff=0, count=13, spacing=5.0)
    printed = vector.PrintedPages(heads, [mark], {(0, 0): []}, None, None)
    assert vector.apply_printed_tuplets(part, printed).applied == 1
    assert part.find("measure/note").find("time-modification") is None
    ratio = part.findall("measure/note")[1].find("time-modification")
    assert (ratio.findtext("actual-notes"), ratio.findtext("normal-notes")) == ("13", "8")
    assert musicxml.bars(part)[0].length == 4


def test_a_digit_with_a_letter_beside_it_is_a_chord_symbols():
    # Stats rows as OpenCV gives them: x, y, width, height, area; row 0 the background.
    digit = (100, 50, 12, 24, 150)
    box = (100, 50, 112, 74)
    letter = (70, 56, 30, 18, 200)  # the m of "Cm7", wider than a digit, on its line
    bracket = (40, 56, 30, 10, 70)  # half a tuplet bracket: a thin line and its hook
    stem = (96, 0, 3, 80, 240)  # a stem ending beside the number: far taller
    assert scanpage._beside([(0,) * 5, digit, letter], [1], box, 16.0)
    assert not scanpage._beside([(0,) * 5, digit, bracket, stem], [1], box, 16.0)
