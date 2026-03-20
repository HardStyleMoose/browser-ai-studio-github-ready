import pyautogui

pyautogui.FAILSAFE = False

class MouseController:

    def click(self, x, y, human_like=True):
        if human_like:
            # Simulate human-like movement with random jitter and speed
            import random
            steps = random.randint(8, 20)
            x0, y0 = pyautogui.position()
            for i in range(1, steps + 1):
                nx = x0 + (x - x0) * i / steps + random.uniform(-2, 2)
                ny = y0 + (y - y0) * i / steps + random.uniform(-2, 2)
                pyautogui.moveTo(nx, ny, duration=0.01 + random.uniform(0, 0.03))
            pyautogui.moveTo(x, y, duration=0.02 + random.uniform(0, 0.04))
        else:
            pyautogui.moveTo(x, y)
        pyautogui.click()
