from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout
from PySide6.QtCore import QTimer


class StateDisplayPanel(QWidget):
    def __init__(self, input_manager):
        super().__init__()
        self.input_manager = input_manager
        layout = QVBoxLayout()

        self.state_labels = {}
        self.reward_label = QLabel("Reward: 0.0")
        layout.addWidget(self.reward_label)

        # Add labels for common states
        states = ['gold', 'xp', 'level', 'health', 'damage']
        for state in states:
            label = QLabel(f"{state.capitalize()}: N/A")
            self.state_labels[state] = label
            layout.addWidget(label)

        self.setLayout(layout)

        # Timer to update every second
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_display)
        self.timer.start(1000)  # 1 second

    def update_display(self):
        if self.input_manager.game_state and self.input_manager.game_state_enabled:
            state = self.input_manager.game_state.last_state
            reward = self.input_manager.game_state.last_reward
            self.reward_label.setText(f"Reward: {reward:.2f}")
            for key, label in self.state_labels.items():
                value = state.get(key, 'N/A')
                label.setText(f"{key.capitalize()}: {value}")
        else:
            self.reward_label.setText("Reward: N/A")
            for label in self.state_labels.values():
                label.setText(f"{label.text().split(':')[0]}: N/A")