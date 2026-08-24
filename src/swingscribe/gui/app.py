"""HTTP surface for the selection/audition GUI (plan §13, screens 1-3).

Deliberately thin. Every interaction that has to feel instant — dragging a loop
point, nudging it a tenth of a second, soloing a stem, tapping A while the music
plays — happens in the browser. The server only does things the browser cannot:
find files, read peaks off a wav, cut a span out of a stem, and run Demucs.

That division is also what keeps the eventual Hugging Face Space cheap: this
module is an adapter over pipeline.run and Config, not a second brain. Anything
resembling pipeline logic belongs in a stage, not here.
"""

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from swingscribe.config import Config
from swingscribe.gui import audio as gui_audio
from swingscribe.gui import ground_truth, library, peaks, review
from swingscribe.gui import jobs as gui_jobs
from swingscribe.model import NoteEvent

STATIC_DIR = Path(__file__).parent / "static"

# Decimal places span bounds are rounded to before they reach a cache key.
# Milliseconds are finer than any boundary a person places by ear.
SPAN_PRECISION = 3


class RevalidatingStatic(StaticFiles):
    """Static assets that must be revalidated on every load.

    Without this the browser happily serves a cached app.js after an upgrade —
    or after an edit, which turns every front-end change into a confusing
    hunt for a bug that is already fixed. Revalidation, not no-store: a 304 on
    an unchanged file is still cheap over localhost.
    """

    def is_not_modified(self, response_headers, request_headers) -> bool:
        response_headers["cache-control"] = "no-cache"
        return super().is_not_modified(response_headers, request_headers)

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["cache-control"] = "no-cache"
        return response


class OpenRequest(BaseModel):
    path: str


class JobRequest(BaseModel):
    path: str
    model: str
    kind: str = "separate"  # separate | beats | transcribe — see gui_jobs.JOB_STAGES
    # Transcribe jobs need the span and the lead stem; ignored for the others.
    stem: str | None = None
    start: float | None = None
    end: float | None = None


class StateRequest(BaseModel):
    """Whatever screens 1-3 want remembered. Free-form on purpose: this is UI
    state, it never feeds a cache key, and pinning its shape here would mean a
    server change every time the front end remembers one more thing."""

    state: dict[str, Any]


