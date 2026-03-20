import cv2
import mss
import numpy as np


def capture_screen(region=None):
    """Capture the screen (or a region) and return a NumPy BGR image.

    Args:
        region (dict, optional): {'left': int, 'top': int, 'width': int, 'height': int}

    Returns:
        numpy.ndarray: BGR image.
    """
    with mss.mss() as sct:
        if region:
            monitor = region
        else:
            monitor = sct.monitors[1]  # Primary monitor
        img = np.array(sct.grab(monitor))
        # BGRA to BGR
        frame = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        return frame
