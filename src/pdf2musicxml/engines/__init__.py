"""The optical-music-recognition engines the tool can drive.

Two, chosen on measurement (docs/pdf2musicxml.md):

- `homr` (pure Python, ONNX): the default reading. On a scanned page in a
  handwritten jazz font it kept the rests, four of five triplets and every
  tie that Audiveris lost; it has no tie in its vocabulary (they come out as
  slurs, mended in `musicxml.slurs_to_ties`) and reads no chord symbols.
- `audiveris` (Java, bundled runtime): the second opinion, and the better
  reading of a clean notation-program PDF -- ties, chord symbols and the
  title as OCR'd text, at eight seconds a page. Installed on demand into
  the tool's own folder (`pdf2musicxml setup`); never a system install.

Each module exposes `is_installed()` and a `run(...)` that returns the
MusicXML files it wrote, and raises `EngineError` when it wrote none.
"""


class EngineError(RuntimeError):
    """An engine ran and produced nothing usable; the message says where its log is."""


ENGINES = ("homr", "audiveris")
