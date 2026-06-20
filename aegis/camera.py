"""Frame sources for Aegis.

The SO-ARM101 is typically fitted with a wrist (eye-in-hand) USB camera.  In
that geometry, rotating the base pans the camera left/right and flexing the
wrist tilts it up/down — exactly the two axes the tracker drives.

:class:`RealCamera` wraps an OpenCV capture device; :class:`MockCamera`
synthesises frames so the app runs with no hardware attached.
"""

from __future__ import annotations

import logging
import time

import numpy as np

log = logging.getLogger("aegis.camera")


class RealCamera:
    """OpenCV ``VideoCapture`` wrapper (webcam index, device path, or URL)."""

    def __init__(self, index: str, width: int, height: int):
        import cv2  # lazy import

        self._cv2 = cv2
        # Accept either a numeric webcam index ("0") or a path/URL.
        source: object = int(index) if str(index).isdigit() else index
        self.cap = cv2.VideoCapture(source)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        # Keep only the latest frame so reads don't return a stale backlog
        # (a major source of perceived lag with USB webcams).
        try:
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:  # noqa: BLE001 - not all backends support this
            pass
        if not self.cap.isOpened():
            raise RuntimeError(f"Could not open camera source {source!r}")
        self.width = width
        self.height = height
        log.info("Opened camera %r at %dx%d", source, width, height)

    def read(self) -> np.ndarray:
        ok, frame = self.cap.read()
        if not ok or frame is None:
            raise RuntimeError("Camera frame grab failed")
        return frame

    def close(self) -> None:
        try:
            self.cap.release()
        except Exception:  # noqa: BLE001
            pass


class MockCamera:
    """Generates a moving gradient + timestamp so the stream is never blank."""

    def __init__(self, width: int = 640, height: int = 480):
        self.width = width
        self.height = height
        self._t0 = time.time()

    def read(self) -> np.ndarray:
        import cv2

        h, w = self.height, self.width
        t = time.time() - self._t0
        frame = np.zeros((h, w, 3), dtype=np.uint8)
        # Soft animated background so it is visibly "live".
        xs = np.linspace(0, 255, w, dtype=np.uint8)
        frame[:] = np.dstack([
            np.tile(xs, (h, 1)),
            np.full((h, w), int(96 + 64 * np.sin(t)), dtype=np.uint8),
            np.tile(xs[::-1], (h, 1)),
        ])
        cv2.putText(frame, "MOCK CAMERA", (12, 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
        return frame

    def close(self) -> None:  # nothing to release
        pass


def make_camera(config):
    """Return a real camera, or a mock with graceful fallback."""
    if config.use_mock_camera():
        log.info("Using MockCamera (synthetic frames).")
        return MockCamera(config.frame_width, config.frame_height)
    try:
        return RealCamera(config.camera_index, config.frame_width, config.frame_height)
    except Exception as exc:  # noqa: BLE001
        if config.strict:
            raise
        log.warning("Camera unavailable (%s); falling back to MockCamera.", exc)
        return MockCamera(config.frame_width, config.frame_height)
