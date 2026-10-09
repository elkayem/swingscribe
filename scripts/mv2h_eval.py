"""MV2H over every page the harness scores as notation (docs/mv2h.md).

The outside cross-check on the edit cost (docs/roadmap.md E4): the same
pages `run_eval.py` builds and scores -- the listener's twelve hand scores
(and the pianists' second takes), the 22 Omnibook sides, the PDF pages --
each written in MV2H's text format by `swingscribe.mv2h` and handed to the
MV2H Java tool (McLeod and Steedman 2018; MIT; a download, never a
dependency), in three placements:

- `nonaligned`: each side in its own score time, aligned by MV2H's `-a`
  machinery (McLeod 2019) -- its DTW, its co-optimal alignments, its
  scoring -- run through the driver below, which re-reads the ground truth
  for every alignment because `-a` itself corrupts it (a grouping list
  consumed by the first alignment scored). Nothing of ours decides which
  note is which: the outside check proper.
- `grid`: both sides on the reference's clock, ours moved by the whole
  number of quarters the time-free aligner's matched notes vote for
  (`mv2h.grid_shift`), scored in MV2H's aligned mode. The placement the
  Rhythm Perceiver's numbers imply (docs/mv2h.md), and the one to hold
  beside its 0.92.
- `tempo`: the `grid` placement rendered at the performance's own tempo
  (`run_eval.span_bpm`, the median beat of the page's grid) instead of 120
  bpm. MV2H's tolerances are milliseconds, so the rendering tempo sets how
  strict they are in beats: this is the sensitivity of the answer to a
  choice nobody reports.

`nonaligned` and `grid` at 120 bpm (`mv2h.MS_PER_QUARTER`). Beside each
page's MV2H it prints our own measures (edit cost, rhythm, value, pitch F1)
and the rank correlation between the two families across pages.

    python scripts/mv2h_eval.py --notes SNAPSHOT.json --grids SNAPSHOT.json \\
        --pins PINS.json --work DIR [--json card.json] [--jobs 4]

It reads the harness caches only through the files it is given: another
process may be rewriting the live ones. `--work` receives MV2H's input --
note lists derived from commercial recordings -- so it must be outside the
repo (checked). The Java tool runs in WSL by default (`--mv2h-home`, under
the WSL home, holding `jdk-*/bin/java` and `MV2H/bin`), or natively with
`--java` and `--classpath` (MV2H's classes); the driver is then compiled
with `--javac` if given, else with the WSL JDK's javac. `--heap` bounds
each JVM.
"""

import argparse
import json
import shlex
import statistics
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import run_eval  # noqa: E402

MODES = ("nonaligned", "grid", "tempo")
COMPONENTS = ("multi_pitch", "voice", "meter", "value", "harmony", "mv2h")
# MV2H had our page written the reference's key signature (`mv2h.with_keys_agreed`).
SAME_KEY = "mv2h_same_key"
REPORTED = (*COMPONENTS, SAME_KEY)
# Our own page measures, read beside MV2H: the pinned ones, recomputed here
# from the same notes and checked against the pins.
OURS = ("edit_cost", "rhythm", "value", "coverage")
SETS = ("hand", "hand_crepe", "omnibook", "pages_silver", "pages_bronze")
SET_TITLES = {
    "hand": "hand scores",
    "hand_crepe": "pianists, CREPE line",
    "omnibook": "Omnibook",
    "pages_silver": "PDF pages, silver",
    "pages_bronze": "PDF pages, bronze",
}
# The pinned section each set's rows live under (run_eval.flatten).
PIN_SECTIONS = {
    "hand": ("notation", "mscz"),
    "hand_crepe": ("notation", "mscz"),
    "omnibook": ("omnibook-notation", "omnibook"),
    "pages_silver": ("pages-notation", "pages"),
    "pages_bronze": ("pages-notation", "pages"),
}


def cached_runs(notes_path: Path, log=print) -> dict:
    """The runs `run_eval.transcribe_all` would score, read from a snapshot
    and never transcribed: every sidecar'd track on disk and, for a
    pianist, its second take -- and only an entry whose fingerprint is the
    one the current transcriber would write, so these are the notes the
    pins were computed on."""
    runs = json.loads(notes_path.read_text(encoding="utf-8"))
    live, stale = {}, []
    # Through run_eval's walk (library.discover): a linked take's audio is
    # its sidecar's, wherever the copy it was keyed by has gone.
    for name, _sidecar_path, _audio, sidecar in run_eval.bench_takes(lambda _message: None):
        takes = [(name, None)]
        if run_eval.transcribe_settings(sidecar, 0.2, 0.0).uses_piano_oracle:
            takes.append((run_eval.second_key(name), run_eval.SECOND_LINE))
        for key, line in takes:
            run = runs.get(key)
            wanted = run_eval.transcribe_fingerprint(sidecar, 0.2, 0.0, line)
            if run is None or run.get("fingerprint") != wanted:
                stale.append(key)
                continue
            live[key] = run
    if stale:
        log(f"  {len(stale)} run(s) missing or stale in the snapshot, not scored: {stale[:6]}...")
    return live


