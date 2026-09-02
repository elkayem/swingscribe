"""Background pipeline jobs (separation, beat tracking) with real progress.

Separation is 6-13 minutes on this machine's CPU, which is far too long to hold
a request open and far too long to show a spinner for. So it runs on a worker
thread and the browser polls for progress.

Polling, not server-sent events, on purpose: a ten-minute job polled once a
second is 600 trivial requests to localhost, against which SSE would buy us
reconnect logic, proxy-buffering quirks and a streaming generator to get wrong.

One worker, deliberately. Two Demucs runs on the same CPU do not finish in half
the time; they finish in twice the time each and make the machine unusable
meanwhile.
"""

import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from swingscribe import progress
from swingscribe.config import Config

# Stages each job kind walks through, and roughly what share of the wall clock
# each takes. Ingest is seconds and separation is minutes, so a naive
# "N stages, 1/N each" bar would sit at 50% for most of a job.
#
# A beats job used to include separation, because beat tracking wanted the drum
# stem. It no longer does — the mix tracks better as well as faster
# (stages/beats.py) — so this is now ingest plus a few seconds of beat_this,
# and the button returns before a separation would have finished loading its
# first model.
JOB_STAGES: dict[str, tuple[tuple[str, float], ...]] = {
    "separate": (("ingest", 0.04), ("separate", 0.96)),
    "beats": (("ingest", 0.25), ("beats", 0.75)),
    # Transcription runs on an already-separated stem, so this is the CREPE pass
    # alone — ~30s for a span, not minutes.
    "transcribe": (("transcribe", 1.0),),
}


@dataclass
class Job:
    id: str
    path: str
    model: str
    kind: str = "separate"  # separate | beats | transcribe
    # Distinguishes otherwise-identical jobs: two transcriptions of different
    # spans must not dedupe onto each other. Empty for whole-file work.
    variant: str = ""
    state: str = "queued"  # queued | running | done | error | cancelled
    stage: str = ""
    fraction: float = 0.0
    message: str = ""
    error: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    stems: list[str] = field(default_factory=list)
    # Kind-specific completion info, e.g. {"notes": 137} for a transcribe job.
    result: dict[str, Any] = field(default_factory=dict)
    # Predicted wall-clock seconds for the whole job (separations only), from
    # gui/timings — what the listener saw before deciding to wait.
    estimate_s: float | None = None
    # Seconds of audio the separator was given, for teaching the estimate.
    audio_seconds: float | None = None
    cancel_requested: bool = False

    def remaining_s(self, now: float | None = None) -> float | None:
        """Seconds left, from measured progress when the stage reports it (a
        demucs bag does) and from the estimate when it does not (the Roformer
        cannot) — the estimate counting down, never below zero."""
        if self.state != "running":
            return None
        elapsed = (now or time.time()) - self.started_at
        if self.fraction >= 0.15:
            return max(0.0, elapsed * (1.0 - self.fraction) / self.fraction)
        if self.estimate_s is not None:
            return max(0.0, self.estimate_s - elapsed)
        return None

    def snapshot(self) -> dict[str, Any]:
        now = time.time()
        elapsed = (self.finished_at or now) - self.started_at
        remaining = self.remaining_s(now)
        return {
            "id": self.id,
            "path": self.path,
            "model": self.model,
            "kind": self.kind,
            "state": self.state,
            "stage": self.stage,
            "fraction": round(self.fraction, 4),
            "message": self.message,
            "error": self.error,
            "elapsed": round(elapsed, 1),
            "estimate": None if self.estimate_s is None else round(self.estimate_s, 1),
            "remaining": None if remaining is None else round(remaining, 1),
            "cancel_requested": self.cancel_requested,
            "stems": self.stems,
            "result": self.result,
        }


class JobCancelled(Exception):
    """Raised inside a worker when the listener cancelled the job."""


def _separation_worker(path: str, config_json: str, model: str, queue) -> None:
    """The body of a separate job, in its own PROCESS (see JobRunner.cancel).
    Module-level so the spawn start method can import it; progress events go
    back over the queue because a ContextVar sink does not cross processes."""
    from swingscribe import pipeline, progress
    from swingscribe.config import Config
    from swingscribe.stages import ingest, separate

    config = Config.model_validate_json(config_json)
    run_config = config.model_copy(
        update={"separate": config.separate.model_copy(update={"model": model})}
    )

    def forward(event: progress.ProgressEvent) -> None:
        queue.put(("progress", event.stage, event.fraction, event.message, event.cached))

    try:
        with progress.sink(forward):
            pipeline.run(
                path, run_config, stages=[("ingest", ingest.run), ("separate", separate.run)]
            )
        queue.put(("done",))
    except Exception as exc:  # reported to the parent, which raises it there
        queue.put(("error", f"{type(exc).__name__}: {exc}"))


