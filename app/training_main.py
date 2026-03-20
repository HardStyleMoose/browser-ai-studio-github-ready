# training_main.py - Universal AI Agent Training Script
print("Starting training script...")
# exit()  # Temporary exit to test
import time
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from automation.input_manager import InputManager
from automation.input_discovery import InputDiscovery, COMMON_KEYS
from automation.human_timing import HumanTiming
from vision.yolo_detector import YOLODetector
from vision.resource_reader import ResourceReader
from ai.state_extractor import StateExtractor
from ai.progress_tracker import ProgressTracker
from ai.reward_engine import RewardEngine
from ai.transformer_policy import RLAgent

# Optional: browser support
from playwright.sync_api import sync_playwright
import subprocess

# Optional: desktop capture
from vision.screen_capture import capture_screen

# ---------------------------
# SETTINGS
# ---------------------------
GAME_MODE = os.environ.get('GAME_MODE', "desktop")  # "browser" or "desktop"
HUMAN_MOUSE = os.environ.get('HUMAN_MOUSE', '1') == '1'
HUMAN_KEYBOARD = os.environ.get('HUMAN_KEYBOARD', '1') == '1'
MOUSE_ENABLED = os.environ.get('MOUSE_ENABLED', '1') == '1'
KEYBOARD_ENABLED = os.environ.get('KEYBOARD_ENABLED', '1') == '1'

BROWSER_URL = os.environ.get('GAME_PATH', "https://lom.joynetgame.com") if GAME_MODE == "browser" else "https://lom.joynetgame.com"
DESKTOP_EXE = os.environ.get('GAME_PATH', "C:\\Games\\LegendsOfMushroom\\game.exe") if GAME_MODE == "desktop" else "C:\\Games\\LegendsOfMushroom\\game.exe"
GAME_WINDOW_REGION = {'left': 100, 'top': 100, 'width': 1280, 'height': 720}

# ---------------------------
# LAUNCH GAME
# ---------------------------
if GAME_MODE == "browser":
    print("Launching browser game...")
    p = sync_playwright().start()
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()
    page.goto(BROWSER_URL)
    capture_region = None  # Capture whole screen for browser
else:
    print("Launching desktop game...")
    if os.path.exists(DESKTOP_EXE):
        proc = subprocess.Popen(DESKTOP_EXE)
    else:
        print(f"Desktop exe not found: {DESKTOP_EXE}. Skipping launch.")
        proc = None
    capture_region = GAME_WINDOW_REGION

# ---------------------------
# INPUT MANAGER
# ---------------------------
input_manager = InputManager()
input_manager.mouse_enabled = MOUSE_ENABLED
input_manager.keyboard_enabled = KEYBOARD_ENABLED
input_manager.human_mouse_enabled = HUMAN_MOUSE
input_manager.human_keyboard_enabled = HUMAN_KEYBOARD
timing = HumanTiming()

# ---------------------------
# VISION + GAME STATE
# ---------------------------
ui_detector = YOLODetector(model="yolov8n.pt")  # Adjust model path
resource_reader = ResourceReader()
state_extractor = StateExtractor()
progress_tracker = ProgressTracker()
reward_engine = RewardEngine()

# ---------------------------
# RL AGENT
# ---------------------------
agent = RLAgent()  # Simplified

def execute_action(input_manager, action):
    if action[0] == "mouse":
        input_manager.click(action[1], action[2])
    elif action[0] == "key":
        input_manager.press_key(action[1])

# ---------------------------
# INPUT DISCOVERY
# ---------------------------
discovery = InputDiscovery(COMMON_KEYS)
frame_prev = capture_screen(capture_region)
valid_actions = []

for _ in range(50):  # try 50 random actions
    action = discovery.random_action()
    execute_action(input_manager, action)
    time.sleep(0.1)  # Small delay
    frame_new = capture_screen(capture_region)
    diff = discovery.screen_difference(frame_prev, frame_new)
    if diff > 5:
        valid_actions.append(action)
    frame_prev = frame_new

agent.action_space = valid_actions

# ---------------------------
# TRAINING LOOP
# ---------------------------
print("Starting training loop... Press Ctrl+C to stop.")

try:
    while True:
        frame = capture_screen(capture_region)
        ui_elements = ui_detector.detect(frame)

        text = resource_reader.read_text(frame)
        resources = state_extractor.extract(text)

        # Compute reward
        xp_gain = progress_tracker.compute_reward(resources) if resources else 0
        reward = reward_engine.compute(xp_gain, damage=0, levelup=0)  # Adjust

        # Get state vector
        state_vector = resources if resources else [0, 0, 0, 0, 0]

        action_idx = agent.act(state_vector)

        # Map action_idx to actual action
        if action_idx < len(valid_actions):
            action = valid_actions[action_idx]
            execute_action(input_manager, action)

        # Agent learns (placeholder)
        # agent.train_step(states, actions, rewards, next_states)

        # Optional: small pause for stability
        time.sleep(0.05)

except KeyboardInterrupt:
    print("Training stopped by user.")
    if GAME_MODE == "browser":
        browser.close()
        p.stop()
    else:
        if proc:
            proc.terminate()