def set_of(key: str, tiers: dict[str, str]) -> str:
    if run_eval.is_omnibook(key):
        return "omnibook"
    if run_eval.is_page(key):
        return f"pages_{tiers.get(run_eval.track_of(key), 'bronze')}"
    return "hand" if run_eval.take_of(key) is None else "hand_crepe"


def _page_one(task: tuple) -> dict | None:
    """Build our page and the reference, score them as run_eval does, and
    write the MV2H input for both placements. Pure function of its task."""
    name, run, grid, score_path, work, ms_per_quarter, cache_dir = task
    run_eval._worker_setup(cache_dir)
    from swingscribe import mscz
    from swingscribe import mv2h as m
    from swingscribe.alignment import measured_transposition
    from swingscribe.benchmark import notation_notes
    from swingscribe.evaluation import reader_bars

    notation = run_eval.notate_run(name, run, grid)
    if notation is None or not notation.bars:
        return None
    reference = mscz.parse_any(score_path)
    agreement, result = run_eval.score_notation_page(notation, reference)
    if not result["n_matched"]:
        return None
    ours_raw = notation_notes(notation)
    theirs = [(n.position, n.duration, n.pitch) for n in reference.melody]
    offset, aligned = measured_transposition([p for _, _, p in theirs], [p for _, _, p in ours_raw])
    if offset != int(result["transposition"]):
        raise RuntimeError(
            f"{name}: transposition {offset} against the scorer's {result['transposition']}"
        )
    ours = m.notation_side(notation, offset)
    page_bars = (
        reader_bars(Path(score_path))
        if Path(score_path).suffix.lower() in (".musicxml", ".xml")
        else None
    )
    ref = m.score_side(reference, page_bars)
    shift, on_clock = m.grid_shift(ours.notes, theirs, aligned.pairs)

    folder = Path(work) / run_eval.pin_name(name).replace(" ", "_")
    folder.mkdir(parents=True, exist_ok=True)

    def write(file: str, side, at: float, rate: float = ms_per_quarter) -> str:
        path = folder / file
        text = "\n".join(m.lines(side, shift=at, ms_per_quarter=rate)) + "\n"
        path.write_text(text, encoding="utf-8", newline="\n")
        return str(path)

    # Non-aligned: each side from its own zero; MV2H's -a aligns them.
    files = {
        "nonaligned": (
            write("ref.nonaligned.txt", ref, -m.earliest(ref)),
            write("ours.nonaligned.txt", ours, -m.earliest(ours)),
        )
    }
    # Grid: ours moved onto the reference's clock, both lifted by one
    # constant so nothing starts before zero.
    origin = max(0.0, -m.earliest(ref), -(m.earliest(ours) + shift))
    files["grid"] = (
        write("ref.grid.txt", ref, origin),
        write("ours.grid.txt", ours, shift + origin),
    )
    # Tempo: the same placement at the performance's own tempo. A grid beat
    # is a true-meter quarter on both sides (a double-time page is halved
    # to true meter by `notation_side`), so its median length is the rate.
    beats = run_eval.page_grid(run_eval.track_of(name), grid)[1]
    bpm = run_eval.span_bpm(beats, tuple(run["region"]))
    if bpm:
        files["tempo"] = (
            write("ref.tempo.txt", ref, origin, 60_000.0 / bpm),
            write("ours.tempo.txt", ours, shift + origin, 60_000.0 / bpm),
        )
    return {
        "name": name,
        "files": files,
        "bpm": round(bpm, 1) if bpm else None,
        "shift": shift,
        "on_clock": round(on_clock, 4),
        "transposition": offset,
        "notes_ours": len(ours.notes),
        "notes_ref": len(ref.notes),
        "bars_ours": len(ours.bars),
        "bars_ref": len(ref.bars),
        "edit_cost": round(result["edit_cost"], 3),
        "rhythm": round(result["rhythm"], 4),
        "value": round(result["value"], 4),
        "coverage": round(result["coverage"], 4),
        "trusted": bool(result["trusted"]),
        "n_matched": result["n_matched"],
        "on_the_bar": agreement.get("on_the_bar"),
    }


