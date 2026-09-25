"""pdf2musicxml: PDF sheet-music transcriptions in, MusicXML out.

A standalone tool (it imports nothing from swingscribe) that turns the jazz
transcription PDFs found on the internet -- single solos and whole books of
them -- into one MusicXML file per transcription that MuseScore opens. It
exists to build a ground-truth corpus for the swingscribe benchmark, so its
output is judged by one question: how little must a human fix in MuseScore
before the file is a faithful copy of the page?

The recognition itself is delegated to an optical-music-recognition engine
(`engines/`); everything around it -- rasterising pages at a size the engine
likes, finding where one transcription ends and the next begins in a book,
naming the instrument and its transposition, turning an engine's slurs into
the ties they were, and reporting bars that do not add up -- is here.
"""

__version__ = "0.3.20"
