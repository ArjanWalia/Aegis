"""Aegis — vision-guided object tracking for the SO-ARM101 (Feetech) arm.

The package is split into small, swappable pieces:

* :mod:`aegis.config`     — environment-driven settings.
* :mod:`aegis.camera`     — frame sources (real webcam / mock).
* :mod:`aegis.detector`   — CNN object detectors (YOLOv8 / mock).
* :mod:`aegis.robot`      — Feetech STS3215 arm driver (real / mock).
* :mod:`aegis.controller` — the visual-servoing tracking loop.
* :mod:`aegis.app`        — the FastAPI web application.
"""

__version__ = "0.1.0"
