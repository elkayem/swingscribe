"""The eval harness's track discovery.

Not alignment code, but the same class of harm: a benchmark that scores a
SUBSET without saying so reports a number about less music than it claims.
That has now happened three times — once when a stale grids file made
`wjazz_beat_f1` a mean over 4 beside a note F1 over 11 (R8), and once when
`benchmark/` grew subfolders and two of the three sidecar globs were made
recursive while the third was not, costing every track under
`benchmark/wjazzd/` its beat score and its notation score. The third was
the same harm with the sign flipped: the notes cache is keyed by track name
and only ever added to, so renaming eight tracks left eight orphan entries
behind and every one of them was scored a second time under its old name.

Pure path logic, so it runs in CI with no audio and no ml group.
"""

import contextlib
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

run_eval = pytest.importorskip("run_eval")
score_benchmark = pytest.importorskip("score_benchmark")
wjazz_score = pytest.importorskip("wjazz_score")


def write_sidecar(folder: Path, audio: str, **extra) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / audio).write_bytes(b"not really audio")
    payload = {"file": audio, "region": [0.0, 10.0], "model": "htdemucs", "stem": "other"}
    payload.update(extra)
    path = folder / f"{audio}.swingscribe.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_a_track_in_the_root_keeps_its_bare_name(tmp_path, monkeypatch):
    monkeypatch.setattr(run_eval, "BENCH", tmp_path)
    path = write_sidecar(tmp_path, "Solo.m4a")
    sidecar = json.loads(path.read_text(encoding="utf-8"))
    assert run_eval.sidecar_name(path, sidecar) == "Solo.m4a"


def test_a_track_in_a_subfolder_is_keyed_by_its_path(tmp_path, monkeypatch):
    monkeypatch.setattr(run_eval, "BENCH", tmp_path)
    path = write_sidecar(tmp_path / "wjazzd", "Solo.m4a")
    sidecar = json.loads(path.read_text(encoding="utf-8"))
    # Forward slashes, so a key pinned on Windows matches one pinned anywhere.
    assert run_eval.sidecar_name(path, sidecar) == "wjazzd/Solo.m4a"


def test_two_tracks_of_the_same_name_do_not_collide(tmp_path, monkeypatch):
    monkeypatch.setattr(run_eval, "BENCH", tmp_path)
    a = write_sidecar(tmp_path, "Solo.m4a")
    b = write_sidecar(tmp_path / "wjazzd", "Solo.m4a")
    names = {run_eval.sidecar_name(p, json.loads(p.read_text(encoding="utf-8"))) for p in (a, b)}
    assert len(names) == 2


def test_discover_tunes_finds_a_score_in_a_subfolder(tmp_path):
    (tmp_path / "Hand.mscz").write_bytes(b"pretend")
    write_sidecar(
        tmp_path / "wjazzd",
        "Solo.m4a",
        score=str(tmp_path / "Hand.mscz"),
        ensemble="trio",
    )
    found = score_benchmark.discover_tunes(tmp_path)
    assert len(found) == 1
    audio, mscz_name, _title, instrument = next(iter(found.values()))
    assert audio == "wjazzd/Solo.m4a"
    assert mscz_name == "Hand.mscz"
    assert instrument == "piano"


def test_a_sidecar_without_a_score_is_not_a_benchmark_tune(tmp_path):
    write_sidecar(tmp_path, "Solo.m4a")
    assert score_benchmark.discover_tunes(tmp_path) == {}


# -- the Omnibook set: MusicXML beside the audio, in a subfolder -------------


def test_discover_tunes_takes_a_musicxml_score_beside_its_sidecar(tmp_path):
    """The Omnibook set is LORIA's MusicXML, not .mscz, named like the audio
    and stored in the sidecar by its absolute path (as the GUI stores it) or
    a bare name (as a hand-written sidecar might)."""
    (tmp_path / "Omnibook" / "Confirmation.xml").parent.mkdir()
    (tmp_path / "Omnibook" / "Confirmation.xml").write_text("<score-partwise/>", encoding="utf-8")
    write_sidecar(
        tmp_path / "Omnibook",
        "Confirmation.m4a",
        score=str(tmp_path / "Omnibook" / "Confirmation.xml"),
    )
    found = score_benchmark.discover_tunes(tmp_path)
    assert list(found) == ["omnibook/confirmation"]
    audio, score, _title, instrument = found["omnibook/confirmation"]
    assert audio == "Omnibook/Confirmation.m4a"
    assert score == "Omnibook/Confirmation.xml"
    assert instrument == "horn"

    # The same sidecar naming the score by its bare name finds it beside it.
    write_sidecar(tmp_path / "Omnibook", "Confirmation.m4a", score="Confirmation.xml")
    assert score_benchmark.discover_tunes(tmp_path)["omnibook/confirmation"][1] == (
        "Omnibook/Confirmation.xml"
    )


def test_a_score_outside_benchmark_is_not_a_benchmark_tune(tmp_path):
    """The wjazzd sidecars point at ../wjazz-scores (ODbL, kept out of the
    tree); they were never MuseScore tunes and must not become ones."""
    outside = tmp_path.parent / f"{tmp_path.name}-scores"
    outside.mkdir(exist_ok=True)
    (outside / "Solo.musicxml").write_text("<score-partwise/>", encoding="utf-8")
    write_sidecar(tmp_path / "wjazzd", "Solo.m4a", score=str(outside / "Solo.musicxml"))
    assert score_benchmark.discover_tunes(tmp_path) == {}


def test_a_trailing_take_number_stays_in_the_key():
    """ "02 Confirmation" is Confirmation; "Now's_The_Time_1" and "_2" are two
    recordings and must not fold onto one key."""
    assert score_benchmark.tune_key("02 Confirmation.m4a") == "confirmation"
    assert score_benchmark.tune_key("1-17 Star Eyes.m4a") == "star_eyes"
    assert score_benchmark.tune_key("Now's_The_Time_1.m4a") == "nows_the_time_1"
    assert score_benchmark.tune_key("Now's_The_Time_2.m4a") == "nows_the_time_2"


def test_two_recordings_on_one_key_are_refused_not_folded(tmp_path):
    for name in ("Kim.m4a", "01 Kim.m4a"):
        (tmp_path / "Kim.xml").write_text("<score-partwise/>", encoding="utf-8")
        write_sidecar(tmp_path, name, score=str(tmp_path / "Kim.xml"))
    with pytest.raises(ValueError, match="share the tune key"):
        score_benchmark.discover_tunes(tmp_path)


def test_the_same_tune_in_two_folders_keeps_two_keys():
    """benchmark/Omnibook/ holds Parker's Confirmation and the root holds
    Dexter Gordon's: the key carries the folder so neither shadows the other."""
    assert score_benchmark.tune_key("02 Confirmation.m4a") == "confirmation"
    assert score_benchmark.tune_key("Omnibook/Confirmation.m4a") == "omnibook/confirmation"


def test_the_omnibook_set_is_told_apart_by_its_folder():
    assert run_eval.is_omnibook("Omnibook/Confirmation.m4a")
    assert run_eval.is_omnibook("Omnibook/Confirmation.m4a [line=oracle]")
    assert not run_eval.is_omnibook("Dexter_Gordon_Confirmation.m4a")
    assert not run_eval.is_omnibook("wjazzd/Charlie_Parker_Blues_For_Alice_solo_53.m4a")


def test_the_omnibook_numbers_are_pinned_in_sections_of_their_own():
    """Every existing pin is under mscz/ or notation/; the Omnibook's go
    under omnibook/ and omnibook-notation/, so a reader of the baselines can
    tell the sets apart and the listener's means never absorb the book."""
    card = {
        "wjazz": {},
        "mscz": {"Dexter_Gordon_Confirmation.m4a": {"pitch_f1": 0.8}},
        "notation": {},
        "omnibook": {"Omnibook/Confirmation.m4a": {"pitch_f1": 0.7, "note_f1": 0.5}},
        "omnibook_notation": {
            "Omnibook/Confirmation.m4a": {"rhythm": 0.6, "coverage": 0.7, "trusted": 1.0}
        },
        "summary": {"omnibook_n": 1.0},
    }
    flat = run_eval.flatten(card)
    assert flat["mscz/Dexter_Gordon_Confirmation/pitch_f1"] == 0.8
    assert flat["omnibook/Confirmation/pitch_f1"] == 0.7
    assert flat["omnibook-notation/Confirmation/coverage"] == 0.7
    assert flat["summary/omnibook_n"] == 1.0
    assert not any(key.startswith("mscz/Confirmation") for key in flat)


