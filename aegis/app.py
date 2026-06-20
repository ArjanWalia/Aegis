"""FastAPI application: the Aegis web app.

Routes
------
* ``GET  /``             — the single-page control UI.
* ``GET  /video_feed``   — MJPEG stream of annotated frames.
* ``GET  /api/labels``   — class labels the CNN can recognise.
* ``GET  /api/status``   — live JSON status (polled by the UI).
* ``POST /api/target``   — set the item to track ``{"target": "bottle"}``.
* ``POST /api/engage``   — arm the motors (start pointing).
* ``POST /api/stop``     — disarm the motors (stop pointing).
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles

from .camera import make_camera
from .config import load_config
from .controller import Tracker
from .detector import make_detector
from .robot import make_arm

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("aegis.app")

WEB_DIR = Path(__file__).parent / "web"


def create_app() -> FastAPI:
    config = load_config()
    app = FastAPI(title="Aegis — SO-ARM101 Object Tracker")
    app.state.config = config
    app.state.tracker = None

    @app.on_event("startup")
    def _startup() -> None:
        log.info("Starting Aegis (mock_all=%s, strict=%s)",
                 config.mock_all, config.strict)
        camera = make_camera(config)
        detector = make_detector(config)
        arm = make_arm(config)
        tracker = Tracker(camera, detector, arm, config)
        tracker.start()
        app.state.tracker = tracker

    @app.on_event("shutdown")
    def _shutdown() -> None:
        if app.state.tracker is not None:
            app.state.tracker.stop()

    # -- pages --------------------------------------------------------------
    @app.get("/")
    def index():
        return FileResponse(WEB_DIR / "index.html")

    # -- video stream -------------------------------------------------------
    @app.get("/video_feed")
    def video_feed():
        tracker: Tracker = app.state.tracker
        fps = max(1, config.stream_fps)

        def gen():
            boundary = b"--frame\r\n"
            while True:
                jpeg = tracker.get_jpeg() if tracker else None
                if jpeg is None:
                    time.sleep(0.05)
                    continue
                yield (boundary +
                       b"Content-Type: image/jpeg\r\n\r\n" +
                       jpeg + b"\r\n")
                time.sleep(1.0 / fps)

        return StreamingResponse(
            gen(), media_type="multipart/x-mixed-replace; boundary=frame"
        )

    # -- API ----------------------------------------------------------------
    @app.get("/api/labels")
    def labels():
        tracker: Tracker = app.state.tracker
        return {"labels": sorted(tracker.labels) if tracker else []}

    @app.get("/api/status")
    def status():
        tracker: Tracker = app.state.tracker
        if tracker is None:
            return JSONResponse({"running": False, "message": "starting"})
        return tracker.get_status()

    @app.post("/api/target")
    async def set_target(request: Request):
        body = await request.json()
        target = (body or {}).get("target", "")
        app.state.tracker.set_target(target)
        return {"ok": True, "target": target}

    @app.post("/api/engage")
    def engage():
        app.state.tracker.arm_tracking()
        return {"ok": True, "armed": True}

    @app.post("/api/stop")
    def stop():
        app.state.tracker.disarm_tracking()
        return {"ok": True, "armed": False}

    # Serve any other static assets (css/js) under /static.
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
    return app


app = create_app()
