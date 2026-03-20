import os
import cv2
import numpy as np
from ultralytics import YOLO
from vision.screen_capture import capture_screen


class DatasetPipeline:
    def __init__(self, dataset_dir="datasets/ui_dataset"):
        self.dataset_dir = dataset_dir
        os.makedirs(dataset_dir, exist_ok=True)
        os.makedirs(os.path.join(dataset_dir, "images"), exist_ok=True)
        os.makedirs(os.path.join(dataset_dir, "labels"), exist_ok=True)

    def collect_sample(self, region=None, label_data=None):
        """Collect a sample image and save with labels."""
        frame = capture_screen(region)
        img_path = os.path.join(self.dataset_dir, "images", f"sample_{len(os.listdir(os.path.join(self.dataset_dir, 'images')))}.jpg")
        cv2.imwrite(img_path, frame)

        if label_data:
            # Save YOLO format labels
            label_path = img_path.replace("images", "labels").replace(".jpg", ".txt")
            with open(label_path, "w") as f:
                for label in label_data:
                    # YOLO format: class x_center y_center width height
                    f.write(f"{label['class']} {label['x']} {label['y']} {label['w']} {label['h']}\n")

    def train_yolo(self, model_path="models/ui_detector.pt", epochs=10):
        """Train YOLO model on collected dataset."""
        model = YOLO("yolov8n.pt")  # Start from pretrained
        model.train(data=self.dataset_dir, epochs=epochs, imgsz=640)
        model.save(model_path)
        return model