def test_the_batch_sheet_for_a_subfolder_sits_beside_its_audio():
    benchmark_batch = pytest.importorskip("benchmark_batch")
    root_sheet, root_title = benchmark_batch.sheet_for(benchmark_batch.BENCH_DIR)
    assert root_sheet == benchmark_batch.SHEET_PATH
    assert root_title == "benchmark"
    folder = benchmark_batch.BENCH_DIR / "Omnibook"
    assert benchmark_batch.sheet_for(folder) == (folder / "omnibook_test.xlsx", "omnibook")


def test_every_sidecar_walk_in_the_harness_is_recursive():
    """A structural guard, because the failure it prevents is silent: the run
    still succeeds, it just quietly covers less music than its header claims.
    Both scripts walk the takes through `library.discover`, the one walk, and
    that walk is recursive."""
    from swingscribe.gui import library

    for path in (SCRIPTS / "run_eval.py", SCRIPTS / "score_benchmark.py"):
        source = path.read_text(encoding="utf-8")
        assert '.glob("*.swingscribe.json")' not in source, (
            f"{path.name} walks sidecars with a flat glob; tracks in "
            f"benchmark/ subfolders would be skipped without a word"
        )
        assert "library.discover(" in source
    discover = Path(library.__file__).read_text(encoding="utf-8")
    assert '.rglob(f"*{SETTINGS_SUFFIX}")' in discover


# -- the notes cache must not outlive its tracks ---------------------------


def _cached(sidecar_path: Path, names: list[str]) -> dict:
    """Cache entries that are genuine hits, so transcribe_all never reaches the
    audio -- these tests are about which keys survive, not about decoding."""
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    fingerprint = run_eval.transcribe_fingerprint(sidecar, 0.2, 0.0)
    return {name: {"fingerprint": fingerprint, "notes": []} for name in names}


def test_a_cached_run_whose_track_is_gone_is_not_scored(tmp_path, monkeypatch):
    """Renaming a track leaves its old entry in the notes cache. Everything
    downstream iterates those keys, so the orphan gets scored a second time
    under its old name and the mean is over more tracks than exist."""
    monkeypatch.setattr(run_eval, "BENCH", tmp_path)
    path = write_sidecar(tmp_path / "wjazzd", "New_Name.m4a")
    cache = tmp_path / "notes.json"
    cache.write_text(
        json.dumps(_cached(path, ["wjazzd/Old_Name.m4a", "wjazzd/New_Name.m4a"])), encoding="utf-8"
    )
    runs = run_eval.transcribe_all(cache, step_cost=0.2, dip_db=0.0, log=lambda *_a: None)
    assert set(runs) == {"wjazzd/New_Name.m4a"}


def test_the_orphan_stays_in_the_cache_file(tmp_path, monkeypatch):
    """It cost minutes of CREPE and comes straight back if the rename is
    reverted. It is dropped from what gets SCORED, not from the file."""
    monkeypatch.setattr(run_eval, "BENCH", tmp_path)
    path = write_sidecar(tmp_path / "wjazzd", "New_Name.m4a")
    cache = tmp_path / "notes.json"
    cache.write_text(
        json.dumps(_cached(path, ["wjazzd/Old_Name.m4a", "wjazzd/New_Name.m4a"])), encoding="utf-8"
    )
    run_eval.transcribe_all(cache, step_cost=0.2, dip_db=0.0, log=lambda *_a: None)
    assert "wjazzd/Old_Name.m4a" in json.loads(cache.read_text(encoding="utf-8"))


# -- the notes cache must encode the transcriber, not just its filename ----


def test_the_fingerprint_moves_when_the_routing_moves(tmp_path):
    """`ensemble` routes the piano oracle. Two sidecars that differ only there
    describe different transcriptions and may not share a cached run."""
    horn = {"region": [0.0, 10.0], "model": "htdemucs", "stem": "other", "ensemble": "horn-led"}
    piano = {**horn, "ensemble": "trio"}
    assert run_eval.transcribe_fingerprint(horn, 0.2, 0.0) != run_eval.transcribe_fingerprint(
        piano, 0.2, 0.0
    )


def test_the_fingerprint_moves_when_the_span_moves(tmp_path):
    a = {"region": [0.0, 10.0], "model": "htdemucs", "stem": "other", "ensemble": "horn-led"}
    b = {**a, "region": [0.0, 20.0]}
    assert run_eval.transcribe_fingerprint(a, 0.2, 0.0) != run_eval.transcribe_fingerprint(
        b, 0.2, 0.0
    )


def test_the_fingerprint_moves_when_the_stage_changes_behaviour(monkeypatch):
    """A new step in transcribe with no config change -- the piano gap-fill was
    exactly this -- must still invalidate. The stage's CACHE_VERSION is what
    says so, the same way pipeline._cache_name reads it."""
    from swingscribe.stages import transcribe

    sidecar = {"region": [0.0, 10.0], "model": "htdemucs", "stem": "other", "ensemble": "trio"}
    before = run_eval.transcribe_fingerprint(sidecar, 0.2, 0.0)
    monkeypatch.setattr(transcribe, "CACHE_VERSION", 99, raising=False)
    assert run_eval.transcribe_fingerprint(sidecar, 0.2, 0.0) != before


def test_the_fingerprint_is_stable_for_the_same_settings():
    sidecar = {"region": [0.0, 10.0], "model": "htdemucs", "stem": "other", "ensemble": "trio"}
    assert run_eval.transcribe_fingerprint(sidecar, 0.2, 0.0) == run_eval.transcribe_fingerprint(
        dict(sidecar), 0.2, 0.0
    )


def test_a_run_cached_before_fingerprints_existed_is_recomputed(tmp_path, monkeypatch):
    """No fingerprint means the entry predates this check and there is no way
    to know what produced it. Serving it is the staleness hole."""
    monkeypatch.setattr(run_eval, "BENCH", tmp_path)
    write_sidecar(tmp_path, "Solo.m4a", ensemble="horn-led")
    cache = tmp_path / "notes.json"
    cache.write_text(json.dumps({"Solo.m4a": {"ensemble": "horn-led", "notes": []}}), "utf-8")
    said = []
    # The decision is what is under test. Everything after it needs real audio,
    # so let it fail there -- a cache HIT would have returned before logging
    # anything at all, which is the behaviour being ruled out.
    with contextlib.suppress(Exception):
        run_eval.transcribe_all(cache, step_cost=0.2, dip_db=0.0, log=said.append)
    assert any("re-transcribing" in line for line in said)


def test_a_null_stem_falls_back_to_the_default():
    """A sidecar can carry `stem: null` - the listener never chose one. That is
    not "there is no stem": untreated it reached the filesystem as "None.wav"
    and the track was silently skipped, which nobody saw because a cached run
    kept answering for it (R15)."""
    sidecar = {"region": [0.0, 10.0], "model": "htdemucs", "stem": None, "ensemble": "horn-led"}
    assert run_eval.transcribe_settings(sidecar, 0.2, 0.0).stem == "other"


def test_resolving_a_null_stem_does_not_disturb_a_chosen_one():
    """The fallback must not move the fingerprint of every other track, or
    every cached transcription is thrown away to fix one sidecar."""
    sidecar = {"region": [0.0, 10.0], "model": "htdemucs", "stem": "other", "ensemble": "trio"}
    settings = run_eval.transcribe_settings(sidecar, 0.2, 0.0)
    assert settings.stem == "other"


def test_two_solos_by_one_player_on_one_tune_get_two_names():
    """Joe Henderson takes two solos on In 'n Out (melid 198 and 199), and a
    name built from performer and title alone gave both the same one -- so the
    second overwrote the first and the file disagreed with both the audio and
    the Jazzomat page. 456 solos collapse to 421 such names."""
    first = wjazz_score.score_name("Joe Henderson", "In 'n Out", "", 198)
    second = wjazz_score.score_name("Joe Henderson", "In 'n Out", "", 199)
    assert first != second
    assert first == "Joe_Henderson_In_n_Out_solo_198.musicxml"


