import cv2
import numpy as np
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout, QHBoxLayout, QPushButton
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QPixmap, QImage
import sys
import os

# Ensure project root is on sys.path
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from vision.screen_capture import capture_screen
from vision.yolo_detector import YOLODetector
from vision.resource_reader import ResourceReader
from ai.state_extractor import StateExtractor


class DebugOverlayWindow(QWidget):
    def __init__(self, game_region=None, main_window=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI Debug Overlay")
        self.setGeometry(100, 100, 1280, 720)
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.Tool)

        # Initialize components
        self.yolo_detector = YOLODetector()
        self.resource_reader = ResourceReader()
        self.state_extractor = StateExtractor()
        self.game_region = game_region
        self.main_window = main_window

        # UI Layout
        layout = QVBoxLayout()

        # Image display
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.image_label)

        # Info panel
        info_layout = QHBoxLayout()
        self.action_label = QLabel("Current Action: None")
        self.state_label = QLabel("Game State: N/A")
        self.fps_label = QLabel("FPS: 0")

        info_layout.addWidget(self.action_label)
        info_layout.addWidget(self.state_label)
        info_layout.addWidget(self.fps_label)
        layout.addLayout(info_layout)

        # Control buttons
        button_layout = QHBoxLayout()
        self.pause_btn = QPushButton("Pause")
        self.pause_btn.clicked.connect(self.toggle_pause)
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.close)

        button_layout.addWidget(self.pause_btn)
        button_layout.addStretch()
        button_layout.addWidget(self.close_btn)
        layout.addLayout(button_layout)

        self.setLayout(layout)

        # State
        self.paused = False
        self.last_frame_time = 0
        self.fps = 0

        # Timer for updates
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_overlay)
        self.timer.start(100)  # ~10 FPS

        # Initial update
        self.update_overlay()

    def toggle_pause(self):
        self.paused = not self.paused
        self.pause_btn.setText("Resume" if self.paused else "Pause")

    def update_overlay(self):
        if self.paused:
            return

        try:
            # Capture screen
            frame = capture_screen(self.game_region)

            # Run YOLO detection
            yolo_results = self.yolo_detector.detect(frame)

            # Draw YOLO bounding boxes
            if yolo_results:
                frame = self.draw_yolo_boxes(frame, yolo_results)

            # OCR on full frame (or regions)
            ocr_text = self.resource_reader.read_text(frame)
            frame = self.overlay_ocr_text(frame, ocr_text)

            # Extract state from OCR
            state_values = self.state_extractor.extract(ocr_text)
            self.update_state_display(state_values)

            # Update action display
            current_action = "None"
            if self.main_window and hasattr(self.main_window, 'current_state'):
                current_action = self.main_window.current_state.get('action', 'None')
            self.update_action_display(current_action)

            # Calculate FPS
            current_time = cv2.getTickCount() / cv2.getTickFrequency()
            if self.last_frame_time > 0:
                self.fps = 1.0 / (current_time - self.last_frame_time)
            self.last_frame_time = current_time
            self.fps_label.setText(f"FPS: {self.fps:.1f}")

            # Convert to QPixmap and display
            self.display_frame(frame)

        except Exception as e:
            print(f"Debug overlay error: {e}")

    def draw_yolo_boxes(self, frame, results):
        """Draw YOLO bounding boxes on frame."""
        annotated_frame = frame.copy()

        # YOLO results have boxes, conf, cls
        try:
            if hasattr(results, 'boxes') and results.boxes is not None:
                boxes = results.boxes
                for box in boxes:
                    # Get box coordinates
                    xyxy = box.xyxy
                    if len(xyxy) > 0:
                        x1, y1, x2, y2 = xyxy[0].cpu().numpy()
                        conf = box.conf[0].cpu().numpy() if hasattr(box, 'conf') and len(box.conf) > 0 else 0.0
                        cls = int(box.cls[0].cpu().numpy()) if hasattr(box, 'cls') and len(box.cls) > 0 else 0

                        # Draw rectangle
                        cv2.rectangle(annotated_frame, (int(x1), int(y1)), (int(x2), int(y2)), (0, 255, 0), 2)

                        # Draw label
                        label = f"Class {cls}: {conf:.2f}"
                        if hasattr(results, 'names') and results.names:
                            label = f"{results.names.get(cls, f'Class {cls}')}: {conf:.2f}"
                        cv2.putText(annotated_frame, label, (int(x1), int(y1)-10),
                                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
        except Exception as e:
            print(f"YOLO drawing error: {e}")

        return annotated_frame

    def overlay_ocr_text(self, frame, text):
        """Overlay OCR text on frame."""
        annotated_frame = frame.copy()

        # Simple overlay - put text in top-left
        if text.strip():
            # Split text into lines and display first few
            lines = text.strip().split('\n')[:5]  # Limit to 5 lines
            y_offset = 30
            for line in lines:
                if line.strip():
                    cv2.putText(annotated_frame, line.strip(), (10, y_offset),
                               cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
                    y_offset += 25

        return annotated_frame

    def update_state_display(self, state_values):
        """Update state display from extracted values and main window state."""
        state_text = "Game State: "
        if self.main_window and hasattr(self.main_window, 'current_state'):
            mw_state = self.main_window.current_state
            state_parts = []
            if 'xp' in mw_state:
                state_parts.append(f"XP={mw_state['xp']}")
            if 'gold' in mw_state:
                state_parts.append(f"Gold={mw_state['gold']}")
            if 'reward' in mw_state:
                state_parts.append(f"Reward={mw_state['reward']:.2f}")
            if state_parts:
                state_text += ", ".join(state_parts)
            else:
                state_text += "N/A"
        elif len(state_values) >= 2:
            state_text += f"HP={state_values[0]}, Gold={state_values[1]}"
        else:
            state_text += "N/A"
        
        self.state_label.setText(state_text)

    def update_action_display(self, action):
        """Update current action display."""
        self.action_label.setText(f"Current Action: {action}")

    def display_frame(self, frame):
        """Convert OpenCV frame to QPixmap and display."""
        # Convert BGR to RGB
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # Create QImage
        height, width, channel = rgb_frame.shape
        bytes_per_line = 3 * width
        q_img = QImage(rgb_frame.data, width, height, bytes_per_line, QImage.Format_RGB888)

        # Create QPixmap and scale to fit
        pixmap = QPixmap.fromImage(q_img)
        if not pixmap.isNull():
            scaled_pixmap = pixmap.scaled(self.image_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.image_label.setPixmap(scaled_pixmap)
        else:
            self.image_label.setText("No Image")

    def closeEvent(self, event):
        """Clean up timer on close."""
        self.timer.stop()
        super().closeEvent(event)