"""Coordinates capture -> detection -> OCR pipelines."""

from typing import Any, Dict, List, Optional


class VisionPipeline:
    def __init__(self, capture, detector, ocr):
        self.capture = capture
        self.detector = detector
        self.ocr = ocr

    def process(self) -> Dict[str, Any]:
        frame = self.capture.grab()
        boxes = self.detector.detect(frame) if self.detector else []
        text = self.ocr.read(frame) if self.ocr else []
        return {"frame": frame, "boxes": boxes, "text": text}
