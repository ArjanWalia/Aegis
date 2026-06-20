"""Object detectors — the "powerful CNN" that classifies and *locates* objects.

To point an arm at something you need to know *where* it is in the frame, not
just that it is present, so Aegis uses a detection CNN (label + bounding box)
rather than a bare classifier.

Two implementations are provided:

* :class:`YOLODetector` — Ultralytics YOLOv8, a strong, fast convolutional
  detector pretrained on the 80-class COCO dataset.
* :class:`MockDetector` — a dependency-free stand-in that emits a synthetic
  moving object so the full pipeline (UI -> match -> servo) can be exercised
  without a camera, GPU, or model download.

Both return ``list[Detection]`` so the rest of the system never imports torch.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from typing import List

import numpy as np

log = logging.getLogger("aegis.detector")


# The 80 COCO classes YOLOv8 is trained on — exposed to the UI so the user can
# pick a target the model can actually recognise.
COCO_CLASSES = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train",
    "truck", "boat", "traffic light", "fire hydrant", "stop sign",
    "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep", "cow",
    "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella", "handbag",
    "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball", "kite",
    "baseball bat", "baseball glove", "skateboard", "surfboard",
    "tennis racket", "bottle", "wine glass", "cup", "fork", "knife", "spoon",
    "bowl", "banana", "apple", "sandwich", "orange", "broccoli", "carrot",
    "hot dog", "pizza", "donut", "cake", "chair", "couch", "potted plant",
    "bed", "dining table", "toilet", "tv", "laptop", "mouse", "remote",
    "keyboard", "cell phone", "microwave", "oven", "toaster", "sink",
    "refrigerator", "book", "clock", "vase", "scissors", "teddy bear",
    "hair drier", "toothbrush",
]


@dataclass
class Detection:
    """A single detected object in pixel coordinates."""

    label: str
    confidence: float
    bbox: tuple  # (x1, y1, x2, y2) in pixels

    @property
    def center(self) -> tuple:
        x1, y1, x2, y2 = self.bbox
        return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)

    @property
    def area(self) -> float:
        x1, y1, x2, y2 = self.bbox
        return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def normalize_label(text: str) -> str:
    return " ".join(text.lower().strip().split())


def label_matches(target: str, label: str) -> bool:
    """Loose, user-friendly matching (``phone`` matches ``cell phone``)."""
    if not target:
        return False
    t = normalize_label(target)
    l = normalize_label(label)
    return t == l or t in l or l in t


class YOLODetector:
    """Ultralytics YOLOv8 detector (CNN, COCO-pretrained)."""

    def __init__(self, model_path: str = "yolov8n.pt", confidence: float = 0.4,
                 device: str = "cpu"):
        from ultralytics import YOLO  # lazy: only needed for real detection

        log.info("Loading YOLO model '%s' on %s ...", model_path, device)
        self.model = YOLO(model_path)
        self.confidence = confidence
        self.device = device
        # COCO names as reported by the model itself.
        self.names = list(self.model.names.values())

    @property
    def labels(self) -> List[str]:
        return self.names

    def detect(self, frame: np.ndarray) -> List[Detection]:
        results = self.model.predict(
            frame, conf=self.confidence, device=self.device, verbose=False
        )
        detections: List[Detection] = []
        for res in results:
            for box in res.boxes:
                cls_id = int(box.cls[0])
                conf = float(box.conf[0])
                x1, y1, x2, y2 = (float(v) for v in box.xyxy[0])
                detections.append(
                    Detection(self.model.names[cls_id], conf, (x1, y1, x2, y2))
                )
        return detections


class MockDetector:
    """Synthetic detector: one object drifting in a slow Lissajous orbit.

    Lets you watch the arm "lock on" with no camera or model.  The reported
    label is configurable via ``AEGIS_MOCK_LABEL`` (default ``bottle``) and the
    list of selectable labels still covers all COCO classes.
    """

    def __init__(self, label: str = "bottle"):
        import os

        self.label = normalize_label(os.getenv("AEGIS_MOCK_LABEL", label))
        self._t0 = time.time()

    @property
    def labels(self) -> List[str]:
        return COCO_CLASSES

    def detect(self, frame: np.ndarray) -> List[Detection]:
        h, w = frame.shape[:2]
        t = time.time() - self._t0
        # Drift around the frame so the servo loop has something to chase.
        cx = w * (0.5 + 0.32 * math.sin(t * 0.6))
        cy = h * (0.5 + 0.22 * math.sin(t * 0.9 + 1.0))
        bw, bh = w * 0.16, h * 0.22
        bbox = (cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2)
        conf = 0.90
        return [Detection(self.label, conf, bbox)]


def make_detector(config) -> object:
    """Return a real YOLO detector, or a mock with graceful fallback."""
    if config.use_mock_detector():
        log.info("Using MockDetector (synthetic detections).")
        return MockDetector()
    try:
        return YOLODetector(config.yolo_model, config.confidence, config.device)
    except Exception as exc:  # noqa: BLE001 - want any failure to fall back
        if config.strict:
            raise
        log.warning("YOLO unavailable (%s); falling back to MockDetector.", exc)
        return MockDetector()
