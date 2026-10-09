"""Every script finds a track's audio through gui/library.py, never by hand.

A track's key is its sidecar's path (`library.discover`). Once a copy of a
recording becomes a LINKED take of another file (scripts/dedupe_audio.py),
`BENCH / key` names a file that is gone, and a script that built the path by
hand -- or globbed the folder for audio, or for sidecars -- dropped the
track without a word. These are the three shapes that hole took in nine
scripts; the next script must not bring it back:

- `BENCH / name` (or key, track, entry["track"], r["name"]) as audio: use
  `library.audio_for_key(root, key)`, or the audio `library.discover` and
  `run_eval.bench_takes` hand out;
- a glob for audio suffixes, or a list of them: use `library.audio_files`;
- a glob for sidecars: use `library.discover`.

A line that builds such a path for something that is NOT audio (a page's
title, a page Export wrote) says so with a comment containing "not audio".
"""

import re
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"

KEY_JOIN = re.compile(
    r"\bBENCH(?:_DIR)?\s*/\s*"
    r"(?:name|key|track|entry\[\s*[\"']track[\"']\s*\]|[rh]\[\s*[\"']name[\"']\s*\])"
    r"(?![\w\[])"
)
AUDIO_GLOB = re.compile(
    r"\.r?glob\(\s*f?[\"'][^\"']*\.(?:m4a|mp3|flac|aac|ogg|opus|wma|aiff?)[\"']"
)
SUFFIX_LIST = re.compile(r"\bAUDIO_(?:SUFFIXES|GLOBS)\s*=")
SIDECAR_GLOB = re.compile(r"\.r?glob\(\s*f?[\"']\*(?:[^\"']*swingscribe\.json|\{[^}]*SUFFIX\})")


def offences(text: str) -> list[str]:
    found = []
    for number, line in enumerate(text.splitlines(), start=1):
        code = line.split("#", 1)[0]
        if "not audio" in line:
            continue
        for name, pattern in (
            ("key joined to a path as audio", KEY_JOIN),
            ("audio glob", AUDIO_GLOB),
            ("own audio suffix list", SUFFIX_LIST),
            ("sidecar glob", SIDECAR_GLOB),
        ):
            if pattern.search(code):
                found.append(f"{number}: {name}: {line.strip()}")
    return found


def test_no_script_finds_audio_by_hand():
    bad = {}
    for script in sorted(SCRIPTS.glob("*.py")):
        found = offences(script.read_text(encoding="utf-8"))
        if found:
            bad[script.name] = found
    assert bad == {}, "\n".join(f"{name}: {line}" for name, lines in bad.items() for line in lines)


def test_the_guard_catches_each_shape():
    assert offences("document = library.ingested_document(run_eval.BENCH / name, config)")
    assert offences('if not (BENCH / r["name"]).is_file():')
    assert offences('stems = resolve(BENCH / entry["track"], model)')
    assert offences('for path in sorted(WJAZZD.glob("*.m4a")):')
    assert offences('AUDIO_GLOBS = ("*.m4a", "*.mp3")')
    assert offences('for p in BENCH.rglob("*.swingscribe.json"):')
    assert offences('for p in root.rglob(f"*{library.SETTINGS_SUFFIX}"):')
    # ... and leaves alone what is not audio.
    assert not offences('path = BENCH / f"{track}.swingscribe.json"')
    assert not offences("score = run_eval.BENCH / by_audio[track]")
    assert not offences("str(BENCH / track),  # a name for the page's title, not audio")
    assert not offences('stems = sorted(directory.glob("*.wav"))')
