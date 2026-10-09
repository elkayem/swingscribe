"""scripts/multi_horn_page.py: the GUI's Export path from a shell, wired.

The review, the stems, the ingest and the beat grid are stood in for; what
is under test is that the script reads the sidecar the way the page does,
forces the ensemble, and writes the two-horn page through `page_of`.
"""

import json
import sys
from pathlib import Path
from xml.etree import ElementTree

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import multi_horn_page  # noqa: E402

BEAT = 0.5


def payload():
    notes = []
    for i in range(32):
        onset = 2.0 + i * BEAT
        notes.append({"onset": onset, "duration": 0.45, "pitch": 74, "confidence": 0.7, "voice": 1})
        notes.append({"onset": onset, "duration": 0.45, "pitch": 58, "confidence": 0.6, "voice": 2})
    ghost = {"onset": 2.1, "duration": 0.2, "pitch": 86, "confidence": 0.2, "dropped": "ghost"}
    return {"notes": notes, "candidates": [ghost], "second_voice": []}


def stand_in(monkeypatch, tmp_path):
    from swingscribe.gui import library, review
    from swingscribe.gui import musicxml as gui_musicxml
    from swingscribe.model import AudioRef, BeatGrid, Document

    audio = tmp_path / "Open_Sesame.m4a"
    audio.write_bytes(b"")
    document = Document(
        audio_path=str(audio),
        sample_rate=44100,
        audio=AudioRef(path=str(audio), sample_rate=44100, channels=2, duration=30.0),
    )
    grid = BeatGrid(beats=[i * BEAT for i in range(60)], downbeats=[], beats_per_bar=4)
    seen = {}

    def cached_review(document, run_config, model):
        seen["run_config"] = run_config
        seen["model"] = model
        return payload()

    monkeypatch.setattr(library, "ingested_document", lambda path, config: document)
    monkeypatch.setattr(library, "resolve_stem", lambda *a, **k: str(tmp_path / "other.wav"))
    monkeypatch.setattr(review, "cached_review", cached_review)
    monkeypatch.setattr(gui_musicxml, "cached_grid", lambda *a, **k: grid)
    return audio, seen


def test_the_script_writes_a_two_horn_page_from_the_sidecar(monkeypatch, tmp_path, capsys):
    audio, seen = stand_in(monkeypatch, tmp_path)
    sidecar = tmp_path / "sidecar.json"
    sidecar.write_text(
        json.dumps({"anchor": 2.0, "model": "bsroformer_sw", "stem": "other", "ensemble": "trio"})
    )
    out = tmp_path / "page.musicxml"
    voices = tmp_path / "voices.txt"
    code = multi_horn_page.main(
        [
            str(audio),
            "--start",
            "1.5",
            "--end",
            "18.5",
            "--sidecar",
            str(sidecar),
            "--out",
            str(out),
            "--dump-voices",
            str(voices),
        ]
    )
    assert code == 0
    # The ensemble is forced, whatever the sidecar said; the model is its.
    assert seen["run_config"].transcribe.ensemble == "multi-horn"
    assert seen["run_config"].transcribe.region == (1.5, 18.5)
    assert seen["model"] == "bsroformer_sw"
    # The sidecar itself is never written.
    assert json.loads(sidecar.read_text())["ensemble"] == "trio"

    xml = out.read_text(encoding="utf-8")
    root = ElementTree.fromstring(xml[xml.index("<score-partwise") :])
    notes = root.iter("note")
    voiced = {(n.findtext("voice"), n.findtext("stem")) for n in notes if n.find("rest") is None}
    assert ("1", "up") in voiced and ("2", "down") in voiced
    # Two octaves and a major second apart: the lower horn moved up an
    # octave, every phrase at once.
    text = voices.read_text(encoding="utf-8")
    assert "moved +12" in text
    assert "bar   1 v2:" in text or "bar   2 v2:" in text
    printed = capsys.readouterr().out
    assert "1 candidates" in printed
    assert "(swing" in printed
    # Every heard note is on the page.
    assert "voice 1 32 kept, 0 re-attack heads folded, 32 written" in printed
    assert "voice 2 32 kept, 0 re-attack heads folded, 32 written" in printed
    assert "NOT WRITTEN" not in printed


