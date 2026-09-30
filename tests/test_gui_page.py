"""The page view: Export's MusicXML engraved to SVG in the app (gui/page.py).

Two layers. The engraving module's own arithmetic (width clamping, the memo)
needs nothing beyond the standard library and runs everywhere. The endpoint
needs the gui group (fastapi, verovio) and skips without it, as every GUI
test does -- CI installs neither.

The one claim the endpoint exists to keep: the page on screen is the page
Export writes, byte for byte, with every one of the listener's choices in it.
"""

import pathlib

import pytest

from swingscribe.config import Config
from swingscribe.gui import page as gui_page
from swingscribe.model import AudioRef, BeatGrid, Document, NoteEvent

SPAN = {"model": "htdemucs_ft", "stem": "other", "start": 1.0, "end": 3.0}


# ── the engraving module, no server ─────────────────────────────────────────


def test_the_width_is_clamped_and_rounded_for_the_memo():
    assert gui_page.page_width(None) == 1000
    assert gui_page.page_width(float("nan")) == 1000
    assert gui_page.page_width(10) == gui_page.MIN_WIDTH_PX
    assert gui_page.page_width(99999) == gui_page.MAX_WIDTH_PX
    # A window dragged a few pixels wider is the same page.
    assert gui_page.page_width(1203) == gui_page.page_width(1190) == 1200


def test_the_page_is_laid_out_for_the_panel_width():
    """Verovio's page width is in its own units: at SCALE percent, the page
    is exactly as many CSS pixels wide as the panel asked for."""
    opts = gui_page.options(1200)
    assert opts["pageWidth"] * gui_page.SCALE / 100 == 1200
    assert opts["pageHeight"] > opts["pageWidth"]  # pages, portrait
    assert opts["svgViewBox"] and opts["svgHtml5"]
    assert opts["footer"] == "none"


class _FakeToolkit:
    """Stands in for verovio.toolkit, counting engravings."""

    engraved = 0

    def setOptions(self, options):  # noqa: N802 - Verovio's name
        self.options = options

    def loadData(self, xml):  # noqa: N802
        return "<score-partwise" in xml

    def getPageCount(self):  # noqa: N802
        return 2

    def renderToSVG(self, page):  # noqa: N802
        type(self).engraved += 1
        return f"<svg data-page='{page}'/>"


def test_the_same_page_is_engraved_once(monkeypatch):
    """A page view refreshes on every edit; an edit that does not change the
    page must not engrave it again."""
    gui_page.clear_memo()
    _FakeToolkit.engraved = 0
    monkeypatch.setattr(gui_page, "_toolkit", _FakeToolkit)
    xml = "<score-partwise/>"
    first = gui_page.render(xml, 1200)
    again = gui_page.render(xml, 1203)  # rounds to the same width
    assert first == again
    assert first[2] == ["<svg data-page='1'/>", "<svg data-page='2'/>"]
    assert _FakeToolkit.engraved == 2  # two pages, once
    wider = gui_page.render(xml, 1600)
    assert wider[0] != first[0]  # a different width is a different layout
    assert _FakeToolkit.engraved == 4
    gui_page.clear_memo()


def test_unreadable_musicxml_is_an_error_not_an_empty_page(monkeypatch):
    gui_page.clear_memo()
    monkeypatch.setattr(gui_page, "_toolkit", _FakeToolkit)
    with pytest.raises(ValueError, match="could not read"):
        gui_page.render("not a score", 1200)


_TINY = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
  <part-list><score-part id="P1"><part-name>Solo</part-name></score-part></part-list>
  <part id="P1"><measure number="1">
    <attributes><divisions>1</divisions><key><fifths>-2</fifths></key>
      <time><beats>4</beats><beat-type>4</beat-type></time>
      <clef><sign>G</sign><line>2</line></clef></attributes>
    <note><pitch><step>C</step><octave>5</octave></pitch><duration>4</duration>
      <type>whole</type></note>
  </measure></part>
</score-partwise>
"""


# ── chord symbols in the view (roadmap O4) ──────────────────────────────────


def _chord_page(text: str, bars: int = 3) -> str:
    """Export's MusicXML for a page of whole notes under these changes."""
    from swingscribe.chords import parse_chart, place
    from swingscribe.model import NotatedBar, NotatedNote, Notation
    from swingscribe.stages.export import to_musicxml

    notation = Notation(
        bars=[
            NotatedBar(
                number=number,
                time_signature=(4, 4),
                notes=[NotatedNote(beat=0.0, duration=4.0, pitch=72, step="C", octave=5)],
            )
            for number in range(1, bars + 1)
        ]
    )
    return to_musicxml(place(parse_chart(text, 4), notation, form_bar=1))


