"""The tracking loop: capture -> detect -> match -> point.

A single background thread runs the closed loop at ``config.loop_hz``:

1. grab a frame from the camera;
2. run the CNN detector;
3. pick the highest-confidence detection whose label matches the user target;
4. draw overlays and stash the annotated JPEG for the web stream;
5. if *armed* and a target is visible, compute the pixel error between the
   object centre and the frame centre and drive the pan/tilt joints with a
   proportional controller (visual servoing) so the object stays centred —
   i.e. the arm "locks on" and keeps pointing at it.

Decoupling the loop from the HTTP layer means the MJPEG stream and the JSON
status endpoint just read the latest shared state; they never block control.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import List, Optional

import cv2

from .detector import Detection, label_matches, normalize_label

log = logging.getLogger("aegis.controller")


class Tracker:
    def __init__(self, camera, detector, arm, config):
        self.camera = camera
        self.detector = detector
        self.arm = arm
        self.config = config

        self._target: str = ""
        self._armed: bool = False  # is the arm allowed to move?

        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._lock = threading.Lock()

        self._latest_jpeg: Optional[bytes] = None
        self._status: dict = {
            "running": False,
            "armed": False,
            "target": "",
            "target_visible": False,
            "target_confidence": 0.0,
            "error_x": 0.0,
            "error_y": 0.0,
            "fps": 0.0,
            "detections": [],
            "joints": {},
            "message": "idle",
        }

    # -- lifecycle ----------------------------------------------------------
    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, name="tracker", daemon=True)
        self._thread.start()
        log.info("Tracker thread started.")

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        try:
            self.camera.close()
        finally:
            self.arm.close()
        log.info("Tracker stopped.")

    # -- control surface (called from HTTP handlers) ------------------------
    def set_target(self, label: str) -> None:
        with self._lock:
            self._target = normalize_label(label)
            self._status["target"] = self._target

    def arm_tracking(self) -> None:
        with self._lock:
            self._armed = True

    def disarm_tracking(self) -> None:
        with self._lock:
            self._armed = False

    @property
    def labels(self) -> List[str]:
        return list(getattr(self.detector, "labels", []))

    def get_jpeg(self) -> Optional[bytes]:
        with self._lock:
            return self._latest_jpeg

    def get_status(self) -> dict:
        with self._lock:
            return dict(self._status)

    # -- the loop -----------------------------------------------------------
    def _run(self) -> None:
        period = 1.0 / max(1.0, self.config.loop_hz)
        last = time.time()
        fps = 0.0
        while self._running:
            t0 = time.time()
            try:
                frame = self.camera.read()
            except Exception as exc:  # noqa: BLE001
                log.warning("Camera read failed: %s", exc)
                time.sleep(0.1)
                continue

            with self._lock:
                target = self._target
                armed = self._armed

            detections = self._safe_detect(frame)
            best = self._best_match(detections, target)

            target_visible = best is not None
            err_x = err_y = 0.0
            conf = 0.0
            message = "searching" if target else "enter a target"

            if target_visible:
                conf = best.confidence
                err_x, err_y = self._frame_error(frame, best)
                if armed:
                    self._servo(err_x, err_y)
                    message = "locked on — pointing"
                else:
                    message = "target acquired (press Engage to point)"

            annotated = self._annotate(frame, detections, best, armed, message)
            ok, buf = cv2.imencode(".jpg", annotated,
                                   [cv2.IMWRITE_JPEG_QUALITY, 80])

            # Smooth the measured loop rate a little.
            dt = max(1e-6, time.time() - last)
            last = time.time()
            fps = 0.9 * fps + 0.1 * (1.0 / dt)

            with self._lock:
                if ok:
                    self._latest_jpeg = buf.tobytes()
                self._status.update({
                    "running": True,
                    "armed": armed,
                    "target": target,
                    "target_visible": target_visible,
                    "target_confidence": round(conf, 3),
                    "error_x": round(err_x, 3),
                    "error_y": round(err_y, 3),
                    "fps": round(fps, 1),
                    "detections": [
                        {"label": d.label, "confidence": round(d.confidence, 3)}
                        for d in detections[:12]
                    ],
                    "joints": {k: round(v, 1) for k, v in self.arm.positions().items()},
                    "message": message,
                })

            # Pace the loop.
            sleep = period - (time.time() - t0)
            if sleep > 0:
                time.sleep(sleep)

    # -- helpers ------------------------------------------------------------
    def _safe_detect(self, frame) -> List[Detection]:
        try:
            return self.detector.detect(frame)
        except Exception as exc:  # noqa: BLE001
            log.warning("Detection failed: %s", exc)
            return []

    @staticmethod
    def _best_match(detections: List[Detection], target: str) -> Optional[Detection]:
        if not target:
            return None
        matches = [d for d in detections if label_matches(target, d.label)]
        if not matches:
            return None
        return max(matches, key=lambda d: d.confidence)

    @staticmethod
    def _frame_error(frame, det: Detection):
        """Normalised target offset from frame centre, each axis in [-1, 1]."""
        h, w = frame.shape[:2]
        cx, cy = det.center
        err_x = (cx - w / 2.0) / (w / 2.0)
        err_y = (cy - h / 2.0) / (h / 2.0)
        return err_x, err_y

    def _servo(self, err_x: float, err_y: float) -> None:
        """Proportional pan/tilt correction toward a centred target."""
        cfg = self.config
        dz = cfg.deadzone
        ex = 0.0 if abs(err_x) < dz else err_x
        ey = 0.0 if abs(err_y) < dz else err_y
        if ex == 0.0 and ey == 0.0:
            return  # already centred — hold position (locked on)

        d_pan = cfg.pan_sign * cfg.kp_pan * ex
        d_tilt = cfg.tilt_sign * cfg.kp_tilt * ey
        self.arm.move_relative({
            cfg.pan_joint: d_pan,
            cfg.tilt_joint: d_tilt,
        })

    def _annotate(self, frame, detections, best, armed, message):
        out = frame.copy()
        h, w = out.shape[:2]

        # Centre crosshair (the point the arm tries to align the target with).
        cv2.drawMarker(out, (w // 2, h // 2), (255, 255, 255),
                       cv2.MARKER_CROSS, 24, 1)
        # Deadzone box.
        dz = self.config.deadzone
        cv2.rectangle(out,
                      (int(w / 2 * (1 - dz)), int(h / 2 * (1 - dz))),
                      (int(w / 2 * (1 + dz)), int(h / 2 * (1 + dz))),
                      (160, 160, 160), 1)

        for det in detections:
            x1, y1, x2, y2 = (int(v) for v in det.bbox)
            is_target = det is best
            color = (0, 0, 255) if is_target else (0, 200, 0)
            thick = 3 if is_target else 1
            cv2.rectangle(out, (x1, y1), (x2, y2), color, thick)
            tag = f"{det.label} {det.confidence:.2f}"
            cv2.putText(out, tag, (x1, max(14, y1 - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
            if is_target:
                cx, cy = (int(v) for v in det.center)
                cv2.line(out, (w // 2, h // 2), (cx, cy), (0, 0, 255), 1)
                cv2.circle(out, (cx, cy), 4, (0, 0, 255), -1)

        banner = "ENGAGED" if armed else "STANDBY"
        bcol = (0, 0, 255) if armed else (180, 180, 180)
        cv2.putText(out, banner, (w - 130, 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, bcol, 2)
        cv2.putText(out, message, (12, h - 14),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 0), 2)
        return out
