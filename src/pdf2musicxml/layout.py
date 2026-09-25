"""Which pages hold staves, where the first staff sits, and how pages group into transcriptions.

A PDF from the web is one of two things: a single transcription over one or
more pages, or a book of them. Nothing in the file says which, so the pages
are read for the two signs a human uses. A TITLE: on a page with a text
layer, the largest wordy text near the top of the page. And LAYOUT: on a
scan, a title pushes the first staff down the page, while a continuation
page starts its staves near the top under a small running header. Pages
without staves (cover, contents, "how to use this book") belong to nothing
and are dropped -- Audiveris refuses to export a book that holds one.

The grouping is a guess that a manifest beside the output can overrule
(`convert.py`); this module only makes the guess.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pdf2musicxml.pdfpages import TextLine

# "PG. 2", "Page 3", "p.2" in a running header: a continuation page, whatever
# its title line says.
CONTINUATION = re.compile(r"\b(?:pg|page|p)\.?\s*(\d+)\b", re.IGNORECASE)
# A running header of the other kind: the title with the page number in
# front ("2 Strode Rode", "2  Minority") or behind ("The Bird 3").
NUMBERED_HEADER = re.compile(r"^\s*\d{1,3}\s+\S|\S\s+\d{1,3}\s*$")

# A title page's first staff sits at least this much of the page height
# lower than a continuation page's (measured on the ten-solo ebook: 18% on
# its title pages, 9.3% on its continuation pages).
TITLE_DROP = 0.04
# With no continuation page to compare against, a first staff this far down
# the page has a title block above it.
TITLE_ABSOLUTE = 0.12
# A title is set in the top part of the page (measured 4-7% on the corpus).
TITLE_ZONE = 0.15


@dataclass
class PageInfo:
    index: int  # 0-based
    has_staves: bool
    first_staff_top: float | None  # of the page height
    lines: list[TextLine] = field(default_factory=list)
    printed_noteheads: int = 0  # from the text layer's glyph shapes; 0 for a scan

    @property
    def text_lines(self) -> list[TextLine]:
        """Words, not glyphs."""
        return [line for line in self.lines if not line.is_music and line.wordy]

    @property
    def title(self) -> str | None:
        return pick_title(self.lines)

    @property
    def header_lines(self) -> list[TextLine]:
        """Words in the running-header zone, the top 8% of the page."""
        return [line for line in self.text_lines if line.top < 0.08]

    @property
    def continuation(self) -> bool:
        """A running header at the very top of the page names the page, not a new piece."""
        header = self.header_lines
        if any(CONTINUATION.search(line.text) for line in header):
            return True
        # A header that carries a page number, as the biggest words up there.
        return bool(header) and all(NUMBERED_HEADER.search(line.text) for line in header)

    def repeats(self, title: str | None) -> bool:
        """The page's header or title is the current piece's title again (page numbers aside)."""
        if not title:
            return False
        wanted = title_key(title)
        candidates = [line.text for line in self.header_lines]
        if self.title:
            candidates.append(self.title)
        return any(title_key(text) == wanted for text in candidates)

    @property
    def has_text(self) -> bool:
        """A text layer of any kind: a notation program's glyphs count, a scan has none."""
        return bool(self.lines)


def title_key(text: str) -> str:
    """The title with page numbers and case taken out: a running header against a new piece."""
    stripped = re.sub(r"^\s*\d{1,3}\s+|\s+\d{1,3}\s*$", "", text)
    return " ".join(stripped.lower().split())