def test_an_alternate_take_says_so_in_its_name():
    """`titleaddon` is the human-readable half of the distinction; the melid is
    the half that guarantees it."""
    name = wjazz_score.score_name("John Coltrane", "Body and Soul", "Alternate Take", 219)
    assert "Alternate_Take" in name
    assert name.endswith("_solo_219.musicxml")


def test_the_melid_is_invisible_to_the_gui_name_matcher():
    """`_solo_198` splits into a stopword and a digit, both of which
    `gui/ground_truth` drops. `_solo198` would survive as a token that matches
    no track and dilutes nothing but is still noise in `shared`."""
    from swingscribe.gui import ground_truth

    stem = wjazz_score.score_name("Joe Henderson", "In 'n Out", "", 198)[: -len(".musicxml")]
    assert ground_truth._tokens(stem) == ground_truth._tokens("Joe Henderson In n Out")


# -- a pianist is scored on both lines; the take lives in the run's key ----


def _cached_takes(sidecar_path: Path, names: list[str]) -> dict:
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    out = {}
    for name in names:
        line = run_eval.take_of(name)
        out[name] = {"fingerprint": run_eval.transcribe_fingerprint(sidecar, 0.2, 0.0, line)}
        out[name]["notes"] = []
    return out


def test_a_pianist_gets_a_second_take_and_a_horn_does_not(tmp_path, monkeypatch):
    """The Line picker exists in the GUI, so the harness must score the other
    line too — but only where the picker reads something: a piano model
    asked about a saxophone vouches for nothing."""
    monkeypatch.setattr(run_eval, "BENCH", tmp_path)
    piano = write_sidecar(tmp_path, "Piano.m4a", ensemble="trio", stem="piano")
    horn = write_sidecar(tmp_path, "Horn.m4a")
    cache = tmp_path / "notes.json"
    cached = _cached_takes(piano, ["Piano.m4a", "Piano.m4a [line=crepe]"])
    cached |= _cached_takes(horn, ["Horn.m4a", "Horn.m4a [line=crepe]"])
    cache.write_text(json.dumps(cached), encoding="utf-8")
    runs = run_eval.transcribe_all(cache, step_cost=0.2, dip_db=0.0, log=lambda *_a: None)
    # The horn's stale second-take entry is an orphan like any renamed track's.
    assert set(runs) == {"Piano.m4a", "Piano.m4a [line=crepe]", "Horn.m4a"}


def test_the_second_take_is_the_line_the_default_is_not():
    """Whichever line ships by default, the harness scores the other one
    beside it; a second take equal to the default would measure nothing."""
    from swingscribe.config import LINES, Config

    assert run_eval.SECOND_LINE in LINES
    assert Config().transcribe.piano_line != run_eval.SECOND_LINE


def test_the_take_is_its_own_fingerprint_and_the_default_is_unchanged():
    sidecar = {"file": "P.m4a", "region": [0.0, 10.0], "model": "m", "ensemble": "trio"}
    default = run_eval.transcribe_fingerprint(sidecar, 0.2, 0.0)
    assert run_eval.transcribe_fingerprint(sidecar, 0.2, 0.0, None) == default
    assert run_eval.transcribe_fingerprint(sidecar, 0.2, 0.0, "oracle") == default
    assert run_eval.transcribe_fingerprint(sidecar, 0.2, 0.0, "crepe") != default
    assert run_eval.transcribe_settings(sidecar, 0.2, 0.0, "crepe").piano_line == "crepe"
    # A horn keys the same whatever line is named: it never reads one.
    horn = {"file": "H.m4a", "region": [0.0, 10.0], "model": "m"}
    assert run_eval.transcribe_fingerprint(horn, 0.2, 0.0, "crepe") == (
        run_eval.transcribe_fingerprint(horn, 0.2, 0.0)
    )


def test_the_take_rides_in_the_key_and_the_track_comes_back_out():
    key = run_eval.second_key("wjazzd/Solo.m4a")
    assert key == "wjazzd/Solo.m4a [line=crepe]"
    assert run_eval.track_of(key) == "wjazzd/Solo.m4a"
    assert run_eval.take_of(key) == "crepe"
    assert run_eval.take_of("wjazzd/Solo.m4a") is None
    # A key pinned while the oracle line was the second take still reads.
    assert run_eval.take_of("wjazzd/Solo.m4a [line=oracle]") == "oracle"
    # A file holding several solos keeps its performer suffix after the take.
    assert (
        run_eval.second_key("Two.m4a [Herbie Hancock]") == "Two.m4a [line=crepe] [Herbie Hancock]"
    )
    assert run_eval.track_of("Two.m4a [line=crepe] [Herbie Hancock]") == "Two.m4a"


def test_pinned_names_keep_the_two_takes_apart():
    """`Path(key).stem` folded "X.m4a [line=crepe]" onto "X", so the second
    take would have overwritten the default's pinned numbers."""
    assert run_eval.pin_name("X.m4a") == "X"
    assert run_eval.pin_name("wjazzd/X.m4a") == "X"
    assert run_eval.pin_name("X.m4a [line=crepe]") == "X [line=crepe]"
    assert run_eval.pin_name("X.m4a [Herbie Hancock]") == "X [Herbie Hancock]"


def test_the_summary_means_are_over_the_default_take_and_the_pair_is_paired():
    section = {
        "A.m4a": {"pitch_f1": 0.8},
        "A.m4a [line=crepe]": {"pitch_f1": 0.9},
        "B.m4a": {"pitch_f1": 0.6},  # no second take: a horn, or not yet run
        "C.m4a [line=crepe]": {"pitch_f1": 0.5},  # no default: never paired
    }
    default, second = run_eval.paired_takes(section, "pitch_f1")
    assert (default, second) == ([0.8], [0.9])
    card = {"notation": {"A.m4a": {"readability": 0.9}, "A.m4a [line=crepe]": {"readability": 0.1}}}
    assert list(run_eval.readable_pages(card)) == ["A.m4a"]


def test_every_wjazzd_name_is_unique_over_the_whole_database():
    """The property that matters is over the SET, not the pair: a unique-looking
    scheme that still collides once in 456 loses a solo silently."""
    rows = [
        ("Sonny Rollins", "Blue Seven", "", 379),
        ("Sonny Rollins", "Blue Seven", "", 380),
        ("Sonny Rollins", "Blue Seven", "", 381),
        ("Clifford Brown", "I'll Remember April", "Alternate Take 2", 90),
        ("Clifford Brown", "I'll Remember April", "", 91),
    ]
    names = {wjazz_score.score_name(*row) for row in rows}
    assert len(names) == len(rows)


# -- the page the harness scores is the page the Score button scores (D27) --


def _grid_and_run(beats: list[float], region: list[float]) -> tuple[dict, dict]:
    """One quarter note on every true beat, so every bar is full."""
    grid = {"beats": beats, "downbeats": [], "duration": region[1]}
    run = {
        "notes": [
            {"onset": t, "duration": 0.4, "pitch": 60, "confidence": 1.0}
            for t in beats
            if t < region[1]
        ],
        "region": region,
        "stem": "other",
    }
    return grid, run


def _full_bars(notation) -> dict[int, int]:
    """Bar number -> sounding notes, for the bars that hold any."""
    counts = {bar.number: sum(1 for note in bar.notes if not note.is_rest) for bar in notation.bars}
    return {number: count for number, count in counts.items() if count}


def test_the_harness_notates_on_the_repaired_grid(tmp_path, monkeypatch):
    """A doubled beat left in the grid makes one bar three beats long and
    moves every bar after it (R21). The Score button's page is built on the
    repaired grid; the harness's used to be built on the raw one, so its
    rhythm numbers carried a defect the listener's page did not."""
    monkeypatch.setattr(run_eval, "BENCH", tmp_path)
    write_sidecar(tmp_path, "Solo.m4a", region=[0.0, 20.0], anchor=0.0)
    true_beats = [i * 0.5 for i in range(41)]  # 0 .. 20 s: ten bars of 4/4
    grid, run = _grid_and_run(true_beats, [0.0, 20.0])
    grid["beats"] = sorted(true_beats + [10.25])  # the tracker doubled one
    notation = run_eval.notate_run("Solo.m4a", run, grid)
    assert notation is not None
    full = _full_bars(notation)
    assert set(full) == set(range(1, 11))
    assert set(full.values()) == {4}


