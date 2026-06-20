"""Central configuration for Aegis.

Every value can be overridden with an environment variable so the same code
runs against real hardware or in mock mode without edits.  See
``config.example.env`` for a documented template.

Component selection (camera / detector / robot) is *auto* by default: Aegis
tries the real implementation and transparently falls back to a mock if the
hardware or its driver library is unavailable.  Set ``AEGIS_MOCK=1`` to force
mock mode everywhere, or ``AEGIS_STRICT=1`` to disable the fallback and fail
loudly when hardware is missing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on", "y")


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    try:
        return int(raw) if raw is not None else default
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    raw = os.getenv(name)
    try:
        return float(raw) if raw is not None else default
    except ValueError:
        return default


def _str(name: str, default: str) -> str:
    raw = os.getenv(name)
    return raw if raw is not None and raw != "" else default


# Default SO-ARM101 joint -> Feetech motor ID map (factory IDs, base to gripper).
_DEFAULT_MOTOR_IDS = {
    "shoulder_pan": 1,
    "shoulder_lift": 2,
    "elbow_flex": 3,
    "wrist_flex": 4,
    "wrist_roll": 5,
    "gripper": 6,
}

# Safe absolute joint limits in degrees (0..360). These are intentionally
# conservative; calibrate for your unit before widening them.
_DEFAULT_JOINT_LIMITS = {
    "shoulder_pan": (60.0, 300.0),
    "shoulder_lift": (90.0, 270.0),
    "elbow_flex": (90.0, 270.0),
    "wrist_flex": (60.0, 300.0),
    "wrist_roll": (0.0, 360.0),
    "gripper": (90.0, 270.0),
}


@dataclass
class Config:
    """Resolved runtime configuration (read from the environment once)."""

    # -- Web server ---------------------------------------------------------
    host: str = field(default_factory=lambda: _str("AEGIS_HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: _int("AEGIS_PORT", 8000))
    stream_fps: int = field(default_factory=lambda: _int("AEGIS_STREAM_FPS", 20))

    # -- Mode switches ------------------------------------------------------
    mock_all: bool = field(default_factory=lambda: _bool("AEGIS_MOCK", False))
    strict: bool = field(default_factory=lambda: _bool("AEGIS_STRICT", False))

    # -- Camera -------------------------------------------------------------
    # CAMERA_INDEX may be an integer webcam index or a device path / URL.
    camera_index: str = field(default_factory=lambda: _str("AEGIS_CAMERA_INDEX", "0"))
    frame_width: int = field(default_factory=lambda: _int("AEGIS_FRAME_WIDTH", 640))
    frame_height: int = field(default_factory=lambda: _int("AEGIS_FRAME_HEIGHT", 480))
    mock_camera: bool = field(default_factory=lambda: _bool("AEGIS_MOCK_CAMERA", False))

    # -- Detector (the "powerful CNN model") --------------------------------
    detector: str = field(default_factory=lambda: _str("AEGIS_DETECTOR", "yolo"))
    yolo_model: str = field(default_factory=lambda: _str("AEGIS_YOLO_MODEL", "yolov8n.pt"))
    confidence: float = field(default_factory=lambda: _float("AEGIS_CONFIDENCE", 0.40))
    device: str = field(default_factory=lambda: _str("AEGIS_DEVICE", "cpu"))
    mock_detector: bool = field(default_factory=lambda: _bool("AEGIS_MOCK_DETECTOR", False))

    # -- Robot (Feetech STS3215 bus) ----------------------------------------
    serial_port: str = field(default_factory=lambda: _str("AEGIS_SERIAL_PORT", "/dev/ttyACM0"))
    baudrate: int = field(default_factory=lambda: _int("AEGIS_BAUDRATE", 1_000_000))
    mock_robot: bool = field(default_factory=lambda: _bool("AEGIS_MOCK_ROBOT", False))
    motor_ids: dict = field(default_factory=lambda: dict(_DEFAULT_MOTOR_IDS))
    joint_limits: dict = field(default_factory=lambda: dict(_DEFAULT_JOINT_LIMITS))

    # -- Visual-servoing control --------------------------------------------
    pan_joint: str = field(default_factory=lambda: _str("AEGIS_PAN_JOINT", "shoulder_pan"))
    tilt_joint: str = field(default_factory=lambda: _str("AEGIS_TILT_JOINT", "wrist_flex"))
    # Proportional gains: degrees of joint motion per unit of normalised error.
    kp_pan: float = field(default_factory=lambda: _float("AEGIS_KP_PAN", 12.0))
    kp_tilt: float = field(default_factory=lambda: _float("AEGIS_KP_TILT", 10.0))
    # Direction of each axis; flip to +1/-1 if the arm chases away from target.
    pan_sign: float = field(default_factory=lambda: _float("AEGIS_PAN_SIGN", -1.0))
    tilt_sign: float = field(default_factory=lambda: _float("AEGIS_TILT_SIGN", 1.0))
    # Fraction of half-frame within which the target is "centred" (no motion).
    deadzone: float = field(default_factory=lambda: _float("AEGIS_DEADZONE", 0.06))
    # Clamp on how far any joint may move in a single control tick (degrees).
    max_step_deg: float = field(default_factory=lambda: _float("AEGIS_MAX_STEP_DEG", 4.0))
    # Control-loop rate (also the detection rate).
    loop_hz: float = field(default_factory=lambda: _float("AEGIS_LOOP_HZ", 15.0))
    # Servo move speed / acceleration sent to the Feetech bus (0..N).
    move_speed: int = field(default_factory=lambda: _int("AEGIS_MOVE_SPEED", 600))
    move_accel: int = field(default_factory=lambda: _int("AEGIS_MOVE_ACCEL", 30))

    def use_mock_camera(self) -> bool:
        return self.mock_all or self.mock_camera

    def use_mock_detector(self) -> bool:
        return self.mock_all or self.mock_detector or self.detector == "mock"

    def use_mock_robot(self) -> bool:
        return self.mock_all or self.mock_robot


def load_config() -> Config:
    """Build a :class:`Config` from the current environment."""
    return Config()