# MV2H's non-aligned mode (`mv2h.Main -a`) scores EVERY co-optimal DTW
# alignment and keeps the best, one at a time: 1,228,800 of them for a
# 280-note page (Birks Works, 2026-09-30), 1,707 s run to the end -- for
# one short hand score -- and the count multiplies with every tie
# region: a median 3e9 over the 44 pages, 6e24 at most.
#
# And `Main -a` at 79155847 does not score them correctly. `Meter.getF1`
# takes the ground truth's OWN grouping list and removes every grouping it
# matches (src/mv2h/objects/meter/Meter.java), and `-a` scores every
# alignment against one ground truth: from the second alignment on, meter
# reads near 0 (Carl Perkins' first alignment, scored four times on one
# ground truth: meter 0.670, 0.0, 0.0, 0.0). So `-a`'s "best" is in
# practice the FIRST alignment it evaluates (on Giant Steps, 0.8251 over
# all 19,968 against 0.8321 correctly scored). Found in review, 2026-09-30.
#
# So this driver runs the same evaluation through MV2H's own classes (the
# flags `-a` sets, its alignment enumeration,
# `evaluateTranscription(align(...))`, its comparison for "best") with the
# ground truth PARSED AGAIN for every alignment, and chooses which to score:
#
# - ALL of them when there are at most `cap`, in `Main -a`'s own order;
# - otherwise `cap` from the co-optimal alignments that pair the most notes
#   at one pitch (a longest-path pass over MV2H's own alignment DAG; all of
#   them when they fit, else index 0 and a seeded random draw), and `cap`
#   more drawn from the whole co-optimal set, because the most multi-pitch
#   is not always the most MV2H (meter and value move too).
#
# Scored correctly, a sample's best is a LOWER bound on the exhaustive
# answer. It prints which case it was, how many it scored, which subset the
# best came from and the worst score seen. With `shared` as a fifth
# argument it scores against one ground truth, as `Main -a` does: a check
# that the machinery is MV2H's, never a reading.
DRIVER = r"""
import java.io.File;
import java.math.BigInteger;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.IdentityHashMap;
import java.util.List;
import java.util.Map;
import java.util.Random;
import java.util.Scanner;

import mv2h.Main;
import mv2h.objects.MV2H;
import mv2h.objects.Music;
import mv2h.objects.Note;
import mv2h.tools.Aligner;
import mv2h.tools.AlignmentNode;

public class SampledAlign {
    // The ground truth as text, parsed again for each alignment scored:
    // Meter.getF1 consumes the ground truth's grouping list.
    static String truthText;
    static boolean shared;
    // Read only: the alignment DAG and the pitch-match pass.
    static Music groundTruth;
    static Music transcription;
    static final IdentityHashMap<AlignmentNode, Integer> depths =
        new IdentityHashMap<AlignmentNode, Integer>();
    static final IdentityHashMap<AlignmentNode, Integer> bests =
        new IdentityHashMap<AlignmentNode, Integer>();
    static final IdentityHashMap<AlignmentNode, BigInteger> counts =
        new IdentityHashMap<AlignmentNode, BigInteger>();

    static MV2H best = new MV2H(0, 0, 0, 0, 0);
    static String bestFrom = "none";
    static double worst = Double.POSITIVE_INFINITY;
    static long evaluated = 0;

    static Music parseTruth() throws Exception {
        return Music.parseMusic(new Scanner(truthText));
    }

    static void score(List<Integer> alignment, String from) throws Exception {
        Music truth = shared ? groundTruth : parseTruth();
        MV2H candidate = truth.evaluateTranscription(transcription.align(truth, alignment));
        evaluated++;
        if (candidate.compareTo(best) > 0) {
            best = candidate;
            bestFrom = from;
        }
        worst = Math.min(worst, candidate.mv2h);
    }

    static int depth(AlignmentNode node) {
        Integer known = depths.get(node);
        if (known != null) {
            return known;
        }
        int d = node.prevList.isEmpty() ? 1 : depth(node.prevList.get(0)) + 1;
        depths.put(node, d);
        return d;
    }

    // Notes paired at one pitch by this node: the multiset intersection of
    // the ground truth's note list at this depth and the transcription's.
    static int gain(AlignmentNode node) {
        if (node.value == -1) {
            return 0;
        }
        Map<Integer, Integer> pitches = new HashMap<Integer, Integer>();
        for (Note note : groundTruth.getNoteLists().get(depth(node) - 1)) {
            pitches.merge(note.pitch, 1, Integer::sum);
        }
        int matched = 0;
        for (Note note : transcription.getNoteLists().get(node.value)) {
            Integer left = pitches.get(note.pitch);
            if (left != null && left > 0) {
                matched++;
                pitches.put(note.pitch, left - 1);
            }
        }
        return matched;
    }

    static int most(AlignmentNode node) {
        Integer known = bests.get(node);
        if (known != null) {
            return known;
        }
        int b = 0;
        for (AlignmentNode prev : node.prevList) {
            b = Math.max(b, most(prev));
        }
        b += gain(node);
        bests.put(node, b);
        return b;
    }

    static BigInteger count(AlignmentNode node) {
        BigInteger known = counts.get(node);
        if (known != null) {
            return known;
        }
        BigInteger c = BigInteger.ZERO;
        int target = most(node) - gain(node);
        for (AlignmentNode prev : node.prevList) {
            if (most(prev) == target) {
                c = c.add(count(prev));
            }
        }
        c = c.max(BigInteger.ONE);
        counts.put(node, c);
        return c;
    }

    static List<Integer> restricted(AlignmentNode node, BigInteger index) {
        List<Integer> alignment = null;
        if (node.prevList.isEmpty()) {
            alignment = new ArrayList<Integer>();
        } else {
            int target = most(node) - gain(node);
            for (AlignmentNode prev : node.prevList) {
                if (most(prev) != target) {
                    continue;
                }
                if (index.compareTo(count(prev)) < 0) {
                    alignment = restricted(prev, index);
                    break;
                }
                index = index.subtract(count(prev));
            }
        }
        alignment.add(node.value);
        return alignment;
    }

    static List<Integer> restrictedAt(List<AlignmentNode> kept, BigInteger index) {
        for (AlignmentNode node : kept) {
            if (index.compareTo(count(node)) < 0) {
                return restricted(node, index);
            }
            index = index.subtract(count(node));
        }
        throw new IllegalArgumentException("index past the last most-matches alignment");
    }

    static List<Integer> any(List<AlignmentNode> nodes, BigInteger index) {
        for (AlignmentNode node : nodes) {
            if (index.compareTo(node.count) < 0) {
                return node.getAlignment(index);
            }
            index = index.subtract(node.count);
        }
        throw new IllegalArgumentException("index past the last alignment");
    }

    static BigInteger draw(BigInteger total, Random rng) {
        return new BigInteger(total.bitLength() + 16, rng).mod(total);
    }

    public static void main(String[] args) throws Exception {
        Main.DURATION_DELTA = 20;
        Main.ONSET_DELTA = 0;
        Main.GROUPING_EPSILON = 20;
        truthText = new String(Files.readAllBytes(Paths.get(args[0])), StandardCharsets.UTF_8);
        groundTruth = parseTruth();
        transcription = Music.parseMusic(new Scanner(new File(args[1])));
        BigInteger cap = new BigInteger(args[2]);
        Random rng = new Random(Long.parseLong(args[3]));
        shared = args.length > 4 && args[4].equals("shared");

        List<AlignmentNode> nodes = Aligner.getPossibleAlignments(groundTruth, transcription);
        BigInteger total = BigInteger.ZERO;
        for (AlignmentNode node : nodes) {
            total = total.add(node.count);
        }

        String how;
        if (total.compareTo(cap) <= 0) {
            how = "all";
            for (AlignmentNode node : nodes) {
                BigInteger i = BigInteger.ZERO;
                while (i.compareTo(node.count) < 0) {
                    score(node.getAlignment(i), "all");
                    i = i.add(BigInteger.ONE);
                }
            }
        } else {
            int top = 0;
            for (AlignmentNode node : nodes) {
                top = Math.max(top, most(node));
            }
            List<AlignmentNode> kept = new ArrayList<AlignmentNode>();
            BigInteger keptTotal = BigInteger.ZERO;
            for (AlignmentNode node : nodes) {
                if (most(node) == top) {
                    kept.add(node);
                    keptTotal = keptTotal.add(count(node));
                }
            }
            System.out.println("Most matches: " + top);
            System.out.println("With most matches: " + keptTotal);
            if (keptTotal.compareTo(cap) <= 0) {
                how = "restricted";
                BigInteger i = BigInteger.ZERO;
                while (i.compareTo(keptTotal) < 0) {
                    score(restrictedAt(kept, i), "most-matches");
                    i = i.add(BigInteger.ONE);
                }
            } else {
                how = "sampled";
                score(restrictedAt(kept, BigInteger.ZERO), "most-matches");
                for (long i = 1; i < cap.longValue(); i++) {
                    score(restrictedAt(kept, draw(keptTotal, rng)), "most-matches");
                }
            }
            for (long i = 0; i < cap.longValue(); i++) {
                score(any(nodes, draw(total, rng)), "whole-set sample");
            }
        }
        System.out.println("Alignments: " + total);
        System.out.println("Evaluated: " + evaluated + " " + how + (shared ? "-shared" : ""));
        System.out.println("Best from: " + bestFrom);
        System.out.println("Worst: " + worst);
        System.out.println(best);
    }
}
"""


