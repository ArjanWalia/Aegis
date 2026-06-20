"""SO-ARM101 arm driver (Feetech STS3215 serial-bus servos).

The arm is a chain of Feetech STS3215 smart servos addressed by ID over a
single TTL serial bus (the SO-ARM101 controller board enumerates as e.g.
``/dev/ttyACM0`` on Linux, ``/dev/tty.usbmodem*`` on macOS, ``COMx`` on
Windows).  Each servo has a 12-bit absolute encoder: 0..4095 ticks == 0..360
degrees.

This module exposes a tiny, safe interface used by the tracker:

* :meth:`Arm.positions`       — current commanded joint angles (degrees).
* :meth:`Arm.move_relative`   — nudge joints by deltas (clamped + rate limited).
* :meth:`Arm.move_absolute`   — command absolute joint angles.

:class:`FeetechArm` talks to real servos via the ``scservo_sdk`` (the
``feetech-servo-sdk`` PyPI package).  :class:`MockArm` mirrors the interface in
memory so the control loop is identical with or without hardware.

NB: the SO-ARM101 also ships with HuggingFace LeRobot.  We drive the bus
directly to keep dependencies light; see the README for the LeRobot route.
"""

from __future__ import annotations

import logging
import threading

log = logging.getLogger("aegis.robot")

TICKS_PER_REV = 4096  # STS3215 12-bit encoder


def deg_to_ticks(deg: float) -> int:
    return int(round((deg % 360.0) / 360.0 * TICKS_PER_REV)) % TICKS_PER_REV


def ticks_to_deg(ticks: int) -> float:
    return (ticks % TICKS_PER_REV) / TICKS_PER_REV * 360.0


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


class _BaseArm:
    """Shared limit-clamping and rate-limiting logic for both arms."""

    def __init__(self, config):
        self.config = config
        self.motor_ids = config.motor_ids
        self.limits = config.joint_limits
        self.max_step = config.max_step_deg
        # Commanded joint angles in degrees; filled in by connect().
        self._commanded: dict[str, float] = {}
        self._lock = threading.Lock()

    # -- to be provided by subclasses --------------------------------------
    def _read_positions_deg(self) -> dict[str, float]:
        raise NotImplementedError

    def _write_positions_deg(self, targets: dict[str, float]) -> None:
        raise NotImplementedError

    # -- public interface ---------------------------------------------------
    def connect(self) -> None:
        with self._lock:
            self._commanded = self._read_positions_deg()
        log.info("Arm connected; start pose (deg): %s",
                 {k: round(v, 1) for k, v in self._commanded.items()})

    def positions(self) -> dict[str, float]:
        with self._lock:
            return dict(self._commanded)

    def move_absolute(self, targets: dict[str, float]) -> dict[str, float]:
        """Command absolute angles; values are clamped to joint limits."""
        with self._lock:
            for joint, deg in targets.items():
                if joint not in self.motor_ids:
                    continue
                lo, hi = self.limits.get(joint, (0.0, 360.0))
                self._commanded[joint] = _clamp(deg, lo, hi)
            self._write_positions_deg(self._commanded)
            return dict(self._commanded)

    def move_relative(self, deltas: dict[str, float]) -> dict[str, float]:
        """Nudge joints by deltas (degrees), rate-limited and clamped."""
        with self._lock:
            for joint, delta in deltas.items():
                if joint not in self.motor_ids:
                    continue
                step = _clamp(delta, -self.max_step, self.max_step)
                lo, hi = self.limits.get(joint, (0.0, 360.0))
                self._commanded[joint] = _clamp(self._commanded[joint] + step, lo, hi)
            self._write_positions_deg(self._commanded)
            return dict(self._commanded)

    def relax(self) -> None:
        """Optionally disable torque so the arm can be moved by hand."""

    def close(self) -> None:
        self.relax()


