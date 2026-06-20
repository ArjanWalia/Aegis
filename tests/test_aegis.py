"""Unit + integration tests that run fully in mock mode (no hardware)."""

import os
import time

import numpy as np

os.environ["AEGIS_MOCK"] = "1"

from aegis.config import load_config  # noqa: E402
from aegis.controller import Tracker  # noqa: E402
from aegis.detector import Detection, MockDetector, label_matches  # noqa: E402
from aegis.robot import MockArm, deg_to_ticks, ticks_to_deg  # noqa: E402


# -- conversions -------------------------------------------------------------
def test_tick_degree_roundtrip():
    for deg in (0.0, 90.0, 180.0, 270.0, 359.0):
        assert abs(ticks_to_deg(deg_to_ticks(deg)) - deg) < 0.2


def test_deg_to_ticks_wraps():
    assert deg_to_ticks(360.0) == 0
    assert 0 <= deg_to_ticks(123.4) < 4096


# -- label matching ----------------------------------------------------------
def test_label_matching_is_forgiving():
    assert label_matches("phone", "cell phone")
    assert label_matches("Bottle", "bottle")
    assert label_matches("cup", "cup")
    assert not label_matches("dog", "cat")
    assert not label_matches("", "bottle")


# -- arm limits --------------------------------------------------------------
def test_mock_arm_clamps_to_limits():
    cfg = load_config()
    arm = MockArm(cfg)
    arm.connect()
    lo, hi = cfg.joint_limits["shoulder_pan"]
    arm.move_absolute({"shoulder_pan": 9999.0})
    assert arm.positions()["shoulder_pan"] <= hi
    arm.move_absolute({"shoulder_pan": -9999.0})
    assert arm.positions()["shoulder_pan"] >= lo


def test_mock_arm_rate_limits_steps():
    cfg = load_config()
    arm = MockArm(cfg)
    arm.connect()
    start = arm.positions()["shoulder_pan"]
    arm.move_relative({"shoulder_pan": 1000.0})  # huge request
    moved = arm.positions()["shoulder_pan"] - start
    assert abs(moved) <= cfg.max_step_deg + 1e-6


# -- servoing direction ------------------------------------------------------
def _frame():
    return np.zeros((480, 640, 3), dtype=np.uint8)


def test_servo_moves_toward_target():
    """An off-centre target should drive the pan joint, and re-centring stops it."""
    cfg = load_config()
    arm = MockArm(cfg)
    arm.connect()
    tracker = Tracker(camera=None, detector=MockDetector(), arm=arm, config=cfg)

    pan0 = arm.positions()[cfg.pan_joint]
    # Target far to the right of centre.
    det = Detection("bottle", 0.9, (600, 220, 640, 260))
    ex, ey = Tracker._frame_error(_frame(), det)
    assert ex > 0
    tracker._servo(ex, ey)
    pan1 = arm.positions()[cfg.pan_joint]
    assert pan1 != pan0  # the arm reacted

    # A centred target is inside the deadzone -> no further motion.
    centered = Detection("bottle", 0.9, (300, 220, 340, 260))
    ex2, ey2 = Tracker._frame_error(_frame(), centered)
    pan_before = arm.positions()[cfg.pan_joint]
    tracker._servo(ex2, ey2)
    assert arm.positions()[cfg.pan_joint] == pan_before


# -- full mock pipeline ------------------------------------------------------
def test_tracker_pipeline_runs_and_locks_on():
    from aegis.camera import MockCamera

    cfg = load_config()
    arm = MockArm(cfg)
    arm.connect()
    tracker = Tracker(MockCamera(640, 480), MockDetector("bottle"), arm, cfg)
    tracker.set_target("bottle")
    tracker.arm_tracking()
    tracker.start()
    try:
        time.sleep(1.0)
        status = tracker.get_status()
        assert status["running"]
        assert status["armed"]
        assert status["target"] == "bottle"
        assert status["target_visible"]
        assert tracker.get_jpeg() is not None
    finally:
        tracker.stop()
