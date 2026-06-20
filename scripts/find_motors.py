#!/usr/bin/env python3
"""Scan the Feetech serial bus and report which servo IDs respond.

Run this first when setting up the SO-ARM101 to confirm wiring, the serial
port, and the motor IDs (factory default IDs are 1..6, base to gripper).

    python scripts/find_motors.py --port /dev/ttyACM0 --baud 1000000

Requires the hardware extras:  pip install -r requirements-hardware.txt
"""

from __future__ import annotations

import argparse
import sys

# Make `aegis` importable when run from the repo root.
sys.path.insert(0, ".")
from aegis.robot import ticks_to_deg  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", default="/dev/ttyACM0", help="serial device")
    ap.add_argument("--baud", type=int, default=1_000_000, help="baud rate")
    ap.add_argument("--max-id", type=int, default=20, help="highest ID to probe")
    args = ap.parse_args()

    try:
        from scservo_sdk import COMM_SUCCESS, PacketHandler, PortHandler
    except Exception as exc:  # noqa: BLE001
        print(f"Could not import scservo_sdk ({exc!r}).")
        print("Install it into THIS interpreter:")
        print("  python -m pip install feetech-servo-sdk")
        return 2

    ADDR_PRESENT_POSITION = 56  # STS/SMS present-position register
    port = PortHandler(args.port)
    packet = PacketHandler(0)  # protocol_end=0 for STS/SMS servos
    if not port.openPort():
        print(f"ERROR: could not open {args.port}")
        return 1
    if not port.setBaudRate(args.baud):
        print(f"ERROR: could not set baud {args.baud}")
        return 1

    print(f"Scanning {args.port} @ {args.baud} baud (IDs 1..{args.max_id})…\n")
    found = 0
    for motor_id in range(1, args.max_id + 1):
        model, comm, err = packet.ping(port, motor_id)
        if comm == COMM_SUCCESS and err == 0:
            pos, _c, _e = packet.read2ByteTxRx(port, motor_id, ADDR_PRESENT_POSITION)
            print(f"  ID {motor_id:>3}  model={model:<6}  "
                  f"pos={pos:>4} ({ticks_to_deg(pos):6.1f} deg)")
            found += 1

    print(f"\nDone. {found} servo(s) responded.")
    if found == 0:
        print("No servos found — check power, USB cable, port, and baud rate.")
    port.closePort()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
