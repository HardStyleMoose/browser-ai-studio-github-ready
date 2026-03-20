# Workflow Sharing and Import for BrowserAI Studio

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QLabel, QFileDialog, QHBoxLayout, QLineEdit,
    QGroupBox, QSpinBox, QTextEdit
)
import json
import os
try:
    import qrcode
except ImportError:
    qrcode = None
from PySide6.QtGui import QPixmap, QImage
from PySide6.QtCore import Qt
import io
from .ratings_helper import load_ratings, get_ratings, submit_rating

class WorkflowSharePanel(QWidget):
    def __init__(self, behavior_editor=None):
        super().__init__()
        self.behavior_editor = behavior_editor
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Share or Import Behavior Workflows"))
        btns = QHBoxLayout()
        self.export_btn = QPushButton("Export Workflow")
        self.import_btn = QPushButton("Import Workflow")
        btns.addWidget(self.export_btn)
        btns.addWidget(self.import_btn)
        layout.addLayout(btns)
        self.link_edit = QLineEdit()
        self.link_edit.setPlaceholderText("Paste or share workflow link here")
        layout.addWidget(self.link_edit)
        self.qr_label = QLabel()
        layout.addWidget(self.qr_label)
        self.export_btn.clicked.connect(self.export_workflow)
        self.import_btn.clicked.connect(self.import_workflow)

        # Ratings/comments UI
        self.rating_box = QGroupBox("Workflow Ratings & Comments")
        rating_layout = QVBoxLayout(self.rating_box)
        self.rating_label = QLabel("Select a workflow to view ratings.")
        rating_layout.addWidget(self.rating_label)
        self.stars_spin = QSpinBox()
        self.stars_spin.setRange(1, 5)
        self.stars_spin.setPrefix("Stars: ")
        self.comment_edit = QTextEdit()
        self.comment_edit.setPlaceholderText("Leave a comment...")
        self.submit_btn = QPushButton("Submit Rating/Comment")
        self.submit_btn.clicked.connect(self.submit_rating)
        rating_layout.addWidget(self.stars_spin)
        rating_layout.addWidget(self.comment_edit)
        rating_layout.addWidget(self.submit_btn)
        self.comments_label = QLabel("Recent Comments:")
        rating_layout.addWidget(self.comments_label)
        self.comments_box = QTextEdit()
        self.comments_box.setReadOnly(True)
        rating_layout.addWidget(self.comments_box)
        layout.addWidget(self.rating_box)

        self.current_workflow = None

        # Real-time refresh timer for ratings/comments
        from PySide6.QtCore import QTimer
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(1000)  # 1 second
        self.refresh_timer.timeout.connect(self._refresh_ratings_comments)
        self.refresh_timer.start()

    def _refresh_ratings_comments(self):
        if self.current_workflow:
            self.display_ratings(self.current_workflow)

    def display_ratings(self, workflow_name):
        ratings = load_ratings("workflows")
        workflow_ratings = get_ratings(ratings, workflow_name)
        if not workflow_ratings["ratings"]:
            self.rating_label.setText("No ratings yet.")
        else:
            avg = sum(workflow_ratings["ratings"]) / len(workflow_ratings["ratings"])
            self.rating_label.setText(f"Average Rating: {avg:.2f} ({len(workflow_ratings['ratings'])} ratings)")
        comments = workflow_ratings.get("comments", [])
        self.comments_box.setPlainText("\n---\n".join(comments[-5:]))

    def submit_rating(self):
        workflow_name = self.current_workflow
        if not workflow_name:
            return
        stars = self.stars_spin.value()
        comment = self.comment_edit.toPlainText().strip()
        submit_rating("workflows", workflow_name, stars, comment)
        self.display_ratings(workflow_name)
        self.comment_edit.clear()

    def export_workflow(self):
        if not self.behavior_editor:
            return
        graph = self.behavior_editor.get_behavior_graph()
        data = json.dumps(graph)
        filename, _ = QFileDialog.getSaveFileName(self, "Export Workflow", "workflow.json", "JSON Files (*.json)")
        if filename:
            with open(filename, "w", encoding="utf-8") as f:
                f.write(data)
            # Generate QR code for sharing (if qrcode is available)
            if qrcode:
                qr = qrcode.make(data)
                buf = io.BytesIO()
                qr.save(buf, format="PNG")
                buf.seek(0)
                image = QImage()
                image.loadFromData(buf.read(), "PNG")
                self.qr_label.setPixmap(QPixmap.fromImage(image).scaled(180, 180, Qt.KeepAspectRatio))
            else:
                self.qr_label.setText("qrcode module not installed")
            # Set current workflow for rating
            self.current_workflow = os.path.basename(filename)
            self.display_ratings(self.current_workflow)

    def import_workflow(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Import Workflow", "", "JSON Files (*.json)")
        if filename and self.behavior_editor:
            with open(filename, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.behavior_editor.load_behavior(filename)
            # Set current workflow for rating
            import os
            self.current_workflow = os.path.basename(filename)
            self.display_ratings(self.current_workflow)
