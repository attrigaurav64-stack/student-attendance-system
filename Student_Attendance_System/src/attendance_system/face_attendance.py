import datetime
import json
import sqlite3
import sys
from pathlib import Path

import cv2


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.attendance_system import database


MODELS_DIR = PROJECT_ROOT / "models"
TRAINER_PATH = MODELS_DIR / "trainer.yml"
LABEL_MAP_PATH = MODELS_DIR / "label_map.json"
FACE_SUBJECT = "Face Recognition"
CONFIDENCE_LIMIT = 70


def load_recognizer():
    if not TRAINER_PATH.exists() or not LABEL_MAP_PATH.exists():
        raise FileNotFoundError(
            "Face model is not trained. Run the training step before starting face attendance."
        )

    recognizer = cv2.face.LBPHFaceRecognizer_create()
    recognizer.read(str(TRAINER_PATH))

    label_map = json.loads(LABEL_MAP_PATH.read_text(encoding="utf-8"))
    return recognizer, label_map


def mark_present(roll_no):
    today = str(datetime.date.today())

    with sqlite3.connect(database.DATABASE_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM students WHERE roll_no=?",
            (roll_no,),
        )
        student = cursor.fetchone()

        if not student:
            return None

        student_name = student[0]
        cursor.execute("""
        SELECT id
        FROM attendance
        WHERE roll_no=? AND subject=? AND date=?
        """, (roll_no, FACE_SUBJECT, today))
        existing = cursor.fetchone()

        if existing:
            cursor.execute("""
            UPDATE attendance
            SET student_name=?, status='Present'
            WHERE id=?
            """, (student_name, existing[0]))
        else:
            cursor.execute("""
            INSERT INTO attendance (
                roll_no, student_name, subject, date, status
            )
            VALUES (?, ?, ?, ?, 'Present')
            """, (roll_no, student_name, FACE_SUBJECT, today))

        conn.commit()
        return student_name


def run_face_attendance():
    recognizer, label_map = load_recognizer()
    face_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )

    camera = cv2.VideoCapture(0)
    if not camera.isOpened():
        raise RuntimeError("Camera could not be opened.")

    marked_roll_numbers = set()

    try:
        while True:
            success, frame = camera.read()
            if not success:
                break

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(
                gray,
                scaleFactor=1.2,
                minNeighbors=5,
            )

            for x, y, w, h in faces:
                label, confidence = recognizer.predict(gray[y:y + h, x:x + w])
                roll_no = label_map.get(str(label))
                display_name = "Unknown"
                color = (0, 0, 255)

                if roll_no and confidence < CONFIDENCE_LIMIT:
                    if roll_no not in marked_roll_numbers:
                        student_name = mark_present(roll_no)
                        if student_name:
                            marked_roll_numbers.add(roll_no)
                    else:
                        student_name = None

                    if student_name or roll_no in marked_roll_numbers:
                        display_name = student_name or roll_no
                        color = (0, 180, 0)

                cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
                cv2.putText(
                    frame,
                    display_name,
                    (x, y - 10),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    color,
                    2,
                )

            cv2.imshow("AttendancePro Face Attendance", frame)
            if cv2.waitKey(1) == ord("q"):
                break
    finally:
        camera.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    run_face_attendance()