def test_the_view_hands_verovio_only_what_the_file_says_to_print():
    """Verovio 6.3 prints every <degree>, even one marked print-object="no",
    so "E7b9" read "E7b9(♭9)"; and it prints a no-chord's hidden root, so
    "N.C." read "C". The view removes the one and respells the other; the
    file keeps both, as MusicXML and MuseScore want them."""
    xml = _chord_page("| E7b9 | N.C. | C |")
    assert '<degree print-object="no">' in xml and 'root-step text=""' in xml
    shown = gui_page.for_verovio(xml)
    assert "<degree" not in shown
    assert '<numeral-root text="N.C.">' in shown
    assert 'root-step text=""' not in shown
    assert gui_page.for_verovio(_TINY) == _TINY  # a page without chords is untouched


def _harm_texts(svg: str) -> list[str]:
    """The text Verovio drew for each chord symbol, glyphs and all."""
    import re

    texts = []
    for match in re.finditer(r'<g [^>]*class="harm[^"]*"[^>]*>', svg):
        depth, index = 1, match.end()
        while depth:
            opening, closing = svg.find("<g", index), svg.find("</g>", index)
            if opening != -1 and opening < closing:
                depth, index = depth + 1, opening + 2
            else:
                depth, index = depth - 1, closing + 4
        drawn = re.findall(r">([^<>]+)<", svg[match.end() : index])
        texts.append("".join(part.strip() for part in drawn))
    return texts


def test_verovio_prints_each_chord_as_the_listener_spelled_it():
    pytest.importorskip("verovio", reason="gui dependency group not installed")
    gui_page.clear_memo()
    xml = _chord_page("| Cmaj7 . E7b9 . | Am7 D7sus4 | N.C. | G7alt/D |", bars=4)
    _, _, pages = gui_page.render(xml, 1200)
    assert _harm_texts("".join(pages)) == ["Cmaj7", "E7b9", "Am7", "D7sus4", "N.C.", "G7alt/D"]
    gui_page.clear_memo()


def test_a_worker_thread_can_engrave():
    """Verovio's default resource path is set per THREAD by its own import;
    a route runs in a worker thread, where the default is the path of the
    machine that built the wheel. Rendering there must still find the fonts."""
    pytest.importorskip("verovio", reason="gui dependency group not installed")
    import threading

    gui_page.clear_memo()
    out = {}
    worker = threading.Thread(target=lambda: out.update(result=gui_page.render(_TINY, 800)))
    worker.start()
    worker.join()
    _, width, pages = out["result"]
    assert width == 800 and len(pages) == 1
    assert "<svg" in pages[0] and "viewBox" in pages[0]
    gui_page.clear_memo()


# ── the endpoint ────────────────────────────────────────────────────────────


@pytest.fixture
def world(tmp_path, monkeypatch):
    """An opened track with a cached review of three notes and a cached beat
    grid, without running ingest, CREPE or the beat tracker."""
    pytest.importorskip("fastapi", reason="gui dependency group not installed")
    from dataclasses import dataclass

    from fastapi.testclient import TestClient

    from swingscribe.gui import app as gui_app
    from swingscribe.gui import library, review
    from swingscribe.stages.separate import stems_dir

    music = tmp_path / "music"
    music.mkdir()
    source = music / "Some Tune.m4a"
    source.write_bytes(b"pretend this is an m4a")
    # Only ever hashed and checked for: nothing here decodes audio.
    normalized = tmp_path / "cache" / "audio" / "normalized.wav"
    normalized.parent.mkdir(parents=True)
    normalized.write_bytes(b"RIFF pretend")
    config = Config(cache_dir=tmp_path / "cache", gui={"library_dir": str(music)})
    document = Document(
        audio_path=str(source),
        sample_rate=8000,
        audio=AudioRef(path=str(normalized), sample_rate=8000, channels=2, duration=6.0),
    )
    monkeypatch.setattr(library, "ingested_document", lambda path, cfg: document)
    stem_dir = stems_dir(config.cache_dir, library.file_digest(normalized), "htdemucs_ft")
    stem_dir.mkdir(parents=True)
    for name in ("drums", "bass", "other", "vocals"):
        (stem_dir / f"{name}.wav").write_bytes(b"RIFF pretend")

    @dataclass
    class Diag:
        hop_s: float = 0.01
        start: float = 1.0
        f0_midi: list = None
        periodicity: list = None
        energy_ok: list = None
        pitch: list = None
        onsets: list = None
        candidates: list = None

        @property
        def voiced_fraction(self):
            return 1.0

    notes = [
        NoteEvent(
            onset=round(1.1 + 0.5 * i, 3), duration=0.2, pitch=p, confidence=0.8, source="other"
        )
        for i, p in enumerate((64, 67, 71))
    ]
    diag = Diag(f0_midi=[64.0], periodicity=[0.9], energy_ok=[True], pitch=[64.0], onsets=[])
    monkeypatch.setattr("swingscribe.stages.transcribe.analyze", lambda sp, tc: (notes, diag))

    client = TestClient(gui_app.create_app(config))
    track = client.post("/api/tracks/open", json={"path": str(source)}).json()
    span_config = config.model_copy(
        update={
            "transcribe": config.transcribe.model_copy(
                update={"stem": "other", "region": (1.0, 3.0)}
            )
        }
    )
    review.analyze_and_cache(document, span_config, "htdemucs_ft")

    def cached(path, cfg, stages):
        grid = BeatGrid(beats=[i * 0.5 for i in range(13)], downbeats=[], beats_per_bar=4)
        return Document(audio_path=str(path), sample_rate=8000, beat_grid=grid)

    monkeypatch.setattr("swingscribe.pipeline.cached_document", cached)
    gui_page.clear_memo()
    return {"client": client, "track": track, "source": source}