def staff_top(
    image, threshold: float = 0.6, span: float = 0.7, max_thickness: float = 0.006
) -> float | None:
    """Where the first staff starts, as a fraction of the page height; None if there is none.

    A staff line is a THIN run of rows (under `max_thickness` of the page:
    a few pixels at 300 dpi) that is dark across most of the central `span`
    of the page, and a staff is five of them evenly spaced within a twelfth
    of the page. A line of text is thick and never that dark across the
    width; a beam, a heavy title or a banner is one thick run.
    """
    import numpy as np

    pixels = np.asarray(image)
    height, width = pixels.shape[:2]
    x0, x1 = int(width * (1 - span) / 2), int(width * (1 + span) / 2)
    dark = (pixels[:, x0:x1] < 160).mean(axis=1)
    rows = np.flatnonzero(dark > threshold)
    if rows.size == 0:
        return None
    breaks = np.flatnonzero(np.diff(rows) > 1)
    starts = rows[np.r_[0, breaks + 1]]
    ends = rows[np.r_[breaks, rows.size - 1]]
    thin = [
        (int(start), int(end))
        for start, end in zip(starts, ends, strict=True)
        if end - start + 1 <= max_thickness * height
    ]
    window = height / 12
    for k in range(len(thin) - 4):
        five = thin[k : k + 5]
        if five[-1][0] - five[0][0] > window:
            continue
        gaps = np.diff([start for start, _ in five])
        median = float(np.median(gaps))
        if gaps.min() >= 0.7 * median and gaps.max() <= 1.3 * median:
            return five[0][0] / height
    return None


def pick_title(lines: list[TextLine]) -> str | None:
    """The largest wordy line in the top third of the page, if clearly larger than the rest."""
    words = [line for line in lines if not line.is_music and line.wordy]
    # A title block sits at the top of the page; the large words lower down
    # are a watermark ("TRANSCRIBED BY ... .COM" across the staves) or a
    # performance instruction, never the piece.
    candidates = [line for line in words if line.top < TITLE_ZONE]
    if not candidates:
        return None
    best = max(candidates, key=lambda line: (line.size, -line.top))
    # Measured against the page's other WORDS (the credits, the instrument
    # line), because a page of triplets carries dozens of tuplet "3"s set
    # larger than its credits. A page with no other words -- a continuation
    # page with a running header -- is measured against its bar numbers,
    # which the header ("2  Minority") is set at the size of.
    others = sorted(line.size for line in words if line is not best)
    if len(others) < 2:
        others = sorted(line.size for line in lines if not line.is_music and line is not best)
    if others:
        median = others[len(others) // 2]
        if best.size < 1.4 * median:
            return None
    return best.text


def group_pages(pages: list[PageInfo], *, single: bool = False) -> list[list[int]]:
    """Page indices grouped into transcriptions, in page order.

    Decided page by page. A page with a text layer starts a transcription
    when it carries a title and no "page N" header. A page without one
    starts a transcription when its first staff sits TITLE_DROP lower than
    the highest first staff among the textless pages; and when every
    textless page sits equally low (a book of one-page solos, or a single
    solo with a generous top margin), TITLE_ABSOLUTE decides between
    "each page is one" and "the file is one".
    """
    staffed = [page for page in pages if page.has_staves]
    if not staffed:
        return []
    if single:
        return [[page.index for page in staffed]]
    # A page with a text layer starts a piece only on a title; one whose
    # text is bar numbers and tuplet digits is a continuation page, not a
    # scan, and never falls to the layout rule.
    starts = set()
    current: str | None = None
    for page in staffed:
        if not page.has_text:
            continue
        if page.title and not page.continuation and not page.repeats(current):
            starts.add(page.index)
            current = page.title
    textless = [page for page in staffed if not page.has_text]
    if textless:
        tops = [page.first_staff_top or 0.0 for page in textless]
        base = min(tops)
        if max(tops) - base >= TITLE_DROP:
            starts |= {
                page.index
                for page in textless
                if (page.first_staff_top or 0.0) - base >= TITLE_DROP
            }
        elif base >= TITLE_ABSOLUTE:
            starts |= {page.index for page in textless}
    starts.add(staffed[0].index)
    groups: list[list[int]] = []
    for page in staffed:
        if page.index in starts:
            groups.append([page.index])
        else:
            groups[-1].append(page.index)
    return groups


def parse_split(spec: str, count: int) -> list[list[int]]:
    """ "4-5,6-8,9" (1-based pages, as a reader counts them) -> [[3, 4], [5, 6, 7], [8]]."""
    groups: list[list[int]] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            first, last = (int(x) for x in part.split("-", 1))
        else:
            first = last = int(part)
        if not 1 <= first <= last <= count:
            raise ValueError(f"page range {part!r} is outside 1-{count}")
        groups.append(list(range(first - 1, last)))
    return groups
