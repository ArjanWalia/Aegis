# 🛡️ Aegis — SO-ARM101 Vision-Guided Object Tracker

Aegis turns a [SO-ARM101](https://github.com/TheRobotStudio/SO-ARM100) robot arm
into a camera turret that **locks onto an object you name and keeps pointing at
it**. You type a target ("bottle", "cup", "cell phone", …) into a small web app;
a CNN watches the arm's wrist camera; and when your object appears, the Feetech
servos pan and tilt to keep it centred in view until you stop.

```
 ┌──────────┐   frames   ┌───────────────┐  label+box  ┌──────────────┐  pan/tilt  ┌──────────┐
 │  Wrist   │ ─────────▶ │  YOLOv8 CNN   │ ──────────▶ │  Visual-servo │ ─────────▶ │ Feetech  │
 │  camera  │            │  (detector)   │             │  controller   │            │  STS3215 │
 └──────────┘            └───────────────┘             └──────────────┘            └──────────┘
        ▲                         the web app shows the live feed + controls            │
        └──────────────── camera moves with the arm, closing the loop ◀────────────────┘
```

## How it maps to the goal

| Requirement | How Aegis does it |
|---|---|
| Have the user input the item to track | Web UI text box with autocomplete of the CNN's known labels (`POST /api/target`). |
| Connect & activate the SO-ARM101 camera (Feetech motors) | OpenCV opens the wrist webcam; the Feetech STS3215 bus is opened over serial and torque-enabled. |
| Relay frames to a web app that classifies with a powerful CNN | FastAPI streams annotated frames (MJPEG) while **YOLOv8** (COCO-pretrained convolutional detector) labels and locates every object. |
| If the label matches, point the motors at it until stopped | A proportional **visual-servoing** loop drives `shoulder_pan` (yaw) + `wrist_flex` (pitch) to keep the matched object's bounding-box centre on the frame centre. Runs until you press **Stop**. |

> **Why a detector, not a plain classifier?** To *point* at something you need
> its *position* in the frame, not just its presence. A detection CNN gives both
> the class label **and** the bounding box, which is exactly what the controller
> needs. The detector is pluggable (`aegis/detector.py`).

## Quick start (no hardware required)

Everything runs in **mock mode** — synthetic camera, synthetic detections, and
an in-memory arm — so you can see the whole UI and control loop immediately.

```bash
pip install -r requirements.txt
AEGIS_MOCK=1 python run.py
# open http://localhost:8000
```

Type `bottle` (the mock target), press **Engage**, and watch the joint angles in
the status panel move as the controller "chases" the drifting mock object.

## Running on a real SO-ARM101

### 1. Install hardware extras

```bash
pip install -r requirements.txt -r requirements-hardware.txt
```

This adds **Ultralytics YOLOv8** (downloads `yolov8n.pt` on first run) and
**`feetech-servo-sdk`** (the `scservo_sdk` module) for the motor bus.

### 2. Wire it up

- Plug the SO-ARM101 controller board into USB. It appears as
  `/dev/ttyACM0` (Linux), `/dev/tty.usbmodem*` (macOS), or `COMx` (Windows).
- Mount/plug in the wrist USB camera; note its index (usually `0`).
- Power the servo bus.

### 3. Find your motors

```bash
python scripts/find_motors.py --port /dev/ttyACM0
```

You should see IDs **1–6** (base→gripper). The default joint map is:

| ID | Joint | Role in tracking |
|----|-------|------------------|
| 1 | `shoulder_pan` | **pan** (horizontal) |
| 2 | `shoulder_lift` | — |
| 3 | `elbow_flex` | — |
| 4 | `wrist_flex` | **tilt** (vertical) |
| 5 | `wrist_roll` | — |
| 6 | `gripper` | — |

### 4. (Optional) Calibrate safe limits

```bash
python scripts/read_positions.py --port /dev/ttyACM0 --relax
```

Move each joint by hand to its safe extremes and note the angles, then set the
matching `AEGIS_*` limits (see `aegis/config.py` → `_DEFAULT_JOINT_LIMITS`).

### 5. Configure & launch

```bash
cp config.example.env .env
# edit AEGIS_SERIAL_PORT / AEGIS_CAMERA_INDEX if needed, then:
set -a; source .env; set +a
python run.py
```

Open `http://localhost:8000`, type your target, and press **Engage**. Press
**Stop** (or Ctrl-C) at any time — Stop holds the motors; shutdown relaxes them.

> **Tip:** if the arm drives *away* from the target instead of toward it, flip
> the offending axis with `AEGIS_PAN_SIGN` / `AEGIS_TILT_SIGN` (set to `1.0` or
> `-1.0`). This depends on your servo zero direction and camera mounting.

## How the tracking loop works

A single background thread (`aegis/controller.py`) runs at `AEGIS_LOOP_HZ`:

1. **Capture** a frame from the camera.
2. **Detect** all objects with the CNN (label + box + confidence).
3. **Match** — pick the highest-confidence detection whose label matches your
   target (matching is forgiving: `phone` ↔ `cell phone`).
4. **Servo** — if engaged and the target is visible, compute the normalised
   error between the box centre and the frame centre and apply a proportional
   correction to the pan/tilt joints. A **deadzone** stops jitter once centred,
   a **per-tick step clamp** and **joint limits** keep motion safe.
5. **Stream** the annotated frame (target boxed in red, crosshair, deadzone) to
   the web app.

Because the camera is on the arm, every correction changes what the camera
sees — a classic eye-in-hand closed loop that settles with the object centred,
i.e. the arm *pointing at it*.

## Web API

| Method & path | Purpose |
|---|---|
| `GET /` | Control UI |
| `GET /video_feed` | MJPEG stream of annotated frames |
| `GET /api/labels` | Labels the CNN can recognise |
| `GET /api/status` | Live JSON: target, visibility, error, FPS, joint angles |
| `POST /api/target` | `{"target": "bottle"}` |
| `POST /api/engage` | Arm the motors (start pointing) |
| `POST /api/stop` | Disarm the motors (hold still) |

## Configuration

All settings are environment variables with safe defaults — see
[`config.example.env`](config.example.env) for the annotated list (server,
camera, detector/model, serial port, control gains, joint limits). Key knobs:

- `AEGIS_MOCK=1` — force full mock mode; `AEGIS_STRICT=1` — fail instead of
  falling back to mocks when hardware is missing.
- `AEGIS_YOLO_MODEL=yolov8s.pt` — bigger model = stronger, slower
  (`n`<`s`<`m`<`l`<`x`). Use `AEGIS_DEVICE=cuda` for a GPU.
- `AEGIS_KP_PAN`, `AEGIS_KP_TILT` — tracking aggressiveness;
  `AEGIS_DEADZONE`, `AEGIS_MAX_STEP_DEG` — smoothness/safety.

## Safety

- The arm moves on its own. Keep the workspace clear and a hand near power.
- Start with conservative gains and the default joint limits; widen only after
  calibrating your unit.
- **Stop** holds the current pose; quitting the app relaxes torque so you can
  reposition the arm by hand.

## Project layout

```
aegis/
  config.py       env-driven settings + auto mock fallback
  camera.py       RealCamera (OpenCV) / MockCamera
  detector.py     YOLODetector (CNN) / MockDetector + COCO labels
  robot.py        FeetechArm (scservo_sdk) / MockArm + tick<->deg math
  controller.py   the visual-servoing tracking loop
  app.py          FastAPI routes + MJPEG stream
  web/            single-page UI (index.html / app.js / style.css)
scripts/
  find_motors.py     scan the Feetech bus for servo IDs
  read_positions.py  live joint angles (for calibration)
tests/            mock-mode unit + integration tests (pytest)
run.py            launcher
```

## Tests

```bash
pip install pytest && python -m pytest -v   # runs entirely in mock mode
```

## Notes & alternatives

- The SO-ARM101 also ships with [HuggingFace LeRobot](https://github.com/huggingface/lerobot),
  which has its own `FeetechMotorsBus`. Aegis talks to the bus directly via
  `scservo_sdk` to stay lightweight; swapping in LeRobot only touches
  `aegis/robot.py`.
- The detector is a small interface (`detect(frame) -> list[Detection]`), so you
  can drop in a different CNN (e.g. a torchvision Faster R-CNN) without touching
  the rest of the system.