def _page(world, **params):
    return world["client"].get(
        f"/api/tracks/{world['track']['id']}/page", params={**SPAN, **params}
    )


def _state(world, **state):
    response = world["client"].post(
        f"/api/tracks/{world['track']['id']}/state", json={"state": state}
    )
    assert response.status_code == 200, response.text


def _needs_verovio():
    pytest.importorskip("verovio", reason="gui dependency group not installed")


def test_the_page_is_engraved_as_one_svg_per_page(world):
    _needs_verovio()
    response = _page(world, width=910)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"  # the sidecar is not in the URL
    page = response.json()
    assert page["page_count"] == len(page["pages"]) >= 1
    assert all(svg.lstrip().startswith("<svg") and "viewBox" in svg for svg in page["pages"])
    assert page["width"] == 920  # rounded to the memo's 40 px step
    assert page["bars"] >= 1 and page["notes"] == 3
    assert page["name"] == "Some Tune.1-3s.musicxml"


def test_the_page_is_the_file_export_writes(world, monkeypatch):
    """Byte for byte: the view engraves the Export button's own string."""
    _needs_verovio()
    seen = {}
    real = gui_page.render

    def spy(xml, width=None):
        seen["xml"] = xml
        return real(xml, width)

    monkeypatch.setattr(gui_page, "render", spy)
    _state(world, transposition="Eb", timing="literal-16", key=-3)
    shown = _page(world).json()
    written = world["client"].post(f"/api/tracks/{world['track']['id']}/export", params=SPAN).json()
    assert pathlib.Path(written["path"]).read_text(encoding="utf-8") == seen["xml"]
    assert pathlib.Path(written["path"]).name == shown["name"]
    for field in ("bars", "notes", "key_fifths", "key", "timing", "transpose", "time_signature"):
        assert shown[field] == written[field], field


def test_looking_at_the_page_writes_nothing(world):
    """A GET: the file on disk stays whatever Export last put there."""
    _needs_verovio()
    assert _page(world).status_code == 200
    assert not list(world["source"].parent.glob("*.musicxml"))


def test_every_choice_that_changes_the_page_reaches_it(world):
    """The listener's edits and menus are read off the sidecar, as Export
    reads them: each one moves the digest the frontend refreshes on."""
    _needs_verovio()
    first = _page(world).json()
    digests = {first["digest"]}

    _state(world, erasures=[{"onset": 1.6, "pitch": 67, "reason": "not-solo"}])
    silenced = _page(world).json()
    assert silenced["notes"] == first["notes"] - 1
    digests.add(silenced["digest"])

    _state(world, timing="literal-32")
    literal = _page(world).json()
    assert literal["timing"] == "literal-32" and not literal["swing"]
    digests.add(literal["digest"])

    _state(world, key=2)
    keyed = _page(world).json()
    assert keyed["key_fifths"] == 2 and not keyed["key_auto"]
    digests.add(keyed["digest"])

    _state(world, transposition="Bb-tenor")
    tenor = _page(world).json()
    assert tenor["transpose"] == 14
    digests.add(tenor["digest"])
    assert len(digests) == 5


def test_a_page_the_client_already_drew_is_not_sent_again(world):
    _needs_verovio()
    first = _page(world).json()
    again = _page(world, known=first["digest"]).json()
    assert again["unchanged"] and again["pages"] is None
    assert again["digest"] == first["digest"] and again["page_count"] == first["page_count"]
    # A stale digest gets the pages.
    assert _page(world, known="stale").json()["pages"]