def test_the_sidecars_time_signature_reaches_the_harness_page(tmp_path, monkeypatch):
    """One hand score and four WJazzD solos are in 3/4 or 6/4; the harness
    barred every one of them in 4/4 while the Score button did not."""
    monkeypatch.setattr(run_eval, "BENCH", tmp_path)
    write_sidecar(tmp_path, "Waltz.m4a", region=[0.0, 15.0], time_signature="3/4")
    grid, run = _grid_and_run([i * 0.5 for i in range(31)], [0.0, 15.0])
    notation = run_eval.notate_run("Waltz.m4a", run, grid)
    assert notation is not None
    assert {bar.time_signature for bar in notation.bars} == {(3, 4)}
    full = _full_bars(notation)
    assert len(full) == 10
    assert set(full.values()) == {3}


def _fake_tracker(monkeypatch, beats: list[float]):
    from swingscribe.gui import library
    from swingscribe.model import AudioRef, BeatGrid, Document
    from swingscribe.stages import beats as beats_stage

    def fake_ingest(path, config):
        audio = AudioRef(path="x.wav", sample_rate=44100, channels=2, duration=12.5)
        return Document(audio_path=str(path), sample_rate=44100, audio=audio)

    def fake_track(document, config):
        grid = BeatGrid(beats=beats, downbeats=[beats[0]], beats_per_bar=4, source="mix")
        return document.model_copy(update={"beat_grid": grid})

    monkeypatch.setattr(library, "ingested_document", fake_ingest)
    monkeypatch.setattr(beats_stage, "run", fake_track)


def test_a_grid_cached_without_its_length_is_backfilled(tmp_path, monkeypatch):
    """Grids cached before D27 hold beats only. The repaired bar grid also
    wants the downbeat layer and the track's length, so such an entry is
    tracked once more -- and keeps the beats the pinned numbers stand on."""
    monkeypatch.setattr(run_eval, "BENCH", tmp_path)
    write_sidecar(tmp_path, "Solo.m4a")
    cache = tmp_path / "grids.json"
    cache.write_text(
        json.dumps({"Solo.m4a": {"beats": [0.0, 0.5, 1.0], "source": "mix"}}), encoding="utf-8"
    )
    _fake_tracker(monkeypatch, [0.0, 0.5, 1.0])
    grids = run_eval.beat_grids(cache, log=lambda *_a: None)
    expected = {"beats": [0.0, 0.5, 1.0], "downbeats": [0.0], "duration": 12.5, "source": "mix"}
    assert grids["Solo.m4a"] == expected
    assert json.loads(cache.read_text(encoding="utf-8"))["Solo.m4a"] == expected


def test_a_re_tracked_grid_that_disagrees_keeps_the_cached_beats(tmp_path, monkeypatch):
    """The pinned numbers stand on the cached beats. A tracker that no longer
    reproduces them is reported, not silently adopted."""
    monkeypatch.setattr(run_eval, "BENCH", tmp_path)
    write_sidecar(tmp_path, "Solo.m4a")
    cache = tmp_path / "grids.json"
    cache.write_text(
        json.dumps({"Solo.m4a": {"beats": [0.0, 0.5, 1.0], "source": "mix"}}), encoding="utf-8"
    )
    _fake_tracker(monkeypatch, [0.0, 0.6, 1.2])
    said = []
    grids = run_eval.beat_grids(cache, log=said.append)
    assert grids["Solo.m4a"] == {
        "beats": [0.0, 0.5, 1.0],
        "downbeats": [],
        "duration": 12.5,
        "source": "mix",
    }
    assert any("keeping the cached grid" in line for line in said)


def test_parallel_map_is_a_map_in_order_at_any_job_count():
    """The per-track scorers are pure functions of their task tuple, so the
    pool can only change the wall clock, never the card. One job is an
    in-process map; more than one goes through a process pool and must
    come back in the same order."""
    keys = ["A.m4a [line=crepe]", "B.m4a", "wjazzd/C.m4a [Bird]"]
    expected = [run_eval.pin_name(k) for k in keys]
    assert run_eval.parallel_map(run_eval.pin_name, keys, 1) == expected
    assert run_eval.parallel_map(run_eval.pin_name, keys, 2) == expected
    assert run_eval.parallel_map(run_eval.pin_name, [], 4) == []
    assert 1 <= run_eval.default_jobs() <= 4


# -- the PDF pages, the locked split, the paired table (docs/roadmap.md E1-E3) --


def test_the_pages_are_their_own_located_set():
    assert run_eval.is_page("Transcriptions_Other/musicxml/Cheese Cake.m4a")
    assert run_eval.is_page("Transcriptions_Other/musicxml/Celia.m4a [line=crepe]")
    assert not run_eval.is_page("Omnibook/Confirmation.m4a")
    assert run_eval.is_located("Omnibook/Confirmation.m4a")
    assert run_eval.is_located("Transcriptions_Other/musicxml/Cheese Cake.m4a")
    assert not run_eval.is_located("wjazzd/Dexter_Gordon_Cheese_Cake_solo_121.m4a")
    assert not run_eval.is_located("Art_Pepper_Birks_Works.m4a")


def test_the_page_numbers_are_pinned_in_sections_of_their_own():
    card = {
        "wjazz": {},
        "mscz": {},
        "notation": {},
        "pages": {"Transcriptions_Other/musicxml/Celia.m4a": {"pitch_f1": 0.7, "silver": 1.0}},
        "pages_notation": {
            "Transcriptions_Other/musicxml/Celia.m4a": {"rhythm": 0.6, "trusted": 1.0}
        },
        "summary": {},
    }
    flat = run_eval.flatten(card)
    assert flat["pages/Celia/pitch_f1"] == 0.7
    assert flat["pages/Celia/silver"] == 1.0
    assert flat["pages-notation/Celia/rhythm"] == 0.6


def test_located_summary_keeps_the_omnibook_keys_and_splits_the_tiers():
    rows = {
        "Omnibook/A.m4a": {"pitch_f1": 0.8, "note_f1": 0.5},
        "Omnibook/B.m4a": {"pitch_f1": 0.6, "note_f1": 0.3},
    }
    notation = {
        "Omnibook/A.m4a": {"rhythm": 0.7, "value": 0.6, "trusted": 1.0, "readability": 0.99},
        "Omnibook/B.m4a": {"rhythm": 0.1, "value": 0.1, "trusted": 0.0, "readability": 0.97},
    }
    s = run_eval.located_summary(rows, notation, "omnibook")
    assert s["omnibook_pitch_f1"] == 0.7 and s["omnibook_n"] == 2.0
    # Rhythm and value over the trusted pairing only; readability over both.
    assert (s["omnibook_rhythm"], s["omnibook_value"], s["omnibook_rhythm_n"]) == (0.7, 0.6, 1.0)
    assert s["omnibook_readability"] == 0.98 and s["omnibook_readability_n"] == 2.0
    # A pianist's second take never enters a mean.
    rows["Omnibook/A.m4a [line=crepe]"] = {"pitch_f1": 0.0, "note_f1": 0.0}
    assert run_eval.located_summary(rows, notation, "x")["x_pitch_f1"] == 0.7
    assert run_eval.tier_of({"silver": 1.0}) == "silver"
    assert run_eval.tier_of({"silver": 0.0}) == run_eval.tier_of({}) == "bronze"


def _split_file(tmp_path, dev):
    path = tmp_path / "split.json"
    path.write_text(json.dumps({"salt": "test-salt", "test_share": 0.5, "dev": dev}))
    return path


