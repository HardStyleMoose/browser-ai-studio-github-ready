import os
from pathlib import Path

import cv2

try:
    import pytesseract
except ImportError:  # pragma: no cover
    pytesseract = None


class ResourceReader:
    COMMON_TESSERACT_PATHS = [
        Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
        Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
        Path(r"D:\Program Files\Tesseract-OCR\tesseract.exe"),
    ]

    def __init__(self):
        self.available = False
        self.status_message = "OCR unavailable: pytesseract is not installed."
        self.tesseract_path = None
        self._configure_tesseract()

    def _configure_tesseract(self):
        if pytesseract is None:
            return

        configured_cmd = getattr(getattr(pytesseract, "pytesseract", pytesseract), "tesseract_cmd", None)
        candidates = []
        if configured_cmd:
            candidates.append(Path(configured_cmd))

        env_cmd = os.environ.get("TESSERACT_CMD")
        if env_cmd:
            candidates.append(Path(env_cmd))

        which_cmd = self._resolve_from_path("tesseract")
        if which_cmd is not None:
            candidates.append(which_cmd)

        candidates.extend(self.COMMON_TESSERACT_PATHS)

        seen = set()
        for candidate in candidates:
            candidate_path = Path(candidate)
            normalized = str(candidate_path).lower()
            if normalized in seen or not candidate_path.exists():
                continue
            seen.add(normalized)
            try:
                pytesseract.pytesseract.tesseract_cmd = str(candidate_path)
                pytesseract.get_tesseract_version()
                self.available = True
                self.tesseract_path = str(candidate_path)
                os.environ["TESSERACT_CMD"] = str(candidate_path)
                self.status_message = f"OCR ready via {candidate_path}"
                return
            except Exception:
                continue

        self.available = False
        self.status_message = "OCR unavailable: install Tesseract OCR or add it to PATH."

    def _resolve_from_path(self, executable_name: str):
        for directory in os.environ.get("PATH", "").split(os.pathsep):
            if not directory:
                continue
            candidate = Path(directory) / executable_name
            if candidate.exists():
                return candidate
            if os.name == "nt":
                exe_candidate = candidate.with_suffix(".exe")
                if exe_candidate.exists():
                    return exe_candidate
        return None

    def get_status(self):
        return {
            "available": self.available,
            "message": self.status_message,
            "path": self.tesseract_path,
        }

    def read_text(self, image, config: str = "--psm 6"):
        """Extract text from a UI image region."""
        if pytesseract is None or not self.available or image is None:
            return ""

        try:
            if len(image.shape) == 2:
                gray = image
            elif len(image.shape) == 3:
                gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            else:
                return ""
            return pytesseract.image_to_string(gray, config=str(config or "--psm 6"))
        except Exception as exc:
            message = str(exc).lower()
            if "tesseract" in message and ("not found" in message or "not installed" in message or "no such file" in message):
                self.available = False
                self.status_message = "OCR unavailable: Tesseract OCR is installed incorrectly or not reachable."
            return ""

    def read_text_boxes(self, image, keywords=(), min_confidence: float = 20.0, config: str = "--psm 11"):
        if pytesseract is None or not self.available or image is None:
            return []

        normalized_keywords = [str(keyword or "").strip().lower() for keyword in keywords if str(keyword or "").strip()]
        try:
            if len(image.shape) == 2:
                gray = image
            elif len(image.shape) == 3:
                gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            else:
                return []
            data = pytesseract.image_to_data(
                gray,
                output_type=pytesseract.Output.DICT,
                config=str(config or "--psm 11"),
            )
        except Exception as exc:
            message = str(exc).lower()
            if "tesseract" in message and ("not found" in message or "not installed" in message or "no such file" in message):
                self.available = False
                self.status_message = "OCR unavailable: Tesseract OCR is installed incorrectly or not reachable."
            return []

        boxes = []
        texts = data.get("text", []) if isinstance(data, dict) else []
        for index, raw_text in enumerate(texts):
            text = str(raw_text or "").strip()
            if not text:
                continue
            normalized_text = text.lower()
            matched_keyword = next(
                (keyword for keyword in normalized_keywords if keyword and keyword in normalized_text),
                normalized_text,
            )
            if normalized_keywords and matched_keyword == normalized_text and normalized_text not in normalized_keywords:
                continue
            try:
                confidence = float((data.get("conf", []) or [])[index])
            except Exception:
                confidence = -1.0
            if confidence < float(min_confidence):
                continue
            try:
                x = int((data.get("left", []) or [])[index])
                y = int((data.get("top", []) or [])[index])
                width = int((data.get("width", []) or [])[index])
                height = int((data.get("height", []) or [])[index])
            except Exception:
                continue
            if width <= 2 or height <= 2:
                continue
            boxes.append(
                {
                    "text": text,
                    "keyword": matched_keyword,
                    "confidence": confidence,
                    "x": x,
                    "y": y,
                    "width": width,
                    "height": height,
                }
            )
        return boxes

    def read(self, image):
        return self.read_text(image)
