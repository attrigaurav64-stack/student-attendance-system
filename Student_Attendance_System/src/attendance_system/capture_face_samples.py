import argparse
import sqlite3
import sys
from pathlib import Path

import cv2


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.attendance_system import database


FACE_IMAGES_DIR = database.PROJECT_ROOT / "web" / "static" / "student_faces"


def student_exists(roll_no):
    with sqlite3.connect(database.DATABASE_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM students WHERE roll_no=?", (roll_no,))
        return cursor.fetchone() is not None


def capture_samples(roll_no, sample_count):
    if not student_exists(roll_no):
        print(f"No student found for roll number {roll_no}.")
        return 1

    output_dir = FACE_IMAGES_DIR / roll_no
    output_dir.mkdir(parents=True, exist_ok=True)

    detector = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
    camera = cv2.VideoCapture(0)

    if not camera.isOpened():
        print("Camera could not be opened.")
        return 1

    captured = 0

    try:
        while captured < sample_count:
            success, frame = camera.read()
            if not success:
                print("Camera frame could not be read.")
                break

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = detector.detectMultiScale(
                gray,
                scaleFactor=1.2,
                minNeighbors=5,
            )

            for x, y, w, h in faces[:1]:
                captured += 1
                face = gray[y:y + h, x:x + w]
                sample_path = output_dir / f"sample_{captured:03d}.jpg"
                cv2.imwrite(str(sample_path), face)

                cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 180, 0), 2)
                cv2.putText(
                    frame,
                    f"Captured {captured}/{sample_count}",
                    (x, y - 10),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (0, 180, 0),
                    2,
                )

            if len(faces) == 0:
                cv2.putText(
                    frame,
                    "Align face in camera",
                    (20, 36),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (0, 0, 255),
                    2,
                )

            cv2.imshow("Capture Student Face Samples", frame)
            if cv2.waitKey(1) == ord("q"):
                break
    finally:
        camera.release()
        cv2.destroyAllWindows()

    print(f"Captured {captured} sample(s) for roll number {roll_no}.")
    return 0 if captured > 0 else 1


def main():
    parser = argparse.ArgumentParser(description="Capture student face samples.")
    parser.add_argument("--roll-no", required=True)
    parser.add_argument("--samples", type=int, default=20)
    args = parser.parse_args()

    return capture_samples(args.roll_no, args.samples)


if __name__ == "__main__":
    raise SystemExit(main())
