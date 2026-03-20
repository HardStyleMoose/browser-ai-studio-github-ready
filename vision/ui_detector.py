import cv2

class UIDetector:

    def detect_buttons(self, frame):

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        edges = cv2.Canny(gray, 50, 150)

        contours, _ = cv2.findContours(
            edges,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE
        )

        buttons = []

        for c in contours:

            x,y,w,h = cv2.boundingRect(c)

            if w > 50 and h > 20:
                buttons.append((x,y,w,h))

        return buttons