def test_an_ordinary_run_holds_the_test_split_out_and_says_so(tmp_path, monkeypatch):
    from swingscribe.evaluation import load_split

    monkeypatch.setattr(run_eval, "BENCH", tmp_path)
    split_path = _split_file(tmp_path, ["Old Tune"])
    monkeypatch.setattr(run_eval, "SPLIT_FILE", split_path)
    split = load_split(split_path)
    # Find one new title on each side of this salt's hash.
    titles = [f"New Tune {i}" for i in range(40)]
    test_title = next(t for t in titles if split.is_test(t))
    dev_title = next(t for t in titles if not split.is_test(t))
    runs = {}
    for title in ("Old Tune", test_title, dev_title):
        audio = title.replace(" ", "_") + ".m4a"
        write_sidecar(tmp_path, audio)
        runs[audio] = {"notes": []}
    runs["Old_Tune.m4a [line=crepe]"] = {"notes": []}
    said = []
    dev = run_eval.split_runs(runs, None, test=False, log=said.append)
    held = test_title.replace(" ", "_") + ".m4a"
    assert held not in dev
    assert {"Old_Tune.m4a", "Old_Tune.m4a [line=crepe]"} <= set(dev)
    assert any("held out: 1" in line for line in said)
    assert set(run_eval.split_runs(runs, None, test=True, log=said.append)) == {held}


def test_a_missing_split_file_holds_nothing_out(tmp_path, monkeypatch):
    monkeypatch.setattr(run_eval, "SPLIT_FILE", tmp_path / "absent.json")
    runs = {"A.m4a": {"notes": []}}
    assert run_eval.split_runs(runs, None, test=False, log=lambda _m: None) == runs
    assert run_eval.split_runs(runs, None, test=True, log=lambda _m: None) == {}


def test_a_track_with_any_dev_name_stays_dev(tmp_path):
    from swingscribe.evaluation import Split

    # A WJazzD file known by its stem when the run has no database and by its
    # title when it has one: either name on the dev list keeps it dev.
    split = Split("s", 1.0, frozenset({"dextergordoncheesecakesolo121"}))
    sidecar = {"melid": 121}
    assert not run_eval.held_out("wjazzd/Dexter_Gordon_Cheese_Cake_solo_121.m4a", sidecar, split)
    assert run_eval.held_out("wjazzd/Someone_Else_solo_9.m4a", {}, split)


def test_the_paired_table_pairs_tracks_by_recording_and_skips_what_it_must():
    # evaluation.paired_change resamples with numpy, which CI does not install.
    pytest.importorskip("numpy")
    before = {
        "wjazz/So_What [Miles Davis]/note_f1": 0.80,
        "wjazz/So_What [John Coltrane]/note_f1": 0.70,
        "wjazz/Walkin/note_f1": 0.90,
        "wjazz/Walkin [line=crepe]/note_f1": 0.10,
        "omnibook-notation/A/rhythm": 0.70,
        "omnibook-notation/A/trusted": 1.0,
        "omnibook-notation/B/rhythm": 0.20,
        "omnibook-notation/B/trusted": 0.0,
        "wjazz/Walkin/tempo": 128.0,
        "summary/wjazz_note_f1": 0.8,
    }
    after = dict(before)
    after.update(
        {
            "wjazz/So_What [Miles Davis]/note_f1": 0.85,
            "wjazz/So_What [John Coltrane]/note_f1": 0.75,
            "wjazz/Walkin [line=crepe]/note_f1": 0.99,
            "omnibook-notation/B/rhythm": 0.90,
            "summary/wjazz_note_f1": 0.9,
        }
    )
    changes = {(s, f): c for s, f, c in run_eval.paired_changes(before, after)}
    # The second take and the untrusted page are not in any row; a set where
    # nothing trusted moved has no row at all; a non-headline field neither.
    assert set(changes) == {("wjazz", "note_f1")}
    c = changes[("wjazz", "note_f1")]
    assert (c.n, c.recordings) == (3, 2)
    assert (c.up, c.level, c.down) == (1, 1, 0)
    assert c.mean == pytest.approx(0.1 / 3)


def test_a_comparison_against_another_card_informs_and_does_not_fail(capsys):
    pytest.importorskip("numpy")  # the paired table's resampling
    card = {
        "wjazz": {"A.m4a": {"note_f1": 0.9}, "B.m4a": {"note_f1": 0.8}},
        "mscz": {},
        "summary": {},
    }
    other = {"wjazz/A/note_f1": 0.8, "wjazz/B/note_f1": 0.8}
    assert run_eval.compare(card, pinned=other) == 0
    out = capsys.readouterr().out
    assert "Against the other card: CHANGED" in out
    assert "Paired changes" in out and "wjazz / note_f1" in out


def test_the_figure_prior_build_leaves_the_test_pages_out(tmp_path):
    import importlib.util

    spec = importlib.util.spec_from_file_location("figure_prior", SCRIPTS / "figure_prior.py")
    fp = sys.modules.get("figure_prior")
    if fp is None:
        fp = importlib.util.module_from_spec(spec)
        sys.modules["figure_prior"] = fp
        spec.loader.exec_module(fp)
    from swingscribe.evaluation import load_split

    split_path = _split_file(tmp_path, [])
    split = load_split(split_path)
    titles = [f"Page {i}" for i in range(40)]
    corpus = [
        fp.Transcription(Path(f"{t}.musicxml"), t, "?", None, [], {"title": t}) for t in titles
    ]
    kept = fp.without_test_pages(corpus, split_path, log=lambda _m: None)
    assert [t.name for t in kept] == [t for t in titles if not split.is_test(t)]
    assert 0 < len(kept) < len(corpus)
    assert fp.without_test_pages(corpus, tmp_path / "absent.json", log=lambda _m: None) == corpus


# -- edit cost, confidence, strata, the OMR step check (docs/roadmap.md E4-E6) --


def _edit_row(cost, trusted=1.0):
    row = dict.fromkeys(run_eval.EDIT_KEYS, 0.0)
    row.update(edit_cost=cost, edit_deletions=cost, trusted=trusted)
    return row


def test_the_edit_cost_mean_is_over_trusted_default_pages():
    """A wrong take is every note deleted and inserted: its edit cost is not
    a reader's effort, so it is kept out of the mean exactly as its rhythm is."""
    rows = {
        "Omnibook/A.m4a": _edit_row(30.0),
        "Omnibook/B.m4a": _edit_row(90.0, trusted=0.0),
        "Omnibook/A.m4a [line=crepe]": _edit_row(10.0),
        "Omnibook/C.m4a": {"rhythm": 0.5, "trusted": 1.0},  # scored before E4
    }
    s = run_eval.edit_summary(rows, "omnibook")
    assert s["omnibook_edit_cost"] == 30.0 and s["omnibook_edit_n"] == 1.0
    assert s["omnibook_edit_deletions"] == 30.0
    assert run_eval.edit_summary({}, "x") == {}
    # A listener's row carries no `trusted`: its span was drawn by ear.
    assert run_eval.edit_summary({"A.m4a": _edit_row(20.0) | {"trusted": 1.0}}, "mscz")


def test_the_edit_cost_is_pinned_and_a_trusted_headline():
    card = {
        "wjazz": {},
        "mscz": {},
        "notation": {"A.m4a": _edit_row(25.0) | {"trace": "bars 1-9 on the bar"}},
        "erasures": {"A.m4a": {"erasures": 10.0, "matched": 8.0, "conf_auc": 0.8}},
        "erasure_means": {"erasure_conf_auc": 0.8, "erasure_matched": 8.0},
        "strata": {"wjazz": {"style": {"BEBOP": {"note_f1": 0.9, "note_f1_n": 3.0}}}},
        "summary": {},
    }
    flat = run_eval.flatten(card)
    assert flat["notation/A/edit_cost"] == 25.0
    assert not any(key.startswith("strata") for key in flat)  # E6 is never pinned
    # The erasures are the listener's LIVE labels: one erased note in the GUI
    # must not fail the next run with no code change.
    assert not any("erasure" in key for key in flat)
    assert "edit_cost" in run_eval.HEADLINE_FIELDS and "edit_cost" in run_eval.TRUSTED_FIELDS
    assert "edit_cost" in run_eval.LOWER_IS_BETTER