def wsl_path(path: str) -> str:
    """C:\\a\\b -> /mnt/c/a/b, for a java running inside WSL."""
    p = Path(path).resolve()
    drive = p.drive.rstrip(":").lower()
    return f"/mnt/{drive}/" + "/".join(p.parts[1:])


def check_native(args) -> None:
    """A native java or javac reads MV2H's classes from a folder it must be told."""
    if (args.java or args.javac) and args.classpath is None:
        raise SystemExit("--java and --javac need --classpath, the folder of MV2H's classes")


def java_prefix(args, tool: str = "java") -> list[str]:
    """How to start `tool`: java natively with --java, javac natively with
    --javac, each in WSL otherwise (so a native java with no javac beside it
    -- the Zulu runtime Audiveris bundles -- still gets its driver built)."""
    native = args.java if tool == "java" else args.javac
    if native:
        # A path is one program (shlex would eat a Windows path's backslashes).
        return [native] if Path(native).is_file() else shlex.split(native)
    return ["wsl.exe", "-d", args.distro, "--exec", f"{args.mv2h_home}/{args.jdk}/bin/{tool}"]


def host_path(args, path, tool: str = "java") -> str:
    """`path` as `tool` sees it: a Windows path natively, /mnt/... in WSL."""
    native = args.java if tool == "java" else args.javac
    return str(path) if native else wsl_path(str(path))


