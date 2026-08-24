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
# "N stages, 1/N each" bar would sit at 50% for most of a job. A beats job
# includes separation because beat tracking wants the drum stem — usually a
# cache hit that flashes past, but honest when it isn't.
JOB_STAGES: dict[str, tuple[tuple[str, float], ...]] = {
    "separate": (("ingest", 0.04), ("separate", 0.96)),
    "beats": (("ingest", 0.03), ("separate", 0.85), ("beats", 0.12)),
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
    state: str = "queued"  # queued | running | done | error
    stage: str = ""
    fraction: float = 0.0
    message: str = ""
    error: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    stems: list[str] = field(default_factory=list)
    # Kind-specific completion info, e.g. {"notes": 137} for a transcribe job.
    result: dict[str, Any] = field(default_factory=dict)

    def snapshot(self) -> dict[str, Any]:
        elapsed = (self.finished_at or time.time()) - self.started_at
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
            "stems": self.stems,
            "result": self.result,
        }


class JobRunner:
    """Runs pipeline work off the request thread and reports progress."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}
        self._by_target: dict[tuple[str, str, str], str] = {}  # (path, model, kind)
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="swingscribe-job")

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
    ) -> Job:
        if kind not in JOB_STAGES:
            raise ValueError(f"unknown job kind {kind!r}")
        existing = self.active_for(str(path), model, kind, variant)
        if existing is not None:
            return existing
        job = Job(id=uuid.uuid4().hex[:12], path=str(path), model=model, kind=kind, variant=variant)
        with self._lock:
            self._jobs[job.id] = job
            self._by_target[(job.path, model, kind, variant)] = job.id
        future: Future = self._pool.submit(self._run, job, config, model)
        future.add_done_callback(lambda _f: None)
        return job

    # ── worker ──────────────────────────────────────────────────────────────

    def _run(self, job: Job, config: Config, model: str) -> None:
        job.state = "running"
        # The sink is installed *inside* the worker thread: progress lives in a
        # ContextVar, which does not cross a thread boundary on its own.
        try:
            with progress.sink(lambda event: self._on_progress(job, event)):
                if job.kind == "transcribe":
                    self._run_transcribe(job, config, model)
                else:
                    self._run_separation(job, config, model)
            job.state = "done"
            job.fraction = 1.0
        except Exception as exc:  # surfaced to the UI, never swallowed
            job.state = "error"
            job.error = f"{type(exc).__name__}: {exc}"
            job.message = "failed"
        finally:
            job.finished_at = time.time()

    def _run_separation(self, job: Job, config: Config, model: str) -> None:
        from swingscribe import pipeline
        from swingscribe.gui import library
        from swingscribe.stages import beats, ingest, separate

        run_config = config.model_copy(
            update={"separate": config.separate.model_copy(update={"model": model})}
        )
        stage_list = [("ingest", ingest.run), ("separate", separate.run)]
        if job.kind == "beats":
            stage_list.append(("beats", beats.run))
        document = pipeline.run(job.path, run_config, stages=stage_list)
        job.stems = sorted(library.available_stems(document, run_config, model))
        job.message = "beat grid ready" if job.kind == "beats" else "stems ready"

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