def _idle_worker(path: str, config_json: str, model: str, queue) -> None:
    """A worker that only waits — what a cancel test cancels."""
    queue.put(("progress", "separate", 0.05, "idling", False))
    time.sleep(60)
    queue.put(("done",))


# Job kinds that must not queue behind a separation. Beat tracking is ~8
# seconds and needs no stems at all; on a single worker it sat behind an
# eleven-minute demucs run, which is indistinguishable from beat tracking
# being slow and is why "the Beats button takes forever" survived making beat
# tracking fast.
#
# Two single-worker lanes rather than a wider pool: at most one separation and
# one cheap job run at once, so a second demucs cannot start and halve the
# first one's cores. Everything unlisted is heavy by default — a new job kind
# should have to argue that it is cheap.
LIGHT_KINDS = frozenset({"beats", "transcribe"})


class JobRunner:
    """Runs pipeline work off the request thread and reports progress."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}
        self._by_target: dict[tuple[str, str, str], str] = {}  # (path, model, kind)
        self._heavy = ThreadPoolExecutor(max_workers=1, thread_name_prefix="swingscribe-heavy")
        self._light = ThreadPoolExecutor(max_workers=1, thread_name_prefix="swingscribe-light")
        # The separation body, swapped for `_idle_worker` by the cancel test.
        self._worker = _separation_worker

    def cancel(self, job_id: str) -> Job | None:
        """Ask a queued or running job to stop. A separation runs in a child
        process (see `_run_separation`) and is terminated within a second; a
        job that has not started is marked cancelled when its turn comes."""
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            return None
        if job.state in ("queued", "running"):
            job.cancel_requested = True
        return job

    def _pool_for(self, kind: str) -> ThreadPoolExecutor:
        return self._light if kind in LIGHT_KINDS else self._heavy

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def active_for(
        self, path: str, model: str, kind: str = "separate", variant: str = ""
    ) -> Job | None:
        """An unfinished job already doing this exact work.

        Guards against a double-click costing minutes twice. `variant` keeps two
        transcriptions of different spans from colliding on one another.
        """
        with self._lock:
            job_id = self._by_target.get((str(path), model, kind, variant))
            job = self._jobs.get(job_id) if job_id else None
        return job if job and job.state in ("queued", "running") else None

    def all(self) -> list[dict[str, Any]]:
        with self._lock:
            return [job.snapshot() for job in self._jobs.values()]

    def submit(
        self,
        path: str | Path,
        config: Config,
        model: str,
        kind: str = "separate",
        variant: str = "",
        estimate_s: float | None = None,
        audio_seconds: float | None = None,
    ) -> Job:
        if kind not in JOB_STAGES:
            raise ValueError(f"unknown job kind {kind!r}")
        existing = self.active_for(str(path), model, kind, variant)
        if existing is not None:
            return existing
        job = Job(
            id=uuid.uuid4().hex[:12],
            path=str(path),
            model=model,
            kind=kind,
            variant=variant,
            estimate_s=estimate_s,
            audio_seconds=audio_seconds,
        )
        with self._lock:
            self._jobs[job.id] = job
            self._by_target[(job.path, model, kind, variant)] = job.id
        future: Future = self._pool_for(kind).submit(self._run, job, config, model)
        future.add_done_callback(lambda _f: None)
        return job

    # ── worker ──────────────────────────────────────────────────────────────

    def _run(self, job: Job, config: Config, model: str) -> None:
        if job.cancel_requested:
            job.state, job.message, job.finished_at = "cancelled", "cancelled", time.time()
            return
        job.state = "running"
        job.started_at = time.time()  # queue time is not work time
        # The sink is installed *inside* the worker thread: progress lives in a
        # ContextVar, which does not cross a thread boundary on its own.
        try:
            with progress.sink(lambda event: self._on_progress(job, event)):
                if job.kind == "transcribe":
                    self._run_transcribe(job, config, model)
                elif job.kind == "separate":
                    self._run_separation(job, config, model)
                else:
                    self._run_beats(job, config, model)
            job.state = "done"
            job.fraction = 1.0
        except JobCancelled:
            job.state = "cancelled"
            job.message = "cancelled"
        except Exception as exc:  # surfaced to the UI, never swallowed
            job.state = "error"
            job.error = f"{type(exc).__name__}: {exc}"
            job.message = "failed"
        finally:
            job.finished_at = time.time()

    def _run_beats(self, job: Job, config: Config, model: str) -> None:
        from swingscribe import pipeline
        from swingscribe.stages import beats, ingest

        run_config = config.model_copy(
            update={"separate": config.separate.model_copy(update={"model": model})}
        )
        # Beats needs no stems, so a beats job must not queue a separation it
        # would only wait on. This list is not a prefix of pipeline.STAGES
        # (which runs beats between ingest and separate), so the full pipeline
        # looks these stage outputs up under different keys and recomputes
        # them — seconds.
        pipeline.run(job.path, run_config, stages=[("ingest", ingest.run), ("beats", beats.run)])
        job.message = "beat grid ready"

    def _run_separation(self, job: Job, config: Config, model: str) -> None:
        """Separate in a CHILD PROCESS, so the listener can cancel it.

        A torch computation cannot be interrupted from another thread, and
        the Roformer path has no callback to hook, so cancellation means
        terminating the process that runs it. Progress comes back over a
        queue; the parent thread relays it, watches for the cancel flag, and
        reads the finished stems from disk afterwards exactly as a job in
        this process would have.
        """
        import multiprocessing
        from queue import Empty

        from swingscribe.gui import library, timings

        run_config = config.model_copy(
            update={"separate": config.separate.model_copy(update={"model": model})}
        )
        span = run_config.separate.span
        context = multiprocessing.get_context("spawn")
        queue = context.Queue()
        process = context.Process(
            target=self._worker,
            args=(job.path, run_config.model_dump_json(), model, queue),
            daemon=True,
        )
        process.start()
        separated = False  # did the separator actually run, or reuse stems?
        try:
            while True:
                if job.cancel_requested:
                    process.terminate()
                    process.join(5)
                    raise JobCancelled()
                try:
                    message = queue.get(timeout=0.5)
                except Empty:
                    if not process.is_alive():
                        raise RuntimeError(
                            "the separation worker exited without reporting"
                        ) from None
                    continue
                if message[0] == "progress":
                    _kind, stage, fraction, text, cached = message
                    if stage == "separate" and not cached:
                        separated = True
                    self._on_progress(
                        job,
                        progress.ProgressEvent(
                            stage=stage, fraction=fraction, message=text, cached=cached
                        ),
                    )
                elif message[0] == "error":
                    raise RuntimeError(message[1])
                elif message[0] == "done":
                    break
        finally:
            if process.is_alive():
                process.terminate()
            process.join(5)

        document = library.ingested_document(job.path, run_config)
        job.stems = library.selectable_stems(document, run_config, model, span)
        job.message = "stems ready"
        if separated and job.audio_seconds:
            # Teach the estimate this machine's speed — only from a run that
            # did the work, never from one that found the stems on disk.
            timings.record(
                run_config.cache_dir, model, job.audio_seconds, time.time() - job.started_at
            )

    def _run_transcribe(self, job: Job, config: Config, model: str) -> None:
        """Transcribe the configured span (in config.transcribe) and cache the
        notes + diagnostics under gui/. The stem is already separated, so this
        is the CREPE pass only. `config` already carries the span, stem and any
        gate thresholds — the caller folded them in before submitting."""
        from swingscribe.gui import library, review

        run_config = config.model_copy(
            update={"separate": config.separate.model_copy(update={"model": model})}
        )
        document = library.ingested_document(job.path, run_config)
        payload = review.analyze_and_cache(document, run_config, model)
        job.result = {"notes": len(payload["notes"])}
        job.message = f"{len(payload['notes'])} notes"

    def _on_progress(self, job: Job, event: progress.ProgressEvent) -> None:
        """Map a stage-local fraction onto the whole job's bar."""
        offset = 0.0
        weight = None
        for name, share in JOB_STAGES[job.kind]:
            if name == event.stage:
                weight = share
                break
            offset += share
        if weight is None:
            # A stage this job kind doesn't own — e.g. the cached ingest that a
            # transcribe job runs as a precondition. Not part of this bar, so
            # leave the fraction alone rather than letting it run past 100%.
            return
        within = 1.0 if event.fraction is None else event.fraction
        job.stage = event.stage
        job.fraction = max(job.fraction, offset + weight * within)
        if event.cached:
            job.message = f"{event.stage}: cached"
        elif event.message:
            job.message = f"{event.stage}: {event.message}"
