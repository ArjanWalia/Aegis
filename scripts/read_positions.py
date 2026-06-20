#!/usr/bin/env python3
"""Continuously print live joint angles for the SO-ARM101.

Useful for calibration: relax the arm (`--relax`), move it by hand to the
extremes of each joint, and note the angles to set safe AEGIS_* limits.

    python scripts/read_positions.py --port /dev/ttyACM0 --relax

Requires the hardware extras:  pip install -r requirements-hardware.txt
"""

from __future__ import annotations

import argparse
import sys
import time

sys.path.insert(0, ".")
from aegis.config import _DEFAULT_MOTOR_IDS  # noqa: E402
from aegis.robot import ticks_to_deg  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", default="/dev/ttyACM0")
    ap.add_argument("--baud", type=int, default=1_000_000)
    ap.add_argument("--relax", action="store_true",
                    help="disable torque so the arm can be moved by hand")
    args = ap.parse_args()

    try:
        from scservo_sdk import PortHandler, sms_sts
    except ImportError:
        print("scservo_sdk not installed. Run:")
        print("  pip install -r requirements-hardware.txt")
        return 2

    port = PortHandler(args.port)
    packet = sms_sts(port)
    if not port.openPort() or not port.setBaudRate(args.baud):
        print(f"ERROR: could not open {args.port} @ {args.baud}")
        return 1

    ADDR_TORQUE_ENABLE = 40
    if args.relax:
        for motor_id in _DEFAULT_MOTOR_IDS.values():
            packet.write1ByteTxRx(motor_id, ADDR_TORQUE_ENABLE, 0)
        print("Torque disabled — move the arm by hand. Ctrl-C to quit.\n")

    names = list(_DEFAULT_MOTOR_IDS)
    try:
        while True:
            cells = []
            for joint in names:
                motor_id = _DEFAULT_MOTOR_IDS[joint]
                pos, _spd, _c, _e = packet.ReadPosSpeed(motor_id)
                cells.append(f"{joint}={ticks_to_deg(pos):6.1f}")
            print("  ".join(cells), end="\r", flush=True)
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nDone.")
    finally:
        port.closePort()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