def test_the_edit_split_is_averaged_and_read_as_three_blocks():
    """Hearing, notation beside a hearing edit, notation alone: the split is a
    part of position and value, so the three blocks and the bar sum to the
    cost."""
    row = _edit_row(40.0) | {
        "edit_insertions": 5.0,
        "edit_deletions": 5.0,
        "edit_position": 10.0,
        "edit_value": 20.0,
        "edit_position_beside": 4.0,
        "edit_value_beside": 11.0,
        "edit_beside_share": 0.25,
    }
    s = run_eval.edit_summary({"A.m4a": row}, "mscz")
    assert s["mscz_edit_value_beside"] == 11.0 and s["mscz_edit_beside_share"] == 0.25
    blocks = run_eval.edit_blocks(s, "mscz")
    assert blocks == {"hearing": 10.0, "beside": 15.0, "notation": 15.0, "bar": 0.0}
    assert sum(blocks.values()) == s["mscz_edit_cost"]
    # A row scored before the split leaves the split out of the mean.
    old = run_eval.edit_summary({"A.m4a": _edit_row(40.0)}, "mscz")
    assert "mscz_edit_value_beside" not in old and run_eval.edit_blocks(old, "mscz") is None


def test_the_paired_table_says_which_way_is_better_for_the_edit_cost(capsys):
    pytest.importorskip("numpy")  # paired_change's resampling
    from swingscribe.evaluation import paired_change

    change = paired_change([50.0, 60.0, 55.0], [45.0, 52.0, 50.0], ["a", "b", "c"])
    run_eval.print_paired([("notation", "edit_cost", change), ("notation", "rhythm", change)])
    out = capsys.readouterr().out
    assert "notation / edit_cost (v)" in out and "notation / rhythm (v)" not in out
    assert "lower is better" in out


def test_the_confidence_mean_is_over_the_default_take_rows_that_have_one():
    rows = {
        "A.m4a": {"conf_auc": 0.8, "fp_low10": 0.3, "fp_low20": 0.5},
        "B.m4a": {"conf_auc": 0.6, "fp_low10": 0.1, "fp_low20": 0.3},
        "B.m4a [line=crepe]": {"conf_auc": 0.0, "fp_low10": 0.0, "fp_low20": 0.0},
        "C.m4a": {"note_f1": 1.0},  # no false positive: no ranking
    }
    s = run_eval.confidence_summary(rows, "wjazz", ("fp_low10", "fp_low20"))
    assert s == {
        "wjazz_conf_auc": 0.7,
        "wjazz_fp_low10": 0.2,
        "wjazz_fp_low20": 0.4,
        "wjazz_conf_n": 2.0,
    }


def test_the_erasure_mean_weighs_every_matched_erasure_once():
    """One erased note on one track must not count as much as 120 on
    another. Weighted by the matched count, a share is the pooled share."""
    rows = {
        "A.m4a": {"matched": 1.0, "conf_auc": 1.0, "erased_low10": 1.0, "erased_low20": 1.0},
        "B.m4a": {"matched": 3.0, "conf_auc": 0.6, "erased_low10": 0.0, "erased_low20": 1 / 3},
    }
    s = run_eval.confidence_summary(rows, "e", ("erased_low10", "erased_low20"), weight="matched")
    assert s["e_conf_auc"] == pytest.approx(0.7)
    assert s["e_erased_low10"] == pytest.approx(0.25)  # 1 of the 4 erasures
    assert s["e_erased_low20"] == pytest.approx(0.5)  # 2 of the 4
    assert s["e_conf_n"] == 2.0


def test_erasures_are_matched_by_content_on_the_line_view_only(tmp_path, monkeypatch):
    """A re-transcription renumbers every note, so an index would silence --
    and here, score -- a different note (CLAUDE.md). An erasure made on the
    All-notes view is a judgement about a different page and is left out."""
    monkeypatch.setattr(run_eval, "BENCH", tmp_path)
    notes = [
        {"onset": 1.0 + 0.5 * i, "duration": 0.4, "pitch": 60 + i, "confidence": c}
        for i, c in enumerate([0.2, 0.9, 0.8, 0.3, 0.95, 0.85])
    ]
    today = {"model": "bsroformer_sw", "stem": "piano"}
    erased = [
        {"onset": 1.01, "pitch": 60, **today},  # note 0, 10 ms off: the same note
        {"onset": 2.49, "pitch": 63, "model": "htdemucs_ft", "stem": "other"},  # note 3
        {"onset": 3.0, "pitch": 70, **today},  # nothing at that pitch: in span, unmatched
        {"onset": 1.5, "pitch": 61, "piano_notes": "all"},  # the other view
        {"onset": 30.0, "pitch": 61, **today},  # out of the span: not counted anywhere
    ]
    write_sidecar(tmp_path, "Solo.m4a", erasures=erased)
    runs = {"Solo.m4a": {"notes": notes, "region": [0.0, 10.0], **today}}
    rows = run_eval.erasure_scores(runs)
    entry = rows["Solo.m4a"]
    assert (entry["erasures"], entry["matched"], entry["notes"]) == (3.0, 2.0, 6.0)
    # Made on the run's own stems: two in span, one of which still matches.
    assert (entry["same_stems"], entry["same_matched"]) == (2.0, 1.0)
    # The two erased notes are the two least confident: a perfect ranking.
    assert entry["conf_auc"] == 1.0
    means = run_eval.erasure_means(rows)
    assert means["erasure_erasures"] == 3.0 and means["erasure_same_matched"] == 1.0
    assert means["erasure_conf_auc"] == 1.0
    write_sidecar(tmp_path, "Plain.m4a")
    runs["Plain.m4a"] = {"notes": notes, "region": [0.0, 10.0]}
    assert "Plain.m4a" not in run_eval.erasure_scores(runs)


def test_the_confidence_flags_must_reproduce_the_note_precision_or_the_run_stops():
    """`wjazz_confidence` re-derives score()'s span to get at the notes it
    scored; if that ever drifts from score() the flags would describe other
    false positives, silently. The precision beside them is the check."""
    np = pytest.importorskip("numpy")
    pytest.importorskip("mir_eval")

    solo = {
        "ref_on": np.array([1.0, 2.0, 3.0]),
        "ref_p": [60, 62, 64],
        "rate": 1.0,
        "offset": 0.0,
        "performer": "Test Player",
    }
    notes = [
        {"onset": 1.0, "duration": 0.4, "pitch": 60, "confidence": 0.9},
        {"onset": 2.0, "duration": 0.4, "pitch": 62, "confidence": 0.8},
        {"onset": 2.5, "duration": 0.2, "pitch": 70, "confidence": 0.1},  # a false positive
        {"onset": 3.0, "duration": 0.4, "pitch": 64, "confidence": 0.7},
        {"onset": 9.0, "duration": 0.4, "pitch": 64, "confidence": 0.0},  # outside the span
    ]
    onsets = np.array([n["onset"] for n in notes])
    ranking = run_eval.wjazz_confidence(solo, onsets, notes, 3 / 4)
    assert (ranking.n, ranking.flagged, ranking.auc) == (4, 1, 1.0)
    with pytest.raises(RuntimeError, match="not the note precision"):
        run_eval.wjazz_confidence(solo, onsets, notes, 4 / 5)


def test_the_strata_group_each_set_by_kind_and_keep_second_takes_out():
    card = {
        "wjazz": {
            "A.m4a": {"note_f1": 0.9, "beat_f1": 0.95, "tempoclass": "UP", "style": "BEBOP"},
            "B.m4a": {"note_f1": 0.7, "tempoclass": "SLOW", "style": "COOL", "instrument": "ts"},
            "A.m4a [line=crepe]": {"note_f1": 0.1, "tempoclass": "UP"},
            "C.m4a": {"skipped": "wrong take"},
        },
        "notation": {
            "H.m4a": {"rhythm": 0.8, "value": 0.7, "edit_cost": 30.0, "tempo_class": "MEDIUM"},
        },
        "omnibook_notation": {
            "Omnibook/O.m4a": {"rhythm": 0.9, "trusted": 1.0, "tempo_class": "UP"},
            "Omnibook/P.m4a": {"rhythm": 0.1, "trusted": 0.0, "tempo_class": "UP"},
        },
        "wjazz_notation": {"A.m4a": {"rhythm": 0.6, "trusted": 1.0}},
    }
    strata = run_eval.build_strata(card)
    assert strata["wjazz"]["tempoclass"]["UP"] == {
        "note_f1": 0.9,
        "note_f1_n": 1.0,
        "beat_f1": 0.95,
        "beat_f1_n": 1.0,
    }
    assert strata["wjazz"]["style"]["COOL"]["note_f1_n"] == 1.0
    assert strata["notation"]["hand scores"]["MEDIUM"]["edit_cost"] == 30.0
    assert strata["notation"]["Omnibook"]["UP"] == {"rhythm": 0.9, "rhythm_n": 1.0}
    # Flex-Q takes the solo's own tempo class, from the WJazzD row.
    assert strata["notation"]["Flex-Q (collateral)"]["UP"]["rhythm"] == 0.6


