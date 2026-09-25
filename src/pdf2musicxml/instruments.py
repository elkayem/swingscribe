"""The instrument a transcription is written for, and what that does to its pitches.

Transcriptions are published in the soloist's written key: a trumpet or
tenor part sounds a major second (or ninth) below what is on the page, an
alto part a major sixth. The benchmark compares concert pitch, so the file
must either say which it is (`<transpose>`, which MuseScore honours) or be
shifted. The instrument is read off the page's own text -- "Alto Saxophone
(Eb)", "Clarinet in Bb", "TRUMPET" -- never guessed from the notes.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Instrument:
    name: str
    chromatic: int  # semitones from written to sounding pitch
    diatonic: int  # staff steps from written to sounding pitch
    octave_change: int = 0

    @property
    def concert(self) -> bool:
        return self.chromatic == 0 and self.diatonic == 0 and self.octave_change == 0

    @property
    def fifths_shift(self) -> int:
        """Fifths from the written key to the sounding one (concert fifths = written + shift)."""
        for fifths in range(-7, 8):
            if (7 * fifths) % 12 == self.chromatic % 12 and (4 * fifths) % 7 == self.diatonic % 7:
                return fifths
        return 0


# Order matters: the first pattern that matches wins, so the specific
# ("bass clarinet", "C trumpet") sit above the general.
PATTERNS: list[tuple[str, Instrument]] = [
    (r"bass\s*clar", Instrument("Bass Clarinet", -14, -8)),
    (
        r"(?:\bc\b|in\s+c)\s*(?:trumpet|tpt)|(?:trumpet|tpt)\s*(?:in|\()\s*c\b",
        Instrument("Trumpet in C", 0, 0),
    ),
    (r"trumpet|\btpt\b|cornet|fl[uü]gel", Instrument("Bb Trumpet", -2, -1)),
    # No "as"/"ts"/"bs" abbreviations: in prose ("as you will notice") they
    # are words, and the credits OCR'd off a scan are prose.
    (r"alto\s*sax|\balto\b|\beb\s*sax", Instrument("Alto Saxophone", -9, -5)),
    (r"bari(?:tone)?\s*sax|\bbari\b", Instrument("Baritone Saxophone", -21, -12)),
    (r"tenor\s*sax|\btenor\b", Instrument("Tenor Saxophone", -14, -8)),
    (r"soprano\s*sax|\bsoprano\b", Instrument("Soprano Saxophone", -2, -1)),
    (r"clarinet\s*(?:in\s*)?\(?\s*a\b|\ba\s*clarinet", Instrument("Clarinet in A", -3, -2)),
    (
        r"(?:\beb\b|e♭)\s*clarinet|clarinet\s*(?:in\s*)?\(?\s*e\s*[b♭]",
        Instrument("Eb Clarinet", 3, 2),
    ),
    (r"clarinet|\bclar\b", Instrument("Bb Clarinet", -2, -1)),
    (r"\btrombone\b|\btbn\b", Instrument("Trombone", 0, 0)),
    (r"\bpiano\b|\bpno\b|\bkeyboard\b", Instrument("Piano", 0, 0)),
    (r"\bguitar\b|\bgtr\b", Instrument("Guitar", 0, 0, octave_change=-1)),
    (r"\bbass\b", Instrument("Bass", 0, 0, octave_change=-1)),
    (r"\bvib(?:e|raphone)s?\b", Instrument("Vibraphone", 0, 0)),
    (r"\bflute\b", Instrument("Flute", 0, 0)),
    (r"\borgan\b", Instrument("Organ", 0, 0)),  # not Lee Morgan's
    (r"\bviolin\b", Instrument("Violin", 0, 0)),
    (r"\bharmonica\b", Instrument("Harmonica", 0, 0)),
]

# "Bb", "B♭", "Eb", "E♭" beside an instrument name settles the key of a horn
# whose name alone does not (a plain "Sax", "Saxophone", "Horn").
KEY_HINT = re.compile(r"\b([abcefg])\s*([b♭#♯])?\b", re.IGNORECASE)


# Words an OCR engine may misspell by a letter or two ("TRUVPET", "Saxophome").
VOCABULARY = (
    "trumpet",
    "saxophone",
    "clarinet",
    "trombone",
    "piano",
    "guitar",
    "flute",
    "vibraphone",
    "tenor",
    "alto",
    "baritone",
    "soprano",
    "cornet",
    "flugelhorn",
    "organ",
    "violin",
)


def normalise(text: str) -> str:
    """Lower-cased, flats spelt, and words within an OCR slip of the vocabulary corrected."""
    words = []
    for word in text.replace("♭", "b").lower().split():
        letters = "".join(c for c in word if c.isalpha())
        if len(letters) >= 4 and letters not in VOCABULARY:
            # Same length only: a substituted letter ("TRUVPET"), never a
            # dropped one, or "Morgan" becomes an organ.
            close = [
                match
                for match in difflib.get_close_matches(letters, VOCABULARY, n=1, cutoff=0.8)
                if len(match) == len(letters)
            ]
            if close:
                word = word.replace(letters, close[0])
        words.append(word)
    return " ".join(words)


def parse_instrument(text: str) -> Instrument | None:
    """The instrument named in one line of text, or None."""
    lowered = normalise(text)
    for pattern, instrument in PATTERNS:
        if re.search(pattern, lowered):
            return instrument
    if re.search(r"\bsax(?:ophone)?\b|\bhorn\b", lowered):
        if re.search(r"\beb\b", lowered):
            return Instrument("Alto Saxophone", -9, -5)
        if re.search(r"\bbb\b", lowered):
            return Instrument("Tenor Saxophone", -14, -8)
    return None


def find_instrument(lines: list[str]) -> Instrument | None:
    """The instrument these lines (a page's text, or OCR'd credits) say the part is written for.

    A PART LABEL -- a short line that is nothing but an instrument name,
    "TRUMPET", "Alto Saxophone (Eb)", "Clarinet in Bb" -- says what the
    page is written for and wins. A longer line ("Dexter Gordon Tenor
    Solo", "Bill Evans - Piano") names who played, which is the same
    instrument on most pages and the wrong one in a book that writes every
    solo for one horn; it is taken only when no label exists.
    """
    labels = [line for line in lines if len(line.split()) <= 3]
    for candidates in (labels, lines):
        for line in candidates:
            instrument = parse_instrument(line)
            if instrument is not None:
                return instrument
    return None
