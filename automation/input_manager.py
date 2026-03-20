from automation.mouse_controller import MouseController
from automation.keyboard_controller import KeyboardController
from vision.screen_capture import capture_screen
from automation.game_launcher import focus_window, get_window_region
import time


class InputManager:

    def __init__(self, enable_game_state=True, antiban_config=None):
        self.mouse = MouseController()
        self.keyboard = KeyboardController()
        self._game_state = None
        self._agent = None

        self.mouse_enabled = True
        self.keyboard_enabled = True
        self.game_state_enabled = enable_game_state
        # Anti-ban config
        self.antiban = antiban_config or {
            'random_delay': True,
            'random_breaks': True,
            'human_mouse': True,
            'human_keyboard': True,
        }
        self.last_break_time = time.time()
        self.break_interval = 60 + 60 * (0.5 - time.time() % 1)  # randomize
        self.break_duration = 2 + 3 * (0.5 - time.time() % 1)
        self.game_mode = "browser"  # "browser" or "desktop"

    def _ensure_game_state(self):
        if not self.game_state_enabled:
            return None
        if self._game_state is None:
            from automation.game_state import GameStateTracker

            self._game_state = GameStateTracker()
        return self._game_state

    def _ensure_agent(self):
        if not self.game_state_enabled:
            return None
        if self._agent is None:
            from ai.transformer_policy import RLAgent

            self._agent = RLAgent()
        return self._agent

    @property
    def game_state(self):
        return self._ensure_game_state()

    @game_state.setter
    def game_state(self, value):
        self._game_state = value

    @property
    def agent(self):
        return self._ensure_agent()

    @agent.setter
    def agent(self, value):
        self._agent = value

    def click(self, x, y):
        # Anti-ban: random break
        if self.antiban.get('random_breaks', True):
            now = time.time()
            if now - self.last_break_time > self.break_interval:
                time.sleep(self.break_duration)
                self.last_break_time = now
        # Anti-ban: random delay
        if self.antiban.get('random_delay', True):
            time.sleep(0.05 + 0.2 * (0.5 - time.time() % 1))
        if self.mouse_enabled:
            self.mouse.click(x, y, human_like=self.antiban.get('human_mouse', True))

    def press_key(self, key):
        # Anti-ban: random break
        if self.antiban.get('random_breaks', True):
            now = time.time()
            if now - self.last_break_time > self.break_interval:
                time.sleep(self.break_duration)
                self.last_break_time = now
        # Anti-ban: random delay
        if self.antiban.get('random_delay', True):
            time.sleep(0.05 + 0.2 * (0.5 - time.time() % 1))
        if self.keyboard_enabled:
            self.keyboard.press(key, human_like=self.antiban.get('human_keyboard', True))

    def update_game_state(self, frame):

        """Update and return the current game state + reward."""
        if not self.game_state_enabled:
            return None, 0.0

        game_state = self._ensure_game_state()
        if game_state is None:
            return None, 0.0
        return game_state.update(frame)

    def execute_behavior_blocks(self, behavior_blocks, game_state, editor=None):
        """Execute behavior blocks based on conditions and connections.

        Supports both the legacy dict-based flow and the new BehaviorGraph engine.
        """
        from behavior.graph_builder import BehaviorGraphBuilder
        from behavior.graph_engine import BehaviorGraph

        if isinstance(behavior_blocks, BehaviorGraph):
            behavior_blocks.execute(game_state)
            return

        # If the behavior graph is a dict from the editor, build BehaviorGraph for execution.
        try:
            graph = BehaviorGraphBuilder.build_from_dict(behavior_blocks, input_manager=self)
            graph.execute(game_state)
            return
        except Exception:
            # Fallback to legacy execution if graph building fails
            pass

        executed = set()

        def execute_block(block_id):
            if block_id in executed:
                return
            executed.add(block_id)
            block = behavior_blocks.get(block_id, {})
            if editor:
                editor.highlight_block(block_id, active=True)
            if block.get("type") == "state":
                condition = block.get("condition", "")
                try:
                    if not eval(condition, {}, game_state):
                        if editor:
                            editor.highlight_block(block_id, active=False)
                        return  # condition not met
                except Exception as e:
                    print(f"Error evaluating condition {condition}: {e}")
                    if editor:
                        editor.highlight_block(block_id, active=False)
                    return
            elif block.get("type") == "action":
                action_type = block.get("action")
                target = block.get("target")
                if action_type == "click" and isinstance(target, tuple) and len(target) == 2:
                    x, y = target
                    self.click(x, y)
                elif action_type == "key" and target:
                    self.press_key(target)
            # Execute connected blocks
            for conn_id in block.get("connections", []):
                execute_block(conn_id)
            if editor:
                editor.highlight_block(block_id, active=False)

        # Start from blocks with no incoming connections (roots)
        roots = [bid for bid, b in behavior_blocks.items() if not any(bid in b.get("connections", []) for b in behavior_blocks.values())]
        for root in roots:
            execute_block(root)

    def start_training_loop(self, game_window_title=None):
        """Unified training loop for browser or desktop games."""
        region = None
        if self.game_mode == "desktop" and game_window_title:
            region = get_window_region(game_window_title)
            focus_window(game_window_title)

        while True:
            frame = capture_screen(region)
            state_vector, reward = self.update_game_state(frame)
            if state_vector:
                self.sample_and_execute(state_vector)
            time.sleep(1)  # Adjust timing
