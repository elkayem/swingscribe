"""The page, shown in the app: Export's MusicXML engraved to SVG by Verovio.

The product's output is a page, and until this view the listener saw it only
after Export, in MuseScore (docs/roadmap.md O1). Two choices shape it:

- **It engraves the exported string, not a second reading of the notes.** The
  caller hands in exactly the MusicXML `gui/musicxml.page_of` produces for the
  Export button, so what is on screen is the file Export would write, byte for
  byte. Nothing here knows what a note is.
- **Server-side, so the frontend stays plain ES modules.** Verovio also ships
  as a WebAssembly build, and taking it would mean the first JavaScript
  dependency the GUI has ever had (docs/gui-design.md: no Node, no npm, no
  bundler). Its Python wheel is one compiled module; it loads under Smart App
  Control on the dev machine (6.3.0, 2026-09-29).

Engraving a solo line is cheap -- 13 to 79 ms over the thirteen scores
exported beside the benchmark audio, at 900 and 1400 px, 1 to 3 pages each --
and a piano texture is not: Billy Boy's All-notes view on two staves (113
bars, 1.6 MB of SVG) takes 0.57 s at 2000 px and 1.07 s at 640 (2026-09-30).
A page view refreshes on every edit, so the result is memoised by content:
the same MusicXML at the same width is the same set of pages, and the request
then costs only the notation build (0.14 s on Birks Works end to end, 0.33 s
on the texture).

Verovio is LGPL-3.0 and imported lazily, like every heavy library here: the
rest of the app, and CI, never need it.
"""

import contextlib
import hashlib
import re
import threading
from collections import OrderedDict
from importlib.resources import files

# Verovio's `scale` is a percentage of its own page unit; at 40 a staff space
# is 7.2 CSS px (a staff 29 px tall), about MuseScore's 100% on a desktop
# screen. The page WIDTH is the panel's, so the layout -- bars per system --
# is laid out for the width it will be read at, not for a sheet of A4.
SCALE = 40
# The width asked for is clamped: narrower than this and a system holds one
# bar; wider and a line of music is too long to read across.
MIN_WIDTH_PX = 480
MAX_WIDTH_PX = 2400
# Widths are rounded to this many pixels before they reach the memo, so a
# window dragged a few pixels wider does not engrave the same page again.
WIDTH_STEP_PX = 40
# A page is as tall as a US Letter sheet is for its width: pages, not one
# scroll, because a page is what the listener will print and hand over.
PAGE_ASPECT = 11 / 8.5
MEMO_SIZE = 16

_lock = threading.Lock()
_memo: OrderedDict[str, list[str]] = OrderedDict()


class Unavailable(Exception):
    """Verovio is not installed, or this machine refused to load it."""


def page_width(width: float | None) -> int:
    """The panel width the page is engraved for, clamped and rounded."""
    if width is None or width != width:  # None or NaN
        width = 1000
    clamped = min(MAX_WIDTH_PX, max(MIN_WIDTH_PX, float(width)))
    return int(round(clamped / WIDTH_STEP_PX) * WIDTH_STEP_PX)


def options(width_px: int) -> dict:
    """Verovio's options for a page `width_px` CSS pixels wide."""
    page_width_units = int(width_px * 100 / SCALE)
    return {
        "scale": SCALE,
        "pageWidth": page_width_units,
        "pageHeight": min(60000, int(page_width_units * PAGE_ASPECT)),
        # The last page is cut to what it holds, not padded to a full sheet.
        "adjustPageHeight": True,
        # A viewBox and no fixed size, so the frontend zooms by CSS width.
        "svgViewBox": True,
        # Element ids become data-id: several pages share one HTML document,
        # and duplicate ids there are an error the browser resolves silently.
        "svgHtml5": True,
        "svgRemoveXlink": True,
        # The title on page 1 is the file's; "Engraved by Verovio" is not ours
        # to print on the listener's page.
        "header": "auto",
        "footer": "none",
        "breaks": "auto",
    }


def digest(xml: str, width_px: int) -> str:
    """The memo key: the page's content and the width it was engraved for."""
    return hashlib.sha256(f"{width_px}\n{xml}".encode()).hexdigest()


