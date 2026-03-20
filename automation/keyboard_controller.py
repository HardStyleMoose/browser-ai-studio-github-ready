import pyautogui
import random
import time

class KeyboardController:

    def press(self, key, human_like=True):
        import random
        if human_like:
            delay = random.uniform(0.08, 0.25)
        else:
            delay = random.uniform(0.03, 0.08)
        pyautogui.keyDown(key)
        time.sleep(delay)
        pyautogui.keyUp(key)

    def type_text(self, text):

        pyautogui.write(text, interval=0.05)