import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.attendance_system import database


FACE_IMAGES_DIR = database.PROJECT_ROOT / "web" / "static" / "student_faces"
MODELS_DIR = database.PROJECT_ROOT / "models"
TRAINER_PATH = MODELS_DIR / "trainer.yml"
LABEL_MAP_PATH = MODELS_DIR / "label_map.json"


def collect_training_images(images_dir):
    image_paths = []
    valid_suffixes = {".jpg", ".jpeg", ".png"}

    for path in sorted(images_dir.iterdir()):
        if path.is_file() and path.suffix.lower() in valid_suffixes:
            image_paths.append((path, path.stem))
        elif path.is_dir():
            for sample_path in sorted(path.iterdir()):
                if sample_path.is_file() and sample_path.suffix.lower() in valid_suffixes:
                    image_paths.append((sample_path, path.name))

    return image_paths


def get_images_and_labels(images_dir):
    detector = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )

    image_paths = collect_training_images(images_dir)

    roll_numbers = sorted({roll_no for _, roll_no in image_paths})
    label_by_roll_no = {
        roll_no: index
        for index, roll_no in enumerate(roll_numbers, start=1)
    }

    face_samples = []
    labels = []

    for image_path, roll_no in image_paths:
        try:
            image = Image.open(image_path).convert("L")
            image_array = np.array(image, "uint8")
            faces = detector.detectMultiScale(
                image_array,
                scaleFactor=1.2,
                minNeighbors=5,
            )

            if len(faces) == 0:
                print(f"No face found in {image_path}")

            for x, y, w, h in faces:
                face_samples.append(image_array[y:y + h, x:x + w])
                labels.append(label_by_roll_no[roll_no])
        except Exception as exc:
            print(f"Error in {image_path}: {exc}")

    label_map = {
        str(label): roll_no
        for roll_no, label in label_by_roll_no.items()
    }

    return face_samples, labels, label_map


def train_model():
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    FACE_IMAGES_DIR.mkdir(parents=True, exist_ok=True)

    recognizer = cv2.face.LBPHFaceRecognizer_create()
    faces, labels, label_map = get_images_and_labels(FACE_IMAGES_DIR)

    if not faces:
        print("No faces found. Add clear student photos before training.")
        return 1

    recognizer.train(faces, np.array(labels))
    recognizer.write(str(TRAINER_PATH))
    LABEL_MAP_PATH.write_text(
        json.dumps(label_map, indent=2),
        encoding="utf-8",
    )

    print(f"Training completed for {len(label_map)} student label(s).")
    print(f"Model: {TRAINER_PATH}")
    print(f"Label map: {LABEL_MAP_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(train_model())
