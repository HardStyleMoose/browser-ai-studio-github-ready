YOLO = None
_YOLO_IMPORT_ERROR = None


def _resolve_yolo():
    global YOLO, _YOLO_IMPORT_ERROR
    if YOLO is not None:
        return YOLO
    if _YOLO_IMPORT_ERROR is not None:
        raise RuntimeError("ultralytics is not installed") from _YOLO_IMPORT_ERROR
    try:
        from ultralytics import YOLO as ultralytics_yolo
    except ImportError as exc:  # pragma: no cover
        _YOLO_IMPORT_ERROR = exc
        raise RuntimeError("ultralytics is not installed") from exc
    YOLO = ultralytics_yolo
    return YOLO


class YOLODetector:

    def __init__(self, model="yolov8n.pt"):
        """Lightweight YOLOv8 detector for UI elements."""
        self.model_path = model
        self.model = None

    def _ensure_model(self):
        if self.model is None:
            self.model = _resolve_yolo()(self.model_path)
        return self.model

    def detect(self, image):
        """Run detection and return parsed results."""
        model = self._ensure_model()
        results = model(image)
        # results is a list of Results objects; return first frame detections
        if len(results) > 0:
            return results[0]
        return None
