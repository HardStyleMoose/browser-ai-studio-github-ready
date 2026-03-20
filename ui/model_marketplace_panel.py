# Model Marketplace Panel for BrowserAI Studio

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QListWidget, QHBoxLayout, QFileDialog, QGroupBox, QSpinBox, QTextEdit
from ui.ratings_helper import load_ratings, get_ratings, submit_rating
import os

class ModelMarketplacePanel(QWidget):
    def __init__(self, models_dir="models/"):
        super().__init__()
        self.models_dir = models_dir
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Model Marketplace"))
        self.model_list = QListWidget()
        layout.addWidget(self.model_list)
        btns = QHBoxLayout()
        self.upload_btn = QPushButton("Upload Model")
        self.download_btn = QPushButton("Download Model")
        self.import_btn = QPushButton("Import Behavior Graph")
        self.export_btn = QPushButton("Export Behavior Graph")
        btns.addWidget(self.upload_btn)
        btns.addWidget(self.download_btn)
        btns.addWidget(self.import_btn)
        btns.addWidget(self.export_btn)
        layout.addLayout(btns)
        self.upload_btn.clicked.connect(self.upload_model)
        self.download_btn.clicked.connect(self.download_model)
        self.import_btn.clicked.connect(self.import_graph)
        self.export_btn.clicked.connect(self.export_graph)

        # Ratings/comments UI
        self.rating_box = QGroupBox("Model Ratings & Comments")
        rating_layout = QVBoxLayout(self.rating_box)
        self.rating_label = QLabel("Select a model to view ratings.")
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

        self.model_list.currentTextChanged.connect(self.display_ratings)
        self.refresh_models()

        # Real-time refresh timer
        from PySide6.QtCore import QTimer
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self._realtime_refresh)
        self.refresh_timer.start(1000)

    def _realtime_refresh(self):
        self.refresh_models()
        current_model = self.model_list.currentItem().text() if self.model_list.currentItem() else None
        if current_model:
            self.display_ratings(current_model)

    def display_ratings(self, model_name):
        ratings = load_ratings(self.models_dir)
        model_ratings = get_ratings(ratings, model_name)
        if not model_ratings["ratings"]:
            self.rating_label.setText("No ratings yet.")
        else:
            avg = sum(model_ratings["ratings"]) / len(model_ratings["ratings"])
            self.rating_label.setText(f"Average Rating: {avg:.2f} ({len(model_ratings['ratings'])} ratings)")
        comments = model_ratings.get("comments", [])
        self.comments_box.setPlainText("\n---\n".join(comments[-5:]))

    def submit_rating(self):
        model_name = self.model_list.currentItem().text() if self.model_list.currentItem() else None
        if not model_name:
            return
        stars = self.stars_spin.value()
        comment = self.comment_edit.toPlainText().strip()
        submit_rating(self.models_dir, model_name, stars, comment)
        self.display_ratings(model_name)
        self.comment_edit.clear()

    def refresh_models(self):
        self.model_list.clear()
        if os.path.exists(self.models_dir):
            for f in os.listdir(self.models_dir):
                if f.endswith(".pt") or f.endswith(".onnx"):
                    self.model_list.addItem(f)

    def upload_model(self):
        # Placeholder: implement upload logic (e.g., to a server or cloud)
        pass

    def download_model(self):
        # Placeholder: implement download logic (e.g., from a server or cloud)
        pass

    def import_graph(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Import Behavior Graph", "", "JSON Files (*.json)")
        if filename:
            # Placeholder: integrate with behavior editor
            pass

    def export_graph(self):
        filename, _ = QFileDialog.getSaveFileName(self, "Export Behavior Graph", "behavior_graph.json", "JSON Files (*.json)")
        if filename:
            # Placeholder: integrate with behavior editor
            pass
