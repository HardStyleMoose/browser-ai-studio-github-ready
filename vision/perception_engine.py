class PerceptionEngine:

    def __init__(self, detector, ocr, ui_detector):
        self.detector = detector
        self.ocr = ocr
        self.ui_detector = ui_detector

    def analyze(self, frame):
        objects = self._detect_objects(frame)
        text = self._read_text(frame)
        ui = self._detect_ui(frame)

        return {
            "objects": objects,
            "text": text,
            "ui": ui
        }

    def process(self, frame):
        return self.analyze(frame)

    def _detect_objects(self, frame):
        if self.detector is None:
            return []
        detect = getattr(self.detector, "detect", None)
        if callable(detect):
            result = detect(frame)
            return result if result is not None else []
        return []

    def _read_text(self, frame):
        if self.ocr is None:
            return ""
        for method_name in ("read", "read_text"):
            method = getattr(self.ocr, method_name, None)
            if callable(method):
                result = method(frame)
                return result if result is not None else ""
        return ""

    def _detect_ui(self, frame):
        if self.ui_detector is None:
            return []
        for method_name in ("detect_buttons", "detect_elements"):
            method = getattr(self.ui_detector, method_name, None)
            if callable(method):
                result = method(frame)
                return result if result is not None else []
        return []