def create_app(config: Config) -> FastAPI:
    app = FastAPI(title="SwingScribe", docs_url=None, redoc_url=None)
    app.state.config = config
    app.state.runner = gui_jobs.JobRunner()
    app.state.tracks = {}  # track id -> {"path", "document"}

    def resolve(track_id: str) -> dict[str, Any]:
        """Track id -> its open record, reopening it if the server restarted.

        The sidecar remembers the source path, so a reload of the page after a
        restart recovers rather than dead-ending on an unknown id.
        """
        entry = app.state.tracks.get(track_id)
        if entry is not None:
            return entry
        remembered = library.remembered_path(config, track_id)
        if remembered and Path(remembered).is_file():
            return open_track(remembered)
        raise HTTPException(404, f"unknown track {track_id!r}; open it again")

    def open_track(path: str) -> dict[str, Any]:
        source = Path(path).expanduser()
        if not source.is_file():
            raise HTTPException(404, f"no such file: {source}")
        if source.suffix.lower() not in library.AUDIO_SUFFIXES:
            raise HTTPException(400, f"not an audio file: {source.name}")
        try:
            document = library.ingested_document(source, config)
        except Exception as exc:
            raise HTTPException(422, f"could not decode {source.name}: {exc}") from exc
        track_id = library.file_digest(source)
        entry = {"path": str(source.resolve()), "document": document}
        app.state.tracks[track_id] = entry
        library.remember_open(config, track_id, entry["path"])
        return entry

    def review_config(stem: str, start: float | None, end: float | None) -> Config:
        """Base config with the review span and lead stem folded into transcribe.

        Region is stored as (start, end|None); a null start means from zero.
        This is the single place the GUI turns a span selection into the exact
        transcribe config whose hash keys the cached review.

        Span bounds are rounded to the millisecond HERE rather than trusted from
        the caller. The key is a hash of this config, so 60.0637 and "60.064"
        are different spans as far as the cache is concerned — and the job POST
        and the review GET would otherwise disagree in the last decimal place
        and never find each other's work. Canonicalising server-side means no
        client has to get its rounding right.
        """
        span = SPAN_PRECISION
        region = (
            None
            if start is None and end is None
            else (round(start or 0.0, span), None if end is None else round(end, span))
        )
        return config.model_copy(
            update={
                "transcribe": config.transcribe.model_copy(update={"stem": stem, "region": region})
            }
        )

    # ── pages and assets ────────────────────────────────────────────────────

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        return HTMLResponse(
            (STATIC_DIR / "index.html").read_text(encoding="utf-8"),
            headers={"Cache-Control": "no-cache"},
        )

    app.mount("/static", RevalidatingStatic(directory=STATIC_DIR), name="static")

    # ── library ─────────────────────────────────────────────────────────────

    @app.get("/api/config")
    def get_config() -> dict[str, Any]:
        return {
            "models": config.gui.models,
            "default_model": config.separate.model,
            "default_stem": config.transcribe.stem,
            "library_dir": str(library.library_dir(config)),
        }

    @app.get("/api/tracks")
    def get_tracks() -> dict[str, Any]:
        return {"library": library.list_tracks(config), "recent": library.recent_tracks(config)}

    @app.get("/api/browse")
    def get_browse(path: str | None = None) -> dict[str, Any]:
        try:
            return library.browse(path, config)
        except (NotADirectoryError, FileNotFoundError, PermissionError) as exc:
            raise HTTPException(400, f"cannot open {path or '(library folder)'}: {exc}") from exc

    @app.post("/api/tracks/open")
    def post_open(request: OpenRequest) -> dict[str, Any]:
        entry = open_track(request.path)
        document = entry["document"]
        track_id = library.file_digest(entry["path"])
        assert document.audio is not None  # ingest guarantees this or raises
        return {
            "id": track_id,
            "name": Path(entry["path"]).name,
            "path": entry["path"],
            "duration": document.audio.duration,
            "sample_rate": document.audio.sample_rate,
            "models": library.model_status(document, config),
            "state": library.load_settings(entry["path"], config, track_id),
            "settings_path": str(library.settings_path(entry["path"])),
        }

    @app.get("/api/tracks/{track_id}/peaks")
    def get_peaks(
        track_id: str,
        start: float | None = None,
        end: float | None = None,
        buckets: int = peaks.DETAIL_BUCKETS,
        stem: str | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Envelope of the mix, or of one stem when `stem`+`model` are given.

        The stem case is what lets the audition screen draw the isolated
        instrument over the original: you can see what separation removed
        before you have heard a note of it.
        """
        entry = resolve(track_id)
        document = entry["document"]
        source = document.audio.path
        if stem is not None and stem != "mix":
            stems = library.available_stems(document, config, model or config.separate.model)
            if stem not in stems:
                raise HTTPException(404, f"no {stem!r} stem for {model}")
            source = stems[stem]
        if start is None and end is None and stem is None:
            return peaks.overview(source, config.cache_dir, track_id)
        return peaks.envelope(source, buckets, start or 0.0, end)

    @app.get("/api/tracks/{track_id}/audio")
    def get_audio(track_id: str) -> FileResponse:
        """The normalized mix, for screens 1-2. Starlette handles Range here,
        which is what makes seeking in a five-minute file feel instant."""
        entry = resolve(track_id)
        return FileResponse(entry["document"].audio.path, media_type="audio/wav")

    @app.get("/api/tracks/{track_id}/stems")
    def get_stems(track_id: str, model: str | None = None) -> dict[str, Any]:
        entry = resolve(track_id)
        document = entry["document"]
        if model is None:
            return {"models": library.model_status(document, config)}
        return {
            "model": model,
            "stems": sorted(library.available_stems(document, config, model)),
        }

    @app.get("/api/tracks/{track_id}/stem")
    def get_stem_slice(
        track_id: str,
        stem: str,
        model: str,
        start: float = 0.0,
        end: float | None = None,
        rate: float = 1.0,
        download: bool = False,
    ) -> Response:
        """One span of one stem as a wav — what screen 3 actually plays.

        `mix` is not a separated stem but the normalized original, so the same
        endpoint serves the A/B reference and it arrives stretched by the same
        code path as everything else (and therefore still aligned with it).
        """
        entry = resolve(track_id)
        document = entry["document"]
        if stem == "mix":
            source = document.audio.path
        else:
            stems = library.available_stems(document, config, model)
            if stem not in stems:
                raise HTTPException(
                    404,
                    f"no {stem!r} stem for {model}; separate it first "
                    f"(available: {', '.join(sorted(stems)) or 'none'})",
                )
            source = stems[stem]
        try:
            payload = gui_audio.slice_wav(source, start, end, rate)
        except Exception as exc:
            raise HTTPException(500, f"could not slice {stem}: {exc}") from exc

        headers = {"Cache-Control": "no-store"}
        if download:
            name = Path(entry["path"]).stem
            span = f"{start:.1f}-{end:.1f}s" if end is not None else "full"
            headers["Content-Disposition"] = f'attachment; filename="{name}.{stem}.{span}.wav"'
        return Response(content=payload, media_type="audio/wav", headers=headers)

    @app.get("/api/tracks/{track_id}/beats")
    def get_beats(
        track_id: str,
        model: str | None = None,
        time_signature: str | None = None,
        pulses_per_bar: int | None = None,
        anchor: float | None = None,
        bars_per_chorus: int | None = None,
        form_start: float | None = None,
    ) -> dict[str, Any]:
        """The bar grid for this track+model, or ready:false.

        Never computes the beat grid: beat tracking (and the separation it
        chains from) can cost minutes, and "draw the bars if they're free" must
        not be a call that might block. When this says not ready, the client
        starts a kind="beats" job and asks again.

        The *meter* on top of it is re-derived here on every call, because that
        is microseconds of pure arithmetic (stages/meter.py). So the query
        parameters let the GUI preview any downbeat or time signature instantly,
        with no job, no cache write, and no config edit — while the identical
        functions run inside the pipeline for the transcription itself.
        """
        from swingscribe import pipeline
        from swingscribe.stages import beats, ingest, meter, separate

        entry = resolve(track_id)
        run_config = config.model_copy(
            update={
                "separate": config.separate.model_copy(
                    update={"model": model or config.separate.model}
                )
            }
        )
        document = pipeline.cached_document(
            entry["path"],
            run_config,
            stages=[("ingest", ingest.run), ("separate", separate.run), ("beats", beats.run)],
        )
        grid = document.beat_grid if document else None
        if grid is None or not grid.beats:
            return {"ready": False}

        overrides = {
            key: value
            for key, value in {
                "time_signature": time_signature,
                "pulses_per_bar": pulses_per_bar,
                "anchor": anchor,
                "bars_per_chorus": bars_per_chorus,
                "form_start": form_start,
            }.items()
            if value is not None
        }
        meter_config = config.meter.model_copy(update=overrides)
        try:
            signature, pulses = meter.resolve_meter(meter_config)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

        duration = entry["document"].audio.duration
        repaired = meter.repair_beats(grid.beats, meter_config)
        repaired = meter.extend_beats(repaired, meter_config, 0.0, duration)
        sections = meter.derive_sections(repaired, grid.downbeats, meter_config)
        lines = meter.bar_lines(repaired, sections, meter_config.form_start)

        intervals = sorted(
            b.time - a.time for a, b in zip(repaired, repaired[1:], strict=False) if b.time > a.time
        )
        median_bpm = 60.0 / intervals[len(intervals) // 2] if intervals else 0.0
        chorus = meter_config.bars_per_chorus or 0
        # Time the bar grid does not cover, so the UI can say how much free time
        # there is and where — "free time" as a bare label reads as a claim about
        # the whole tune.
        free = []
        cursor = 0.0
        for section in sections:
            if section.start - cursor > 0.5:
                free.append([round(cursor, 2), round(section.start, 2)])
            cursor = max(cursor, section.end)
        if duration - cursor > 0.5:
            free.append([round(cursor, 2), round(duration, 2)])

        return {
            "ready": True,
            "beats": [round(b.time, 3) for b in repaired],
            "implied": [b.implied for b in repaired],
            "bars": [[round(t, 3), number] for t, number in lines],
            "free": free,
            "chorus_bars": (
                [round(t, 3) for t, number in lines if number >= 1 and (number - 1) % chorus == 0]
                if chorus > 1
                else []
            ),
            "sections": [
                {
                    "start": round(section.start, 3),
                    "end": round(section.end, 3),
                    "first_bar": section.first_bar,
                    "confidence": section.confidence,
                }
                for section in sections
            ],
            "time_signature": f"{signature[0]}/{signature[1]}",
            "pulses_per_bar": pulses,
            "anchor": round(sections[0].anchor, 3) if sections else None,
            "form_start": meter_config.form_start,
            "bpm": round(median_bpm, 1),
            "known_signatures": list(meter.TIME_SIGNATURES),
        }

    @app.get("/api/tracks/{track_id}/review")
    def get_review(
        track_id: str,
        model: str,
        stem: str,
        start: float | None = None,
        end: float | None = None,
    ) -> dict[str, Any]:
        """The cached transcription review for this span, or ready:false.

        Never transcribes: the CREPE pass costs ~30s, so "show the notes if
        they're ready" must not block. When not ready the client starts a
        kind=transcribe job and asks again. The frame diagnostics ride along —
        this endpoint is the only thing that serves them.
        """
        entry = resolve(track_id)
        run_config = review_config(stem, start, end)
        payload = review.cached_review(entry["document"], run_config, model)
        if payload is None:
            return {"ready": False}
        return {"ready": True, **payload}

    @app.get("/api/tracks/{track_id}/transcription")
    def get_transcription(
        track_id: str,
        model: str,
        stem: str,
        start: float = 0.0,
        end: float | None = None,
        rate: float = 1.0,
    ) -> Response:
        """The synthesized transcription for the span, as a wav.

        The review screen loads this as one more source in the sample-locked
        engine, so original-vs-transcription switches mid-phrase stay aligned —
        the same guarantee the audition mixer gives. Reads the cached notes;
        404 if the span has not been transcribed yet.
        """
        entry = resolve(track_id)
        document = entry["document"]
        run_config = review_config(stem, start, end)
        payload = review.cached_review(document, run_config, model)
        if payload is None:
            raise HTTPException(404, "not transcribed yet")
        notes = [NoteEvent(source=stem, **n) for n in payload["notes"]]
        resolved_end = document.audio.duration if end is None else end
        try:
            audio = gui_audio.render_transcription(
                notes, start, resolved_end, document.audio.sample_rate, rate
            )
        except Exception as exc:
            raise HTTPException(500, f"could not render transcription: {exc}") from exc
        return Response(
            content=audio, media_type="audio/wav", headers={"Cache-Control": "no-store"}
        )

    # ── ground truth ────────────────────────────────────────────────────────

    @app.get("/api/tracks/{track_id}/scores")
    def get_scores(track_id: str) -> dict[str, Any]:
        """Hand transcriptions sitting beside this track, best name match first.

        Only a suggestion: the folder browser reaches anywhere, and benchmark
        folders hold several tunes at once. See ground_truth.nearby_scores.
        """
        entry = resolve(track_id)
        return {"scores": ground_truth.nearby_scores(entry["path"])}

    @app.get("/api/tracks/{track_id}/ground-truth")
    def get_ground_truth(
        track_id: str,
        model: str,
        stem: str,
        score: str,
        start: float | None = None,
        end: float | None = None,
    ) -> dict[str, Any]:
        """A notated score aligned against this span's transcription.

        Needs the transcription first — the alignment is *to* our notes, and
        their onsets are what places the score horizontally (ground_truth's
        module docstring). 404 rather than transcribing: this endpoint must
        stay as cheap to poll as /review.
        """
        entry = resolve(track_id)
        document = entry["document"]
        score_path = Path(score).expanduser()
        if not score_path.is_file():
            raise HTTPException(404, f"no such score: {score_path}")
        if not ground_truth.is_score(score_path):
            raise HTTPException(400, f"not a MuseScore file: {score_path.name}")

        run_config = review_config(stem, start, end)
        payload = review.cached_review(document, run_config, model)
        if payload is None:
            raise HTTPException(404, "transcribe the span first")
        lo, hi = run_config.transcribe.region or (0.0, None)
        try:
            overlay = ground_truth.cached_overlay(
                config,
                review.review_key(document, run_config, model),
                score_path,
                payload["notes"],
                lo or 0.0,
                document.audio.duration if hi is None else hi,
            )
        except Exception as exc:
            raise HTTPException(422, f"could not read {score_path.name}: {exc}") from exc
        return overlay

    # ── pipeline jobs ───────────────────────────────────────────────────────

    @app.post("/api/jobs")
    def post_job(request: JobRequest) -> dict[str, Any]:
        if request.model not in config.gui.models:
            raise HTTPException(400, f"unknown model {request.model!r}")
        if request.kind not in gui_jobs.JOB_STAGES:
            raise HTTPException(400, f"unknown job kind {request.kind!r}")
        entry = open_track(request.path)  # decode errors surface now, not in the worker
        if request.kind == "transcribe":
            if not request.stem:
                raise HTTPException(400, "a transcribe job needs a stem")
            run_config = review_config(request.stem, request.start, request.end)
            # variant keys the job (and its cache) to this exact span+stem+config,
            # so two spans never dedupe onto each other.
            variant = review.review_key(entry["document"], run_config, request.model)
            job = app.state.runner.submit(
                request.path, run_config, request.model, "transcribe", variant
            )
        else:
            job = app.state.runner.submit(request.path, config, request.model, request.kind)
        return job.snapshot()

    @app.get("/api/jobs")
    def get_jobs() -> dict[str, Any]:
        return {"jobs": app.state.runner.all()}

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        job = app.state.runner.get(job_id)
        if job is None:
            raise HTTPException(404, f"unknown job {job_id!r}")
        return job.snapshot()

    # ── remembered settings ────────────────────────────────────────────────────

    @app.post("/api/tracks/{track_id}/state")
    def post_state(track_id: str, request: StateRequest) -> dict[str, Any]:
        entry = resolve(track_id)
        written = library.save_settings(entry["path"], request.state, config)
        return {
            "settings": library.load_settings(entry["path"], config, track_id),
            "settings_path": str(written),
        }

    return app