def test_the_accounting_names_a_heard_note_the_page_did_not_write():
    from swingscribe.model import NotatedBar, NotatedNote, Notation, NoteEvent
    from swingscribe.notation import HornLines

    def heard(onset, pitch, voice=1, lead_in=False, duration=0.5):
        return NoteEvent(
            onset=onset, duration=duration, pitch=pitch, confidence=0.7, source="o",
            voice=voice, lead_in=lead_in,
        )  # fmt: skip

    lines = HornLines(
        upper=[heard(0.0, 72, lead_in=True, duration=0.08), heard(0.08, 72), heard(1.0, 74)],
        lower=[heard(0.0, 67, 2), heard(1.0, 65, 2), heard(1.1, 64, 2)],
    )
    bar = NotatedBar(
        number=1,
        time_signature=(4, 4),
        notes=[
            NotatedNote(beat=0.0, duration=2.0, pitch=72),
            NotatedNote(beat=2.0, duration=2.0, pitch=74),
            NotatedNote(beat=0.0, duration=2.0, pitch=67, voice=2),
            NotatedNote(beat=2.0, duration=1.0, pitch=65, voice=2, chord=[64]),
        ],
    )
    counts = multi_horn_page.accounting(lines, Notation(bars=[bar]), fold=True)
    assert counts[1] == {"kept": 3, "heads": 1, "written": 2, "lost": 0}
    assert counts[2] == {"kept": 3, "heads": 0, "written": 3, "lost": 0}
    bar.notes.pop(1)  # the quantizer left the D off
    assert multi_horn_page.accounting(lines, Notation(bars=[bar]), fold=True)[1]["lost"] == 1


def test_the_flags_are_laid_over_the_sidecar_in_memory(tmp_path):
    sidecar = tmp_path / "s.json"
    sidecar.write_text(json.dumps({"anchor": 8.46, "timing": "swing", "region": [0, 67.308]}))
    args = multi_horn_page.parse_args(
        ["x.m4a", "--sidecar", str(sidecar), "--timing", "literal-32", "--lag", "--thirds"]
    )
    settings = multi_horn_page.load_settings(args)
    assert settings["ensemble"] == "multi-horn"
    assert settings["timing"] == "literal-32"
    assert settings["literal_lag"] is True and settings["literal_thirds"] is True
    assert settings["anchor"] == 8.46
    assert multi_horn_page.span_of(args, settings) == (0.0, 67.308)


def test_the_rhythm_and_fold_flags_are_sidecar_keys(tmp_path):
    args = multi_horn_page.parse_args(["x.m4a", "--sidecar", str(tmp_path / "none.json")])
    settings = multi_horn_page.load_settings(args)
    assert "timing" not in settings and "literal_lead_ins" not in settings
    args = multi_horn_page.parse_args(
        ["x.m4a", "--sidecar", str(tmp_path / "none.json"), "--timing", "literal-16", "--no-fold"]
    )
    settings = multi_horn_page.load_settings(args)
    assert settings["timing"] == "literal-16"
    assert settings["literal_lead_ins"] is False
    args = multi_horn_page.parse_args(
        ["x.m4a", "--sidecar", str(tmp_path / "none.json"), "--no-lag"]
    )
    assert multi_horn_page.load_settings(args)["literal_lag"] is False


def test_a_console_that_cannot_print_a_flat_does_not_kill_the_summary(monkeypatch):
    """The Windows console in cp1252: the page was written and the summary
    line naming the key died on its flat sign."""
    import io

    raw = io.BytesIO()
    console = io.TextIOWrapper(raw, encoding="cp1252", newline="\n")
    monkeypatch.setattr(sys, "stdout", console)
    multi_horn_page.tolerant_console()
    print("key B♭ major")
    console.flush()
    assert raw.getvalue() == b"key B? major\n"


def test_a_linked_take_names_its_page(monkeypatch, tmp_path):
    """--sidecar on a linked take: the page is named for the take and lands
    beside its sidecar, as the GUI's Export writes it -- not for the audio."""
    audio, _seen = stand_in(monkeypatch, tmp_path)
    takes = tmp_path / "Multi-Horn"
    takes.mkdir()
    sidecar = takes / "Open_Sesame_Melody.swingscribe.json"
    sidecar.write_text(json.dumps({"audio": "../Open_Sesame.m4a", "anchor": 2.0}))
    code = multi_horn_page.main(
        [str(audio), "--start", "1.5", "--end", "18.5", "--sidecar", str(sidecar)]
    )
    assert code == 0
    (page,) = takes.glob("*.musicxml")
    assert page.name.startswith("Open_Sesame_Melody.")
    xml = page.read_text(encoding="utf-8")
    assert "Open_Sesame_Melody" in xml and "<work-title>Open_Sesame<" not in xml


def test_the_held_ratio_bins_part_a_staccato_note_from_a_held_one():
    from swingscribe.model import NoteEvent
    from swingscribe.notation import HornLines

    def heard(onset, duration, voice=1):
        return NoteEvent(
            onset=onset, duration=duration, pitch=72, confidence=0.7, source="o", voice=voice
        )

    # Two staccato notes at half their 0.24 s gap, a held one at 0.95 of it,
    # and a note 1 s before the next: past the window, not counted.
    upper = [heard(0.0, 0.12), heard(0.24, 0.12), heard(0.48, 0.228), heard(0.72, 0.5)]
    lower = [heard(0.0, 0.5, 2), heard(1.5, 0.5, 2)]
    bins = multi_horn_page.held_ratios(HornLines(upper=upper, lower=lower))
    assert bins[1][5] == 2 and bins[1][9] == 1 and sum(bins[1]) == 3
    assert sum(bins[2]) == 0