def test_the_tempo_of_a_page_is_the_median_beat_of_its_grid():
    beats = [i * 0.5 for i in range(40)] + [20.1]  # one stray beat does not move it
    assert run_eval.span_bpm(beats, (0.0, 30.0)) == pytest.approx(120.0)
    assert run_eval.span_bpm(beats, (50.0, 60.0)) is None


def test_an_omr_pages_trace_names_the_page_bar_at_its_step():
    """The step check reaches the row: counted as `page_steps`, and named in
    the sentence the scorecard prints."""
    from swingscribe.evaluation import page_bars

    trace = {
        "matches": 40,
        "slope": 1.0,
        "steady": True,
        "first_bar": 1,
        "segments": [
            {"from": 0.0, "to": 40.5, "offset": 0.0, "beat_offset": 0.0, "matches": 20},
            {"from": 41.0, "to": 80.0, "offset": -2.0, "beat_offset": 2.0, "matches": 20},
        ],
        "steps": [{"at": 41.0, "bar": 11, "change": -2.0}],
    }
    bars = page_bars([(str(i), 6.0 if i == 11 else 4.0, 4.0) for i in range(1, 30)])
    differences = [(0.5 * k, 0.0) for k in range(82)] + [(41.0 + k, -2.0) for k in range(40)]
    row = run_eval.traced(trace, 4.0, bars, differences)
    assert row["page_steps"] == 1.0
    assert "page bar 11 holds 6 of 4 beats -- the page's step" in row["trace"]
    # A listener's row is not an OMR reading and gets no check at all.
    assert "page_steps" not in run_eval.traced(trace, 4.0)
    # The check reads the matched notes unrounded, and will not run without them.
    with pytest.raises(ValueError):
        run_eval.traced(trace, 4.0, bars)


def test_an_undecided_step_is_named_and_never_counted():
    """Half a beat left over with nothing on the page to account for it is
    neither the grid's nor the page's: the row counts no page step and the
    sentence names it apart."""
    from swingscribe.evaluation import page_bars

    trace = {
        "matches": 40,
        "slope": 1.0,
        "steady": True,
        "first_bar": 1,
        "segments": [
            {"from": 0.0, "to": 40.5, "offset": 0.0, "beat_offset": 0.0, "matches": 20},
            {"from": 41.0, "to": 80.0, "offset": 0.5, "beat_offset": 0.5, "matches": 20},
        ],
        "steps": [{"at": 41.0, "bar": 11, "change": 0.5}],
    }
    bars = page_bars([(str(i), 4.0, 4.0) for i in range(1, 30)])
    differences = [(0.5 * k, 0.0) for k in range(82)] + [(41.0 + k, 0.5) for k in range(40)]
    row = run_eval.traced(trace, 4.0, bars, differences)
    assert row["page_steps"] == 0.0
    assert "(OMR check: Undecided: +0.5 at bar 11: residual +0.50" in row["trace"]


def test_the_step_check_reads_the_pairs_the_trace_was_built_from():
    """`page_differences` is the trace's own input, asked for again: split by
    the trace's runs, it holds exactly each run's matches, at the offsets
    the runs were labelled from."""
    from swingscribe.benchmark import notation_notes
    from swingscribe.score_bars import bar_line_trace

    notation = _eighth_page(bars=8)
    ours = notation_notes(notation)
    # The page slips a beat after its fourth bar: two runs, 0 and -1.
    slipped = _Reference(
        [_RefNote(p + (1.0 if i >= 32 else 0.0), d, n) for i, (p, d, n) in enumerate(ours)]
    )
    trace = bar_line_trace(notation, slipped)
    differences = run_eval.page_differences(notation, slipped)
    assert [s["offset"] for s in trace["segments"]] == [0.0, -1.0]
    assert len(differences) == trace["matches"] == len(ours)
    for segment in trace["segments"]:
        run = [d for p, d in differences if segment["from"] <= p <= segment["to"]]
        assert len(run) == segment["matches"]
        assert set(run) == {segment["offset"]}


# -- the review of 2026-09-30: wiring the scorecard now tests, not just renders --


class _Reference:
    """The fields `score_notation_page` reads off an mscz.Score."""

    def __init__(self, melody, beats_per_bar=4.0):
        self.melody = melody
        self.beats_per_bar = beats_per_bar


class _RefNote:
    def __init__(self, position, duration, pitch):
        self.position, self.duration, self.pitch = position, duration, pitch


def _eighth_page(bars=4):
    """A 4/4 Notation of straight eighths on a line no alignment can confuse."""
    from swingscribe.model import NotatedBar, NotatedNote, Notation

    def note(beat, pitch):
        return NotatedNote(
            beat=beat,
            duration=0.5,
            pitch=pitch,
            step="C",
            alter=0,
            octave=4,
            is_rest=False,
            tie_stop=False,
        )

    return Notation(
        bars=[
            NotatedBar(
                number=b + 1,
                time_signature=(4, 4),
                notes=[note(0.5 * j, 60 + ((8 * b + j) * 5) % 13) for j in range(8)],
            )
            for b in range(bars)
        ]
    )


def test_score_notation_page_hands_the_placement_verdict_to_the_edit_cost():
    """`_notation_one`'s wiring: the bar-line agreement is read first and its
    verdict reaches the edit cost's bar edit -- one edit for a page a beat
    off throughout, and none for a page one slipped beat took off the bar,
    which the shift already charges."""
    from swingscribe.benchmark import notation_notes

    notation = _eighth_page()
    ours = notation_notes(notation)
    per = 100.0 / len(ours)

    same = _Reference([_RefNote(p, d, n) for p, d, n in ours])
    agreement, result = run_eval.score_notation_page(notation, same)
    assert agreement["beat_offset"] == 0.0
    assert result["edit_bar"] == 0.0 and result["edit_cost"] == 0.0

    late = _Reference([_RefNote(p + 1.0, d, n) for p, d, n in ours])
    agreement, result = run_eval.score_notation_page(notation, late)
    assert agreement["beat_offset"] == 3.0  # ours sit three beats into their bar
    assert result["edit_bar"] == pytest.approx(per)
    assert result["edit_cost"] == pytest.approx(per)

    slipped = _Reference(
        [_RefNote(p + (1.0 if i >= 8 else 0.0), d, n) for i, (p, d, n) in enumerate(ours)]
    )
    agreement, result = run_eval.score_notation_page(notation, slipped)
    assert agreement["beat_offset"] != 0.0  # the mode says off: 24 notes against 8
    assert result["edit_bar"] == 0.0
    assert result["edit_position"] == pytest.approx(per)
    assert result["edit_cost"] == pytest.approx(per)


def test_the_wjazz_confidence_means_are_per_solo_and_pooled():
    """The per-solo mean (each solo once) is not the pooled fact (each false
    positive once); both are on the card, under names that say which."""
    rows = {
        "A.m4a": {"conf_auc": 0.9, "fp_low10": 0.5, "fp_low20": 1.0, "fp_n": 1.0},
        "B.m4a": {"conf_auc": 0.5, "fp_low10": 0.0, "fp_low20": 0.25, "fp_n": 3.0},
        "B.m4a [line=crepe]": {"conf_auc": 0.0, "fp_low10": 0.0, "fp_low20": 0.0, "fp_n": 99.0},
    }
    s = run_eval.wjazz_confidence_summary(rows)
    assert s["wjazz_conf_auc"] == pytest.approx(0.7)
    assert s["wjazz_fp_low20"] == pytest.approx(0.625)
    assert s["wjazz_pooled_conf_auc"] == pytest.approx((0.9 + 3 * 0.5) / 4)
    assert s["wjazz_pooled_fp_low10"] == pytest.approx(0.5 / 4)
    assert s["wjazz_pooled_fp_low20"] == pytest.approx((1.0 + 0.75) / 4)
    assert s["wjazz_pooled_fp_n"] == 4.0 and s["wjazz_pooled_conf_n"] == 2.0
    # A card from before `fp_n` keeps its per-solo means and gains no pooled ones.
    old = {k: {f: v for f, v in e.items() if f != "fp_n"} for k, e in rows.items()}
    assert not any(key.startswith("wjazz_pooled") for key in run_eval.wjazz_confidence_summary(old))