def _toolkit():
    try:
        import verovio
    except ImportError as exc:
        raise Unavailable(
            "the page view needs Verovio, which is not installed - "
            "`uv sync` with the gui group, or Export and open the file in MuseScore"
        ) from exc
    except OSError as exc:
        # Smart App Control refuses a compiled module with WinError 4551
        # (CLAUDE.md); say what it was rather than a bare OSError.
        raise Unavailable(f"Windows refused to load Verovio: {exc}") from exc
    # Logging control is a convenience; an older wheel may lack it.
    with contextlib.suppress(Exception):
        verovio.enableLog(verovio.LOG_ERROR)
    toolkit = verovio.toolkit(False)
    # Verovio's DEFAULT resource path is per thread: the wheel's __init__ sets
    # it in whichever thread imported the module, and every other thread gets
    # the path of the machine the wheel was built on
    # (C:/Users/RUNNER~1/.../share/verovio). A FastAPI route runs in a worker
    # thread, so without this every page fails with "Bravura font could not
    # be loaded" -- while the same call from a console works. So the toolkit
    # is built without its default fonts (which would log that error once
    # per page) and pointed at the wheel's own data, every time.
    toolkit.setResourcePath(str(files("verovio") / "data"))
    return toolkit


# A chord symbol's <degree> that its <kind text> already spells (export.
# _append_harmony). MusicXML says a reader does not print it; Verovio 6.3
# prints every degree anyway, in parentheses after the text, so "E7b9"
# came out "E7b9(♭9)" and "C7sus4" "C7sus4(4 no3)". MuseScore reads the
# degrees and prints the chord in its own style; the view shows the text.
_HIDDEN_DEGREE = re.compile(r'<degree print-object="no">.*?</degree>\s*', re.DOTALL)
# N.C. is a harmony of kind "none" whose root is hidden by an empty text,
# the schema's way and the one MuseScore prints as "N.C."; Verovio prints
# the hidden root ("C") and drops the text. Spelled as a <numeral> whose
# root's text is "N.C." it prints exactly that (a <function> it drops
# altogether), so that is how the view hands it over.
_NO_CHORD = re.compile(
    r'<root>\s*<root-step text="">[A-G]</root-step>\s*</root>\s*<kind text="([^"]*)">none</kind>'
)


def for_verovio(xml: str) -> str:
    """The page's MusicXML as Verovio must be handed it to print what the
    file says: every degree the file marks as not printed removed, and a
    no-chord spelled the way Verovio prints. Only chord symbols change, and
    the memo is still keyed by the file's own text."""
    xml = _HIDDEN_DEGREE.sub("", xml)
    return _NO_CHORD.sub(
        r'<numeral><numeral-root text="\1">1</numeral-root></numeral><kind text="">none</kind>', xml
    )


def render(xml: str, width: float | None = None) -> tuple[str, int, list[str]]:
    """Engrave MusicXML to SVG, one string per page.

    Returns (digest, width_px, pages). The digest names the content, so a
    client holding the same one can keep what it already drew -- and its zoom
    and scroll with it.
    """
    width_px = page_width(width)
    key = digest(xml, width_px)
    with _lock:
        cached = _memo.get(key)
        if cached is not None:
            _memo.move_to_end(key)
            return key, width_px, cached
        # One engraving at a time: renders are tens of milliseconds, and
        # Verovio's resource loading is not documented as thread-safe.
        toolkit = _toolkit()
        toolkit.setOptions(options(width_px))
        if not toolkit.loadData(for_verovio(xml)):
            raise ValueError("Verovio could not read the page's MusicXML")
        pages = [toolkit.renderToSVG(page) for page in range(1, toolkit.getPageCount() + 1)]
        if not pages:
            raise ValueError("Verovio engraved no pages")
        _memo[key] = pages
        while len(_memo) > MEMO_SIZE:
            _memo.popitem(last=False)
        return key, width_px, pages


def clear_memo() -> None:
    """Forget every engraved page (tests)."""
    with _lock:
        _memo.clear()