def mv2h_classes(args, tool: str = "java") -> str:
    """MV2H's compiled classes, where `tool` runs."""
    native = args.java if tool == "java" else args.javac
    return args.classpath if native else f"{args.mv2h_home}/MV2H/bin"


def compile_driver(args, work: Path) -> str:
    """Compile SampledAlign against MV2H's classes; return the classpath
    the java that runs it needs."""
    folder = work / "driver"
    folder.mkdir(parents=True, exist_ok=True)
    source = folder / "SampledAlign.java"
    source.write_text(DRIVER, encoding="utf-8", newline="\n")
    command = [
        *java_prefix(args, "javac"),
        "-cp",
        mv2h_classes(args, "javac"),
        "-d",
        host_path(args, folder, "javac"),
        host_path(args, source, "javac"),
    ]
    done = subprocess.run(command, capture_output=True, text=True)
    if done.returncode:
        raise SystemExit(f"could not compile the driver: {done.stderr}")
    separator = ";" if args.java and sys.platform == "win32" else ":"
    return f"{mv2h_classes(args)}{separator}{host_path(args, folder)}"


def mv2h_command(args, ground_truth: str, transcription: str, mode: str) -> list[str]:
    """MV2H's aligned mode as it ships (`mv2h.Main`) for the grid and tempo
    placements; the driver above for the non-aligned one."""
    gt, tr = host_path(args, ground_truth), host_path(args, transcription)
    java = [*java_prefix(args), f"-Xmx{args.heap}", "-Xss64m"]
    if mode == "nonaligned":
        driver = [*java, "-cp", args.driver_classpath, "SampledAlign", gt, tr, str(args.cap), "0"]
        return [*driver, "shared"] if args.shared_truth else driver
    return [*java, "-cp", mv2h_classes(args), "mv2h.Main", "-g", gt, "-t", tr]


def run_mv2h(args, ground_truth: str, transcription: str, mode: str) -> dict:
    from swingscribe.mv2h import parse_output, with_keys_agreed

    command = mv2h_command(args, ground_truth, transcription, mode)
    started = time.time()
    # A wsl.exe started beside several others now and then returns nothing at
    # all -- no output, no error (2026-09-30: two runs of 132 in one pass, none
    # in the pass before, the same input files both times). MV2H's answer is
    # deterministic, so an empty one is retried.
    for _attempt in range(3):
        try:
            done = subprocess.run(command, capture_output=True, text=True, timeout=args.timeout)
        except subprocess.TimeoutExpired as expired:
            partial = expired.stdout
            partial = partial if isinstance(partial, str) else (partial or b"").decode()
            seen = partial.rsplit("Evaluating alignment ", 1)[-1][:60] if partial else ""
            return {"error": f"timeout after {args.timeout}s at alignment {seen.strip()}"}
        if done.stdout.strip() or done.stderr.strip():
            break
    try:
        out = parse_output(done.stdout)
    except ValueError as error:
        return {"error": f"{error}; exit {done.returncode}; stderr: {done.stderr.strip()[:300]}"}
    out[SAME_KEY] = with_keys_agreed(out)
    out["seconds"] = round(time.time() - started, 1)
    return out