def test_the_pdf_page_strata_keep_the_tiers_apart():
    """A silver page and a scan are different kinds of reference (E3); one
    stratum would mix them the moment a bronze page is scored."""
    silver = {"rhythm": 0.8, "silver": 1.0, "trusted": 1.0, "tempo_class": "UP"}
    bronze = {"rhythm": 0.4, "silver": 0.0, "trusted": 1.0, "tempo_class": "UP"}
    card = {
        "wjazz": {},
        "pages_notation": {
            "Transcriptions_Other/S.m4a": silver,
            "Transcriptions_Other/B.m4a": bronze,
        },
    }
    notation = run_eval.build_strata(card)["notation"]
    assert notation["PDF pages, silver"]["UP"] == {"rhythm": 0.8, "rhythm_n": 1.0}
    assert notation["PDF pages, bronze"]["UP"] == {"rhythm": 0.4, "rhythm_n": 1.0}
    assert "PDF pages" not in notation


def test_the_scorecard_renders_every_new_section(capsys):
    """A crash in a renderer used to show only after a nine-minute scoring
    pass. A small card through `render`, its summary built by the same
    functions `main` uses."""
    edits = dict.fromkeys(run_eval.EDIT_KEYS, 0.0) | {
        "edit_cost": 50.0,
        "edit_insertions": 10.0,
        "edit_position": 15.0,
        "edit_value": 25.0,
        "edit_position_beside": 5.0,
        "edit_value_beside": 12.0,
        "edit_beside_share": 0.3,
    }
    bar_line = {"beat_n": 40.0, "beat_offset": 0.0, "beat_share": 0.9, "on_the_bar": 0.9}
    hand = {"bars": 10.0, "n_matched": 40.0, "rhythm": 0.8, "value": 0.7, **bar_line, **edits}
    page = hand | {
        "coverage": 0.8,
        "trusted": 1.0,
        "silver": 1.0,
        "tempo_class": "UP",
        "beat_steps": 1.0,
        "page_steps": 1.0,
        "trace": "bars 1-4 on the bar; bars 5-10 +2.0  [steps: -2.0 at bar 5]",
    }
    audio = {"pitch_f1": 0.9, "chroma_f1": 0.9, "onset_f1": 0.9, "note_f1": 0.8}
    solo = {
        "performer": "Some Player",
        "instrument": "ts",
        "tempo": 200.0,
        "note_f1": 0.9,
        "note_precision": 0.9,
        "note_recall": 0.9,
        "beat_f1": 0.95,
        "conf_auc": 0.7,
        "fp_low10": 0.3,
        "fp_low20": 0.5,
        "fp_n": 3.0,
        "tempoclass": "UP",
        "style": "BEBOP",
    }
    erased = {
        "erasures": 5.0,
        "matched": 4.0,
        "moved": 1.0,
        "notes": 80.0,
        "same_stems": 4.0,
        "same_matched": 4.0,
        "conf_auc": 0.75,
        "erased_low10": 0.25,
        "erased_low20": 0.5,
    }
    card = {
        "wjazz": {"A.m4a": solo},
        "mscz": {"H.m4a": audio, "H.m4a [line=crepe]": audio},
        "notation": {"H.m4a": hand | {"tempo_class": "MEDIUM"}, "H.m4a [line=crepe]": hand},
        "pages": {"Transcriptions_Other/P.m4a": audio | {"silver": 1.0}},
        "pages_notation": {"Transcriptions_Other/P.m4a": page},
        "erasures": {"H.m4a": erased},
    }
    summary = {"wjazz_note_n": 1.0, "wjazz_beat_n": 1.0, "wjazz_note_f1": 0.9}
    summary |= {"wjazz_beat_f1": 0.95, "mscz_note_f1": 0.8}
    summary |= run_eval.wjazz_confidence_summary(card["wjazz"])
    summary |= run_eval.edit_summary(card["notation"], "mscz")
    summary |= run_eval.located_summary(card["pages"], card["pages_notation"], "pages_silver")
    summary |= {"pianist_edit_cost": 50.0, "pianist_edit_cost_crepe": 55.0}
    summary |= {"pianist_edit_cost_n": 1.0}
    card["summary"] = summary
    card["erasure_means"] = run_eval.erasure_means(card["erasures"])
    card["strata"] = run_eval.build_strata(card)

    run_eval.render(card)
    out = capsys.readouterr().out
    assert "mean edit cost 50.0 per 100 notes" in out
    assert "= hearing 10.0 + notation beside a hearing edit 17.0 + notation alone 23.0" in out
    assert "a mean over 1 solos, each counted once" in out
    assert "pooled: each of the 3 false positives counted once" in out
    assert "4 of 5 erasures in span matched" in out
    assert "pooled: each matched erasure counted once" in out
    assert "bar-line steps that are the page's, not the grid's: 1 of 1" in out
    assert "edit cost 50.0 / 55.0 per 100 notes over 1" in out
    assert "PDF pages, silver by tempo class" in out
    assert "WJazzD by tempo class" in out


# -- linked sidecars: a take is a track (gui/library.py) ---------------------


def test_a_linked_take_is_keyed_by_its_own_name_and_finds_its_audio(tmp_path, monkeypatch):
    monkeypatch.setattr(run_eval, "BENCH", tmp_path)
    own = write_sidecar(tmp_path / "Multi-Horn", "Open_Sesame.m4a")
    take = tmp_path / "Multi-Horn" / "Open_Sesame_Melody.swingscribe.json"
    take.write_text(
        json.dumps({"audio": "Open_Sesame.m4a", "region": [0.0, 67.3], "model": "m"}),
        encoding="utf-8",
    )
    found = {key: (sidecar, audio) for key, sidecar, audio, _ in run_eval.bench_takes()}
    assert found["Multi-Horn/Open_Sesame.m4a"] == (own, tmp_path / "Multi-Horn/Open_Sesame.m4a")
    assert found["Multi-Horn/Open_Sesame_Melody"][1] == tmp_path / "Multi-Horn/Open_Sesame.m4a"
    assert run_eval.sidecar_name(take) == "Multi-Horn/Open_Sesame_Melody"
    # Its page reads its own sidecar, by the same key.
    assert (tmp_path / "Multi-Horn/Open_Sesame_Melody.swingscribe.json").is_file()


def test_a_take_whose_audio_is_missing_is_not_scored(tmp_path, monkeypatch):
    monkeypatch.setattr(run_eval, "BENCH", tmp_path)
    (tmp_path / "Gone.swingscribe.json").write_text(
        json.dumps({"audio": "nowhere.m4a", "region": [0, 1]}), encoding="utf-8"
    )
    assert run_eval.bench_takes() == []


def test_discover_tunes_benchmarks_a_linked_take_with_a_score(tmp_path):
    (tmp_path / "Head.musicxml").write_text("<score-partwise/>", encoding="utf-8")
    write_sidecar(tmp_path / "Multi-Horn", "Open_Sesame.m4a")
    take = tmp_path / "Multi-Horn" / "Open_Sesame_Melody.swingscribe.json"
    take.write_text(
        json.dumps({"audio": "Open_Sesame.m4a", "score": str(tmp_path / "Head.musicxml")}),
        encoding="utf-8",
    )
    found = score_benchmark.discover_tunes(tmp_path)
    ((audio, score, title, _instrument),) = found.values()
    assert audio == "Multi-Horn/Open_Sesame_Melody"
    assert score == "Head.musicxml"
    assert title == "Open Sesame Melody"
    assert score_benchmark.TAKES[audio] == (take, tmp_path / "Multi-Horn/Open_Sesame.m4a")