class FeetechArm(_BaseArm):
    """Real SO-ARM101 over the Feetech serial bus.

    Uses the generic ``scservo_sdk`` (``feetech-servo-sdk`` on PyPI), whose
    ``PacketHandler(protocol_end)`` exposes register-level ``read*/write*TxRx``
    calls that take the port as the first argument. STS/SMS servos use
    ``protocol_end = 0``.
    """

    # STS/SMS control-table register addresses.
    ADDR_TORQUE_ENABLE = 40
    ADDR_GOAL_ACC = 41
    ADDR_GOAL_POSITION = 42  # 2 bytes
    ADDR_GOAL_SPEED = 46     # 2 bytes
    ADDR_PRESENT_POSITION = 56  # 2 bytes
    STS_PROTOCOL_END = 0

    def __init__(self, config):
        super().__init__(config)
        from scservo_sdk import PacketHandler, PortHandler  # lazy import

        self.port = PortHandler(config.serial_port)
        self.packet = PacketHandler(self.STS_PROTOCOL_END)
        if not self.port.openPort():
            raise RuntimeError(f"Failed to open serial port {config.serial_port}")
        if not self.port.setBaudRate(config.baudrate):
            raise RuntimeError(f"Failed to set baud rate {config.baudrate}")
        self.speed = config.move_speed
        self.accel = config.move_accel
        # Configure speed/accel once. Torque is engaged in connect() *after* the
        # goal position is set to the present pose, so the arm never snaps to a
        # stale goal-position register when torque turns on.
        for joint, motor_id in self.motor_ids.items():
            self.packet.write1ByteTxRx(self.port, motor_id, self.ADDR_GOAL_ACC, self.accel)
            self.packet.write2ByteTxRx(self.port, motor_id, self.ADDR_GOAL_SPEED, self.speed)
        log.info("Feetech bus open on %s @ %d baud", config.serial_port, config.baudrate)

    def connect(self) -> None:
        # Read present pose into the commanded state (via _BaseArm.connect).
        super().connect()
        # Hold exactly where the arm is: set goal = present, *then* enable torque
        # so engaging torque produces no motion.
        self._write_positions_deg(self._commanded)
        for motor_id in self.motor_ids.values():
            self.packet.write1ByteTxRx(self.port, motor_id, self.ADDR_TORQUE_ENABLE, 1)

    def _read_positions_deg(self) -> dict[str, float]:
        from scservo_sdk import COMM_SUCCESS

        out: dict[str, float] = {}
        for joint, motor_id in self.motor_ids.items():
            pos, comm, err = self.packet.read2ByteTxRx(
                self.port, motor_id, self.ADDR_PRESENT_POSITION
            )
            if comm != COMM_SUCCESS or err != 0:
                log.warning("Could not read motor %s (id %d); assuming 180deg",
                            joint, motor_id)
                out[joint] = 180.0
            else:
                out[joint] = ticks_to_deg(pos)
        return out

    def _write_positions_deg(self, targets: dict[str, float]) -> None:
        # Only the joints the tracker actually moves are written each tick, but
        # writing all commanded joints keeps the pose coherent and cheap.
        for joint, deg in targets.items():
            motor_id = self.motor_ids[joint]
            self.packet.write2ByteTxRx(
                self.port, motor_id, self.ADDR_GOAL_POSITION, deg_to_ticks(deg)
            )

    def relax(self) -> None:
        for motor_id in self.motor_ids.values():
            try:
                self.packet.write1ByteTxRx(
                    self.port, motor_id, self.ADDR_TORQUE_ENABLE, 0
                )
            except Exception:  # noqa: BLE001
                pass

    def close(self) -> None:
        self.relax()
        try:
            self.port.closePort()
        except Exception:  # noqa: BLE001
            pass


class MockArm(_BaseArm):
    """In-memory arm: same math, no hardware. Logs target-pointing motion."""

    def _read_positions_deg(self) -> dict[str, float]:
        # Start centred so there is symmetric room to track in every axis.
        return {joint: 180.0 for joint in self.motor_ids}

    def _write_positions_deg(self, targets: dict[str, float]) -> None:
        # No-op: state already lives in self._commanded. Debug-log occasionally.
        log.debug("MockArm pose (deg): %s",
                  {k: round(v, 1) for k, v in targets.items()})


def make_arm(config):
    """Return a real Feetech arm, or a mock with graceful fallback."""
    if config.use_mock_robot():
        log.info("Using MockArm (no serial hardware).")
        arm = MockArm(config)
        arm.connect()
        return arm
    try:
        arm = FeetechArm(config)
        arm.connect()
        return arm
    except Exception as exc:  # noqa: BLE001
        if config.strict:
            raise
        log.warning("Feetech arm unavailable (%s); falling back to MockArm.", exc)
        arm = MockArm(config)
        arm.connect()
        return arm
