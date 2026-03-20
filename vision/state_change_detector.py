import numpy as np

class StateChangeDetector:

    def changed(self, frame1, frame2):

        diff = np.mean(np.abs(frame1 - frame2))

        return diff > 5