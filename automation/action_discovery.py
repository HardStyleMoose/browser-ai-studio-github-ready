from vision.ui_detector import UIDetector

class ActionDiscovery:

    def __init__(self, ui_detector):

        self.ui_detector = ui_detector

    def discover_actions(self, frame):
        if hasattr(self.ui_detector, "detect_elements"):
            elements = self.ui_detector.detect_elements(frame)
        else:
            elements = self.ui_detector.detect_buttons(frame)

        actions = []

        for element in elements:
            if isinstance(element, dict):
                if element.get("type") == "button":
                    actions.append({"type": "click", "x": element["x"], "y": element["y"]})
                elif element.get("type") == "input":
                    actions.append({"type": "type", "x": element["x"], "y": element["y"], "text": "sample"})
            elif isinstance(element, (list, tuple)) and len(element) >= 4:
                x, y, width, height = element[:4]
                actions.append({"type": "click", "x": int(x + width / 2), "y": int(y + height / 2)})

        return actions