def test_the_page_says_which_step_is_still_owed(world, monkeypatch):
    """409 with the fix in the message, as Export's refusals are."""
    monkeypatch.setattr("swingscribe.pipeline.cached_document", lambda p, c, stages: None)
    response = _page(world)
    assert response.status_code == 409
    assert "beats" in response.json()["detail"].lower()
    untranscribed = _page(world, start=2.0)
    assert untranscribed.status_code == 409
    assert "transcribe" in untranscribed.json()["detail"].lower()


def test_a_refused_page_is_given_once_the_cause_is_fixed(world, monkeypatch):
    """The view keeps a refusal's signature and asks again only when the
    listener changes something the page is drawn from (app.js refreshPage):
    not on every click, and never in a loop. That is only correct if the
    server remembers nothing about a refusal -- the SAME request, once the
    cause is fixed, is the page -- and if a refusal engraves nothing."""
    _needs_verovio()
    from swingscribe import pipeline

    with_grid = pipeline.cached_document
    monkeypatch.setattr(pipeline, "cached_document", lambda p, c, stages: None)
    refusals = [_page(world) for _ in range(2)]
    assert [r.status_code for r in refusals] == [409, 409]
    assert "press beats first" in refusals[0].json()["detail"].lower()
    assert refusals[0].json() == refusals[1].json()
    assert not gui_page._memo  # nothing was engraved for a refusal

    monkeypatch.setattr(pipeline, "cached_document", with_grid)  # Beats pressed
    fixed = _page(world)
    assert fixed.status_code == 200, fixed.text
    assert fixed.json()["pages"] and fixed.json()["notes"] == 3

    # The other refusal a listener can cause and undo: every note silenced,
    # then one switched back on.
    everything = [
        {"onset": round(1.1 + 0.5 * i, 3), "pitch": p, "reason": "not-solo"}
        for i, p in enumerate((64, 67, 71))
    ]
    _state(world, erasures=everything)
    silenced = _page(world)
    assert silenced.status_code == 409
    assert "silenced" in silenced.json()["detail"]
    _state(world, erasures=everything[:2])
    restored = _page(world)
    assert restored.status_code == 200, restored.text
    assert restored.json()["notes"] == 1


def test_verovio_is_bounded_to_the_minor_that_was_probed():
    """Smart App Control judges each compiled FILE by reputation, so a Verovio
    release nobody has loaded on the dev machine is not taken on trust
    (pyproject, the same reason torch is pinned <2.13). The lock sits inside
    the bound, so `uv sync` cannot fetch a release the pin excludes."""
    import tomllib

    from packaging.requirements import Requirement

    root = pathlib.Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    gui = [Requirement(r) for r in project["dependency-groups"]["gui"] if isinstance(r, str)]
    (verovio,) = [r for r in gui if r.name == "verovio"]
    assert "6.3.0" in verovio.specifier
    assert "6.4.0" not in verovio.specifier
    lock = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))
    (locked,) = [p["version"] for p in lock["package"] if p["name"] == "verovio"]
    assert locked in verovio.specifier


def test_a_machine_without_verovio_is_told_so_in_json(world, monkeypatch):
    def missing():
        raise gui_page.Unavailable("the page view needs Verovio, which is not installed")

    monkeypatch.setattr(gui_page, "_toolkit", missing)
    response = _page(world)
    assert response.status_code == 501
    assert "Verovio" in response.json()["detail"]


def test_the_changes_reach_the_page_and_say_where_they_landed(world, monkeypatch):
    """The Changes field is a sidecar setting like the key: it moves the
    page's digest, the view engraves the symbols, and the page reports the
    chart's bars as Export does -- one string, one report."""
    _needs_verovio()
    seen = {}
    real = gui_page.render

    def spy(xml, width=None):
        seen["xml"] = xml
        return real(xml, width)

    monkeypatch.setattr(gui_page, "render", spy)
    plain = _page(world).json()
    assert plain["changes"] is None
    _state(world, changes="| Dm7 . G7 . | Cmaj7 |")
    shown = _page(world).json()
    assert shown["digest"] != plain["digest"]
    assert shown["changes"]["bars"] == 2 and shown["changes"]["error"] is None
    assert shown["changes"]["placed"] >= 2
    assert _harm_texts("".join(shown["pages"]))[:2] == ["Dm7", "G7"]
    written = world["client"].post(f"/api/tracks/{world['track']['id']}/export", params=SPAN).json()
    assert pathlib.Path(written["path"]).read_text(encoding="utf-8") == seen["xml"]
    assert written["changes"] == shown["changes"]

    _state(world, changes="| Dm7 | Gxx |")
    broken = _page(world)
    assert broken.status_code == 200, broken.text  # the page is still drawn
    assert broken.json()["changes"]["token"] == "Gxx"
    assert "<harmony" not in seen["xml"]
