from PySide6.QtWidgets import QWidget,QVBoxLayout,QCheckBox,QRadioButton,QButtonGroup,QLabel

class SettingsPanel(QWidget):

    def __init__(self,input_manager):

        super().__init__()

        self.input_manager = input_manager

        layout = QVBoxLayout()
        # Section: Game Mode
        game_mode_label = QLabel("<b>Game Mode:</b>")
        layout.addWidget(game_mode_label)
        self.browser_radio = QRadioButton("Browser Game")
        self.desktop_radio = QRadioButton("Desktop / Non-Browser Game")
        self.browser_radio.setChecked(True)
        self.game_mode_group = QButtonGroup()
        self.game_mode_group.addButton(self.browser_radio)
        self.game_mode_group.addButton(self.desktop_radio)
        self.browser_radio.setToolTip("Use for web-based games.")
        self.desktop_radio.setToolTip("Use for desktop games.")
        self.browser_radio.toggled.connect(self.toggle_game_mode)
        self.desktop_radio.toggled.connect(self.toggle_game_mode)
        mode_row = QWidget()
        mode_layout = QVBoxLayout()
        mode_layout.addWidget(self.browser_radio)
        mode_layout.addWidget(self.desktop_radio)
        mode_row.setLayout(mode_layout)
        layout.addWidget(mode_row)

        # Section: Input Controls
        input_label = QLabel("<b>Input Controls:</b>")
        layout.addWidget(input_label)
        self.mouse_toggle = QCheckBox("Enable Mouse Control")
        self.mouse_toggle.setChecked(True)
        self.mouse_toggle.setToolTip("Toggle mouse input for agent.")
        self.keyboard_toggle = QCheckBox("Enable Keyboard Control")
        self.keyboard_toggle.setChecked(True)
        self.keyboard_toggle.setToolTip("Toggle keyboard input for agent.")
        self.mouse_toggle.stateChanged.connect(self.toggle_mouse)
        self.keyboard_toggle.stateChanged.connect(self.toggle_keyboard)
        input_row = QWidget()
        input_layout = QVBoxLayout()
        input_layout.addWidget(self.mouse_toggle)
        input_layout.addWidget(self.keyboard_toggle)
        input_row.setLayout(input_layout)
        layout.addWidget(input_row)

        # Section: Humanization
        human_label = QLabel("<b>Humanization:</b>")
        layout.addWidget(human_label)
        self.human_mouse = QCheckBox("Human-like Mouse Movement")
        self.human_mouse.setChecked(True)
        self.human_mouse.setToolTip("Simulate human mouse movement.")
        self.human_keyboard = QCheckBox("Human-like Keyboard Timing")
        self.human_keyboard.setChecked(True)
        self.human_keyboard.setToolTip("Simulate human keyboard timing.")
        self.randomized_behavior = QCheckBox("Randomized Input Behavior")
        self.randomized_behavior.setChecked(True)
        self.randomized_behavior.setToolTip("Add randomness to agent actions.")
        self.game_state = QCheckBox("Enable Game State Understanding")
        self.game_state.setChecked(True)
        self.game_state.setToolTip("Allow agent to understand game state.")
        self.human_mouse.stateChanged.connect(self.toggle_human_mouse)
        self.human_keyboard.stateChanged.connect(self.toggle_human_keyboard)
        self.randomized_behavior.stateChanged.connect(self.toggle_randomized)
        self.game_state.stateChanged.connect(self.toggle_game_state)
        human_row = QWidget()
        human_layout = QVBoxLayout()
        human_layout.addWidget(self.human_mouse)
        human_layout.addWidget(self.human_keyboard)
        human_layout.addWidget(self.randomized_behavior)
        human_layout.addWidget(self.game_state)
        human_row.setLayout(human_layout)
        layout.addWidget(human_row)

        self.setLayout(layout)

    def toggle_mouse(self):

        self.input_manager.mouse_enabled = self.mouse_toggle.isChecked()

    def toggle_keyboard(self):

        self.input_manager.keyboard_enabled = self.keyboard_toggle.isChecked()

    def toggle_human_mouse(self):

        self.input_manager.human_mouse_enabled = self.human_mouse.isChecked()

    def toggle_human_keyboard(self):

        self.input_manager.human_keyboard_enabled = self.human_keyboard.isChecked()

    def toggle_randomized(self):

        self.input_manager.randomized_enabled = self.randomized_behavior.isChecked()

    def toggle_game_state(self):

        self.input_manager.game_state_enabled = self.game_state.isChecked()

    def toggle_game_mode(self):

        self.input_manager.game_mode = "browser" if self.browser_radio.isChecked() else "desktop"