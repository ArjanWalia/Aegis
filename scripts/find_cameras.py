#!/usr/bin/env python3
"""List the camera indices OpenCV can open, with a live preview hint.

The SO-ARM101 wrist camera is a USB webcam separate from a laptop's built-in
camera, so it shows up at a *different* index. Run this to discover which index
is the arm camera, then launch Aegis with:

    AEGIS_CAMERA_INDEX=<that index> python run.py

On macOS, also run `system_profiler SPCameraDataType` to see camera *names*;
OpenCV indices follow the same device order (built-in is usually 0).

Usage:
    python scripts/find_cameras.py                # probe indices 0..7
    python scripts/find_cameras.py --max 12       # probe more
    python scripts/find_cameras.py --save         # save a frame from each
"""

from __future__ import annotations

import argparse


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--max", type=int, default=8, help="highest index to probe")
    ap.add_argument("--save", action="store_true",
                    help="save one JPEG per working camera (cam_<i>.jpg)")
    args = ap.parse_args()

    try:
        import cv2
    except ImportError:
        print("opencv not installed. Run: python -m pip install -r requirements.txt")
        return 2

    print(f"Probing camera indices 0..{args.max - 1} …\n")
    working = []
    for index in range(args.max):
        cap = cv2.VideoCapture(index)
        if not cap.isOpened():
            cap.release()
            continue
        ok, frame = cap.read()
        if ok and frame is not None:
            h, w = frame.shape[:2]
            print(f"  index {index}: OK  ({w}x{h})")
            working.append(index)
            if args.save:
                fname = f"cam_{index}.jpg"
                cv2.imwrite(fname, frame)
                print(f"           saved {fname} — open it to see which camera this is")
        else:
            print(f"  index {index}: opened but no frame")
        cap.release()

    print()
    if not working:
        print("No cameras opened. On macOS, grant Camera permission to your "
              "terminal (System Settings > Privacy & Security > Camera) and "
              "make sure the arm's USB camera is plugged in.")
        return 1

    print(f"Working indices: {working}")
    print("Tip: --save writes a frame from each so you can tell which is the "
          "SO-ARM101 wrist camera, then run:")
    print("  AEGIS_CAMERA_INDEX=<index> python run.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