def rankdata(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return ranks


def spearman(x: list[float], y: list[float]) -> float:
    """Spearman's rho: Pearson's r on mid-ranks."""
    rx, ry = rankdata(x), rankdata(y)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    sxx = sum((a - mx) ** 2 for a in rx)
    syy = sum((b - my) ** 2 for b in ry)
    return sxy / (sxx * syy) ** 0.5 if sxx and syy else float("nan")


def rho_interval(
    x: list[float], y: list[float], resamples: int = 4000, seed: int = 0
) -> tuple[float, float]:
    """A 95% bootstrap interval on rho, resampling pages."""
    import numpy as np

    rng = np.random.default_rng(seed)
    n = len(x)
    rhos = []
    for _ in range(resamples):
        idx = rng.integers(0, n, size=n)
        xs, ys = [x[i] for i in idx], [y[i] for i in idx]
        r = spearman(xs, ys)
        if r == r:
            rhos.append(r)
    if not rhos:  # every resample constant on one side
        return float("nan"), float("nan")
    low, high = np.quantile(rhos, [0.025, 0.975])
    return float(low), float(high)


def mean_interval(
    values: list[float], resamples: int = 10_000, seed: int = 0
) -> tuple[float, float, float]:
    """(mean, low, high): a 95% bootstrap interval, resampling pages."""
    import numpy as np

    arr = np.asarray(values, dtype=float)
    rng = np.random.default_rng(seed)
    means = arr[rng.integers(0, len(arr), size=(resamples, len(arr)))].mean(axis=1)
    low, high = np.quantile(means, [0.025, 0.975])
    return float(arr.mean()), float(low), float(high)


def pinned(pins: dict, set_name: str, key: str, field: str) -> float | None:
    notation_section, mscz_section = PIN_SECTIONS[set_name]
    section = mscz_section if field in ("pitch_f1", "note_f1") else notation_section
    return pins.get(f"{section}/{run_eval.pin_name(key)}/{field}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--notes", type=Path, required=True, help="snapshot of the harness notes cache"
    )
    parser.add_argument("--grids", type=Path, required=True, help="snapshot of the beat-grid cache")
    parser.add_argument(
        "--pins", type=Path, default=run_eval.BASELINES, help="pins to read our measures from"
    )
    parser.add_argument(
        "--work", type=Path, required=True, help="MV2H input files (outside the repo)"
    )
    parser.add_argument("--json", type=Path, default=None, help="write every row and summary here")
    parser.add_argument(
        "--jobs", type=int, default=4, help="processes for page building, threads for MV2H"
    )
    parser.add_argument("--timeout", type=float, default=1800.0, help="seconds per MV2H run")
    parser.add_argument("--heap", default="1g", help="-Xmx for each JVM (the commit charge)")
    parser.add_argument("--ms-per-quarter", type=float, default=500.0)
    parser.add_argument("--only", default=None, help="score only keys containing this text")
    parser.add_argument("--modes", default=",".join(MODES))
    parser.add_argument(
        "--cap",
        type=int,
        default=2000,
        help="non-aligned: score every co-optimal alignment up to this many, else this many"
        " from those pairing the most notes and this many from the whole set (seeded)",
    )
    parser.add_argument(
        "--shared-truth",
        action="store_true",
        help="non-aligned: score every alignment against ONE ground truth, as MV2H's own -a"
        " does at 79155847 (meter reads near 0 after the first) -- a check, never a reading",
    )
    parser.add_argument(
        "--java", default=None, help="a java command to run MV2H natively instead of in WSL"
    )
    parser.add_argument(
        "--javac", default=None, help="a native javac for the driver (else the WSL JDK's)"
    )
    parser.add_argument(
        "--classpath", default=None, help="MV2H's compiled classes, for --java and --javac"
    )
    parser.add_argument("--distro", default="Ubuntu")
    parser.add_argument("--mv2h-home", default=None, help="WSL folder holding the JDK and MV2H/bin")
    parser.add_argument("--jdk", default="jdk-21.0.12.1+1")
    args = parser.parse_args()

    repo = Path(__file__).resolve().parent.parent
    work = args.work.resolve()
    if work == repo or repo in work.parents:
        raise SystemExit(
            "--work must be outside the repo: it holds note lists from commercial recordings"
        )
    modes = [mode for mode in args.modes.split(",") if mode]
    check_native(args)
    in_wsl = args.java is None or ("nonaligned" in modes and args.javac is None)
    if in_wsl and args.mv2h_home is None:
        home = subprocess.run(
            ["wsl.exe", "-d", args.distro, "--exec", "printenv", "HOME"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        args.mv2h_home = f"{home}/mv2h-tools"
    if "nonaligned" in modes:
        args.driver_classpath = compile_driver(args, work)

    print(f"== Runs from {args.notes} ==")
    runs = run_eval.split_runs(cached_runs(args.notes), None, test=False)
    grids = json.loads(args.grids.read_text(encoding="utf-8"))
    sys.path.insert(0, str(Path(__file__).parent))
    import score_benchmark

    by_audio = {audio: mscz_name for audio, mscz_name, *_ in score_benchmark.TUNES.values()}
    tiers = run_eval.page_tiers(runs)
    names, tasks = [], []
    for name, run in sorted(runs.items()):
        track = run_eval.track_of(name)
        if track not in by_audio or track not in grids:
            continue
        if args.only and args.only not in name:
            continue
        names.append(name)
        tasks.append(
            (
                name,
                run,
                grids[track],
                str(run_eval.BENCH / by_audio[track]),
                str(work),
                args.ms_per_quarter,
                str(run_eval.CACHE_DIR),
            )
        )
    print(f"== Building {len(tasks)} page(s) in {args.jobs} process(es) ==")
    started = time.time()
    built = run_eval.parallel_map(_page_one, tasks, args.jobs)
    rows = {row["name"]: row for row in built if row}
    print(f"   {len(rows)} built in {time.time() - started:.0f}s")

    jobs = [(name, mode) for name in rows for mode in modes if mode in rows[name]["files"]]
    print(f"== MV2H: {len(jobs)} run(s) in {args.jobs} thread(s) ==")
    started = time.time()

    def one(job):
        name, mode = job
        ground_truth, transcription = rows[name]["files"][mode]
        result = run_mv2h(args, ground_truth, transcription, mode)
        tag = result.get("error") or f"MV2H {result['mv2h']:.3f} in {result['seconds']}s"
        print(f"   {mode:10s} {name}: {tag}", flush=True)
        return job, result

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        for (name, mode), result in pool.map(one, jobs):
            rows[name][mode] = result
    print(f"   done in {time.time() - started:.0f}s")

    pins = json.loads(args.pins.read_text(encoding="utf-8"))
    for name, row in rows.items():
        row["set"] = set_of(name, tiers)
        row["pitch_f1"] = pinned(pins, row["set"], name, "pitch_f1")
        drift = {
            field: round(abs(row[field] - pin), 4)
            for field in ("edit_cost", "rhythm", "value")
            if (pin := pinned(pins, row["set"], name, field)) is not None
        }
        row["pin_drift"] = max(drift.values()) if drift else None
        row.pop("files")

    # The rows first: MV2H's answers must survive a failure in the summary.
    if args.json:
        args.json.write_text(json.dumps({"rows": rows}, indent=1), encoding="utf-8")
    summary = summarize(rows, modes)
    render(rows, summary, modes)
    if args.json:
        args.json.write_text(
            json.dumps({"rows": rows, "summary": summary}, indent=1), encoding="utf-8"
        )
        print(f"\nwritten {args.json}")


def usable(row: dict, mode: str) -> bool:
    """A row counts when MV2H answered, and for a located page only when the
    pairing is trusted -- the rows E4's means are taken over."""
    located = row["set"] in ("omnibook", "pages_silver", "pages_bronze")
    return mode in row and "error" not in row[mode] and (row["trusted"] or not located)


def summarize(rows: dict, modes: list[str]) -> dict:
    from swingscribe.evaluation import paired_change

    out: dict = {"sets": {}, "correlations": {}, "pianists": {}}
    for set_name in SETS:
        members = [row for row in rows.values() if row["set"] == set_name]
        if not members:
            continue
        entry: dict = {"n_pages": len(members)}
        for mode in modes:
            ok = [row for row in members if usable(row, mode)]
            entry[mode] = {"n": len(ok)}
            for field in REPORTED:
                if ok:
                    mean, low, high = mean_interval([row[mode][field] for row in ok])
                    entry[mode][field] = [round(mean, 4), round(low, 4), round(high, 4)]
        ok = [row for row in members if row["trusted"] or set_name.startswith("hand")]
        for field in (*OURS, "pitch_f1"):
            values = [row[field] for row in ok if row.get(field) is not None]
            if values:
                entry[field] = round(statistics.fmean(values), 4)
        out["sets"][set_name] = entry

    # Across pages: the default take of every trusted page, pooled, and each set.
    pools = {
        "all": [r for r in rows.values() if r["set"] != "hand_crepe"],
        "hand": [r for r in rows.values() if r["set"] == "hand"],
        "omnibook": [r for r in rows.values() if r["set"] == "omnibook"],
    }
    for pool_name, pool in pools.items():
        for mode in modes:
            ok = [r for r in pool if usable(r, mode) and r.get("pitch_f1") is not None]
            if len(ok) < 5:
                continue
            table = {}
            for component in (COMPONENTS[-1], SAME_KEY, *COMPONENTS[:-1]):
                x = [r[mode][component] for r in ok]
                if len(set(x)) == 1:
                    # Voice and harmony read the same on every page: no rank.
                    table[f"{component}~constant"] = [round(x[0], 3)]
                    continue
                for ours in ("edit_cost", "rhythm", "value", "pitch_f1"):
                    y = [r[ours] for r in ok]
                    rho = spearman(x, y)
                    low, high = rho_interval(x, y)
                    table[f"{component}~{ours}"] = [round(rho, 3), round(low, 3), round(high, 3)]
            out["correlations"][f"{pool_name}/{mode}"] = {"n": len(ok), **table}

    # The pianists: oracle line (default) against the CREPE line, paired.
    for mode in modes:
        pairs = []
        for row in rows.values():
            if row["set"] != "hand_crepe":
                continue
            default = rows.get(run_eval.track_of(row["name"]))
            if default and usable(default, mode) and usable(row, mode):
                pairs.append(
                    (
                        row[mode]["mv2h"],
                        default[mode]["mv2h"],
                        row["edit_cost"],
                        default["edit_cost"],
                        row[mode][SAME_KEY],
                        default[mode][SAME_KEY],
                    )
                )
        if len(pairs) >= 2:
            change = paired_change([p[0] for p in pairs], [p[1] for p in pairs])
            edit = paired_change([p[2] for p in pairs], [p[3] for p in pairs])
            keyed = paired_change([p[4] for p in pairs], [p[5] for p in pairs])
            out["pianists"][mode] = {
                "n": change.n,
                "mv2h_crepe": round(statistics.fmean(p[0] for p in pairs), 4),
                "mv2h_oracle": round(statistics.fmean(p[1] for p in pairs), 4),
                "mv2h_change": [round(change.mean, 4), round(change.low, 4), round(change.high, 4)],
                "mv2h_up_down": [change.up, change.down, change.level],
                "mv2h_sign_p": round(change.p, 3),
                "same_key_change": [
                    round(keyed.mean, 4),
                    round(keyed.low, 4),
                    round(keyed.high, 4),
                ],
                "same_key_up_down": [keyed.up, keyed.down, keyed.level],
                "same_key_sign_p": round(keyed.p, 3),
                "edit_cost_change": [round(edit.mean, 3), round(edit.low, 3), round(edit.high, 3)],
            }
    return out


def render(rows: dict, summary: dict, modes: list[str]) -> None:
    print("\n== Per page ==")
    header = f"{'page':58s} {'set':12s} {'edit':>6s} {'rhy':>5s} {'val':>5s} {'pF1':>5s}"
    for mode in modes:
        header += (
            f" | {mode[:4]} {'MV2H':>5s} {'MP':>5s} {'Vo':>5s} {'Me':>5s} {'Va':>5s} {'Ha':>5s}"
        )
    print(header + "  shift clock  bpm drift")
    for name in sorted(rows, key=lambda n: (rows[n]["set"], n)):
        row = rows[name]
        pf1 = row.get("pitch_f1")
        pf1 = float("nan") if pf1 is None else pf1
        line = (
            f"{run_eval.pin_name(name)[:58]:58s} {row['set']:12s} {row['edit_cost']:6.1f} "
            f"{row['rhythm']:5.3f} {row['value']:5.3f} {pf1:5.3f}"
        )
        for mode in modes:
            result = row.get(mode, {})
            if "error" in result or not result:
                line += f" | {'ERR':>10s}{'':30s}"
            else:
                line += f" | {'':4s} " + " ".join(
                    f"{result[f]:5.3f}" for f in COMPONENTS[-1:] + COMPONENTS[:-1]
                )
        drift = row["pin_drift"]
        bpm = row.get("bpm") or float("nan")
        line += (
            f"  {row['shift']:+6.0f} {row['on_clock']:.2f} {bpm:4.0f}"
            f" {drift if drift is not None else '-'}"
        )
        print(line)

    print("\n== Set means (95% bootstrap interval over pages) ==")
    for set_name, entry in summary["sets"].items():
        ours = ", ".join(f"{f} {entry[f]}" for f in (*OURS, "pitch_f1") if f in entry)
        print(f"\n{SET_TITLES[set_name]} ({entry['n_pages']} pages; ours: {ours})")
        for mode in modes:
            block = entry.get(mode, {})
            cells = "  ".join(
                f"{f} {block[f][0]:.3f} [{block[f][1]:.3f}, {block[f][2]:.3f}]"
                for f in REPORTED
                if f in block
            )
            print(f"  {mode:10s} n={block.get('n', 0):2d}  {cells}")

    print("\n== Spearman rho across pages (95% bootstrap interval) ==")
    for pool, table in summary["correlations"].items():
        print(f"\n{pool} (n={table['n']})")
        for key, cell in table.items():
            if key == "n":
                continue
            if key.endswith("~constant"):
                print(f"  {key.split('~')[0]:26s} {cell[0]:.3f} on every page: no rank")
                continue
            rho, low, high = cell
            print(f"  {key:26s} {rho:+.3f} [{low:+.3f}, {high:+.3f}]")

    if summary["pianists"]:
        print("\n== Pianists: oracle line against the CREPE line, paired ==")
        for mode, entry in summary["pianists"].items():
            print(f"  {mode}: {json.dumps(entry)}")


if __name__ == "__main__":
    main()
