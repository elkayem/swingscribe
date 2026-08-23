"""HTTP surface for the selection/audition GUI (plan §13, screens 1-3).

Deliberately thin. Every interaction that has to feel instant — dragging a loop
point, nudging it a tenth of a second, soloing a stem, tapping A while the music
plays — happens in the browser. The server only does things the browser cannot:
find files, read peaks off a wav, cut a span out of a stem, and run Demucs.

That division is also what keeps the eventual Hugging Face Space cheap: this
module is an adapter over pipeline.run and Config, not a second brain. Anything
resembling pipeline logic belongs in a stage, not here.
"""

import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from swingscribe.config import Config
from swingscribe.gui import audio as gui_audio
from swingscribe.gui import jobs as gui_jobs
from swingscribe.gui import library, peaks

STATIC_DIR = Path(__file__).parent / "static"


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
        remembered = library.load_state(config, track_id).get("path")
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
        library.save_state(config, track_id, {"path": entry["path"], "opened_at": time.time()})
        return entry

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
            "state": library.load_state(config, track_id),
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

    # ── separation jobs ─────────────────────────────────────────────────────

    @app.post("/api/jobs")
    def post_job(request: JobRequest) -> dict[str, Any]:
        if request.model not in config.gui.models:
            raise HTTPException(400, f"unknown model {request.model!r}")
        open_track(request.path)  # decode errors surface now, not in the worker
        return app.state.runner.submit(request.path, config, request.model).snapshot()

    @app.get("/api/jobs")
    def get_jobs() -> dict[str, Any]:
        return {"jobs": app.state.runner.all()}

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        job = app.state.runner.get(job_id)
        if job is None:
            raise HTTPException(404, f"unknown job {job_id!r}")
        return job.snapshot()

    # ── remembered state ────────────────────────────────────────────────────

    @app.post("/api/tracks/{track_id}/state")
    def post_state(track_id: str, request: StateRequest) -> dict[str, Any]:
        library.save_state(config, track_id, request.state)
        return library.load_state(config, track_id)

    return app
