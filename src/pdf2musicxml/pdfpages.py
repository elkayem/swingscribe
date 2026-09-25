"""PDF pages as images and as text, through pypdfium2.

Two things a page can tell us before any recognition runs. Its TEXT LAYER,
when the PDF came out of a notation program (Finale, Sibelius, MuseScore):
the title, the instrument line and the music glyphs all arrive as characters
with a font name and a size, which is how a title page is told from a
continuation page and "Alto Saxophone (Eb)" from the notes. And its PIXELS,
at a size of our choosing: the engines are picky about resolution, and a
scanned book embedded at 72 dpi on a 15-inch page renders to 30 megapixels
in Audiveris (which refuses it) while a small A5 page renders too coarse.
`render_page` sizes every page the same way, and `write_gray_pdf` wraps the
rendered pages back into a PDF that any engine renders 1:1.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass
from pathlib import Path

# Fonts that carry notation rather than words. A line set in one of these is
# never a title, however large. Sibelius (Opus, Inkpen2, Reprise, Helsinki),
# Finale (Maestro, Engraver, Jazz, Petrucci), MuseScore (Leland, MuseJazz,
# Petaluma, Bravura, Emmentaler/Gonville) and LilyPond (feta) all appear in
# transcription PDFs found on the web.
MUSIC_FONT_MARKERS = (
    "opus",
    "inkpen",
    "reprise",
    "helsinki",
    "maestro",
    "engraver",
    "petrucci",
    "jazz",
    "leland",
    "petaluma",
    "bravura",
    "emmentaler",
    "gonville",
    "gootville",
    "feta",
    "sonata",
    "musicalsymbols",
    "primus",
    "norfolk",
    "broadway",
    "chord",
    "tempo",
    "sebastian",
    "november",
)


# A "Text" or "Script" face is the family's TEXT font: Inkpen2 Script and
# Reprise Text set the titles of Sibelius jazz scores, MuseJazz Text those of
# MuseScore's, Finale's Jazz Text theirs. Opus Text and Engraver Text hold
# notation digits (tuplet numbers, metronome marks) and count as text too,
# harmlessly: nothing set in them is wordy. A "Chords" face is chord symbols.
def is_music_font(name: str) -> bool:
    lowered = name.lower().replace(" ", "")
    if "chord" in lowered:
        return True
    if "text" in lowered or "script" in lowered:
        return False
    return any(marker in lowered for marker in MUSIC_FONT_MARKERS)


def music_family(name: str) -> bool:
    """Any face of a notation family, its Text and Script faces included.

    A metronome mark's beat glyph is set in the TEXT face ("h" in Opus
    Text is a half note), which `is_music_font` counts as text.
    """
    lowered = name.lower().replace(" ", "")
    return any(marker in lowered for marker in MUSIC_FONT_MARKERS)


@dataclass(frozen=True)
class TextLine:
    """One run of characters in one font at one size: a title, a chord, a bar number."""

    text: str
    size: float  # font size in points
    font: str
    top: float  # of the page height, from the top edge
    left: float  # of the page width

    @property
    def is_music(self) -> bool:
        return is_music_font(self.font)

    @property
    def wordy(self) -> bool:
        """Words rather than glyphs: mostly letters and digits, three letters at least."""
        stripped = self.text.strip()
        if sum(c.isalpha() for c in stripped) < 3:
            return False
        plain = sum(c.isalnum() or c in " .,'\"()-&:;!?/" for c in stripped)
        return plain / len(stripped) >= 0.8


def _pdfium():
    import pypdfium2 as pdfium

    return pdfium


def page_count(pdf: Path) -> int:
    return len(_pdfium().PdfDocument(str(pdf)))


def render_page(pdf: Path, index: int, long_side: int = 3300):
    """The page as an 8-bit grayscale PIL image with its long side at `long_side` px.

    3300 is US letter at 300 dpi, the resolution the engines are built for;
    a page's nominal size is ignored because scans lie about theirs.
    """
    doc = _pdfium().PdfDocument(str(pdf))
    page = doc[index]
    width, height = page.get_size()
    scale = long_side / max(width, height)
    return page.render(scale=scale, grayscale=True).to_pil().convert("L")


def page_text(pdf: Path, index: int) -> list[TextLine]:
    """Every text run on the page, music glyphs included (the caller filters).

    Sizes come from pdfium's LOOSE character boxes (the font's full ascent
    to descent), not from `FPDFText_GetFontSize`: Finale writes every glyph
    at size 1 and scales it in the text matrix, Sibelius at hundreds of
    points scaled down. The loose box is in page points whatever the
    producer did. pdfium also inserts a synthetic space (no font, no box)
    between text objects, which is a word break, never a line break.

    Characters are grouped into a line while the font holds and the
    baseline stays within a third of the size; a gap wider than a sixth of
    the size becomes a space. The size is NOT part of the test: a script or
    small-caps face (Inkpen2 Script) sets its capitals larger than its
    lower case within one word, and a line's size is its largest glyph.
    """
    pdfium = _pdfium()
    import pypdfium2.raw as raw

    doc = pdfium.PdfDocument(str(pdf))
    page = doc[index]
    width, height = page.get_size()
    textpage = page.get_textpage()
    count = textpage.count_chars()
    lines: list[TextLine] = []
    buffer: list[str] = []
    font = ""
    size = 0.0
    line_top = line_left = 0.0
    last_right = baseline = 0.0
    pending_space = False

    def flush() -> None:
        text = "".join(buffer).strip()
        if text and font:
            lines.append(TextLine(text, round(size, 1), font, line_top / height, line_left / width))
        buffer.clear()

    for i in range(count):
        char = textpage.get_text_range(i, 1)
        if char in ("\r", "\n"):
            continue
        left, bottom, right, top = textpage.get_charbox(i, loose=True)
        name_buffer = (raw.c_char * 128)()
        raw.FPDFText_GetFontInfo(textpage, i, name_buffer, 128, raw.c_int())
        char_font = name_buffer.value.decode("latin-1", "replace")
        if "+" in char_font[:8]:  # subset prefix: ABCDEF+Maestro
            char_font = char_font.split("+", 1)[1]
        char_size = top - bottom
        if not char_font or char_size <= 0:
            pending_space = True
            continue
        same_line = (
            char_font == font
            and abs(bottom - baseline) <= 0.3 * max(char_size, size)
            and left >= last_right - 1.0 * char_size
        )
        if not same_line:
            flush()
            font, size = char_font, char_size
            line_top, line_left = height - top, left
        else:
            if char != " " and (pending_space or left - last_right > 0.16 * char_size):
                buffer.append(" ")
            if char_size > size:
                size, line_top = char_size, height - top
        buffer.append(char)
        pending_space = False
        last_right, baseline = right, bottom
    flush()
    return lines


def write_gray_pdf(images, path: Path, dpi: int = 300) -> None:
    """Wrap 8-bit grayscale images as a Flate-compressed PDF, one page each.

    Written by hand (forty lines) rather than through Pillow, whose PDF
    writer JPEG-compresses grayscale pages. The page box is sized so that an
    engine rendering at `dpi` gets the pixels back exactly.
    """
    objects: list[bytes] = [b"", b""]  # 1: catalog, 2: pages -- filled at the end
    kids: list[int] = []
    for image in images:
        if image.mode != "L":
            image = image.convert("L")
        width, height = image.size
        data = zlib.compress(image.tobytes(), 6)
        objects.append(
            b"<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /DeviceGray"
            b" /BitsPerComponent 8 /Filter /FlateDecode /Length %d >>\nstream\n"
            % (width, height, len(data))
            + data
            + b"\nendstream"
        )
        image_ref = len(objects)
        page_w, page_h = width * 72.0 / dpi, height * 72.0 / dpi
        content = b"q %.4f 0 0 %.4f 0 0 cm /Im0 Do Q" % (page_w, page_h)
        objects.append(b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream")
        content_ref = len(objects)
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %.4f %.4f]"
            b" /Resources << /XObject << /Im0 %d 0 R >> >> /Contents %d 0 R >>"
            % (page_w, page_h, image_ref, content_ref)
        )
        kids.append(len(objects))
    objects[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[1] = (
        b"<< /Type /Pages /Kids ["
        + b" ".join(b"%d 0 R" % k for k in kids)
        + b"] /Count %d >>" % len(kids)
    )
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    Path(path).write_bytes(bytes(out))
