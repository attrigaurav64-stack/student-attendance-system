import base64
import datetime
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote
import pandas as pd
from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
)

# ReportLab Imports moved to top-level to prevent Pylance scope warnings
from reportlab.lib import colors, styles
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from . import database

PROJECT_ROOT = database.PROJECT_ROOT
WEB_DIR = PROJECT_ROOT / "web"
EXPORT_DIR = PROJECT_ROOT / "exports"
MODELS_DIR = PROJECT_ROOT / "models"
FACE_IMAGES_DIR = WEB_DIR / "static" / "student_faces"
TRAINER_PATH = MODELS_DIR / "trainer.yml"
LABEL_MAP_PATH = MODELS_DIR / "label_map.json"

for runtime_dir in (database.DATA_DIR, EXPORT_DIR, MODELS_DIR, FACE_IMAGES_DIR):
    runtime_dir.mkdir(parents=True, exist_ok=True)

database.connect_db(verbose=False)

app = Flask(
    __name__,
    template_folder=str(WEB_DIR / "templates"),
    static_folder=str(WEB_DIR / "static"),
)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "secret_key")


def profile_exists(cursor, role, linked_id):
    if role == "admin":
        cursor.execute("SELECT 1 FROM admins WHERE admin_id=?", (linked_id,))
    elif role == "teacher":
        cursor.execute("SELECT 1 FROM teachers WHERE teacher_id=?", (linked_id,))
    elif role == "student":
        cursor.execute("SELECT 1 FROM students WHERE roll_no=?", (linked_id,))
    else:
        return False

    return cursor.fetchone() is not None


def current_profile_id():
    return session.get('linked_id') or session.get('username')


def next_teacher_id(cursor):
    rows = cursor.execute("""
    SELECT teacher_id
    FROM teachers
    WHERE teacher_id LIKE 'TCH-%'
    """).fetchall()

    max_number = 0
    for (teacher_id,) in rows:
        try:
            max_number = max(max_number, int(teacher_id.split("-")[-1]))
        except (TypeError, ValueError):
            continue

    return f"TCH-{max_number + 1:04d}"


def upsert_attendance_record(cursor, roll_no, student_name, subject, date, status):
    cursor.execute("""
    SELECT id, status
    FROM attendance
    WHERE roll_no=? AND subject=? AND date=?
    """, (roll_no, subject, date))
    existing = cursor.fetchone()

    if existing:
        if existing[1] != status:
            cursor.execute("""
            UPDATE attendance
            SET student_name=?, status=?
            WHERE id=?
            """, (student_name, status, existing[0]))
            return "updated"
        return "existing"

    cursor.execute("""
    INSERT INTO attendance (roll_no, student_name, subject, date, status)
    VALUES (?, ?, ?, ?, ?)
    """, (roll_no, student_name, subject, date, status))
    return "inserted"


# =====================================
# HOME PAGE
# =====================================

@app.route('/')
def home():
    return render_template(
        'login.html',
        error=None
    )


# =====================================
# LOGIN SYSTEM
# =====================================

@app.route('/login', methods=['POST'])
def login():
    username = request.form['username']
    password = request.form['password']
    role = request.form['role']

    if 'attempts' not in session:
        session['attempts'] = 0

    conn = sqlite3.connect(database.DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute("""
    SELECT id, username, role, linked_id
    FROM users
    WHERE username=?
      AND password=?
      AND role=?
      AND is_active=1
    """, (username, password, role))

    user = cursor.fetchone()
    has_profile = bool(user and profile_exists(cursor, user[2], user[3]))
    conn.close()

    if user and has_profile:
        session['user_id'] = user[0]
        session['username'] = user[1]
        session['role'] = user[2]
        session['linked_id'] = user[3]
        session['attempts'] = 0

        if user[2] == 'admin':
            return redirect('/admin')
        elif user[2] == 'teacher':
            return redirect('/teacher')
        elif user[2] == 'student':
            return redirect('/student')

    session['attempts'] += 1

    if session['attempts'] >= 4:
        error_message = "Too many failed attempts."
    else:
        error_message = f"Invalid login ID or password ({session['attempts']}/4)"

    return render_template(
        'login.html',
        error=error_message
    )


# =====================================
# ADMIN DASHBOARD
# =====================================

@app.route('/admin')
def admin_dashboard():
    if session.get('role') != 'admin':
        return redirect('/')

    conn = sqlite3.connect(database.DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM students")
    total_students = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM teachers")
    total_teachers = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM attendance")
    total_attendance = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM attendance WHERE status='Present'")
    present = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM attendance WHERE status='Absent'")
    absent = cursor.fetchone()[0]

    percentage = 0
    if total_attendance > 0:
        percentage = round((present / total_attendance) * 100, 2)

    cursor.execute("""
    SELECT COALESCE(subject, 'Unassigned') AS subject, COUNT(*) AS total
    FROM attendance
    GROUP BY COALESCE(subject, 'Unassigned')
    ORDER BY total DESC, subject ASC
    LIMIT 6
    """)
    subject_chart = cursor.fetchall()

    cursor.execute("""
    SELECT COALESCE(course, 'Unassigned') AS course, COUNT(*) AS total
    FROM students
    GROUP BY COALESCE(course, 'Unassigned')
    ORDER BY total DESC, course ASC
    LIMIT 6
    """)
    course_chart = cursor.fetchall()

    max_subject_total = max([row[1] for row in subject_chart], default=0)
    max_course_total = max([row[1] for row in course_chart], default=0)

    conn.close()

    return render_template(
        'admin_dashboard.html',
        total_students=total_students,
        total_teachers=total_teachers,
        total_attendance=total_attendance,
        percentage=percentage,
        present=present,
        absent=absent,
        subject_chart=subject_chart,
        course_chart=course_chart,
        max_subject_total=max_subject_total,
        max_course_total=max_course_total
    )


# =====================================
# MANAGE STUDENTS
# =====================================

@app.route('/manage_students')
def manage_students():
    if session.get('role') != 'admin':
        return redirect('/')

    search = request.args.get('search')

    conn = sqlite3.connect(database.DATABASE_PATH)
    cursor = conn.cursor()

    if search:
        cursor.execute("""
        SELECT roll_no, name, course, semester, section, email, phone, photo
        FROM students
        WHERE name LIKE ?
        OR roll_no LIKE ?
        """, (f'%{search}%', f'%{search}%'))
    else:
        cursor.execute("""
        SELECT roll_no, name, course, semester, section, email, phone, photo
        FROM students
        """)

    students = cursor.fetchall()
    conn.close()

    return render_template(
        'manage_students.html',
        students=students,
        face_status=request.args.get('face_status'),
        face_message=request.args.get('face_message'),
    )


# =====================================
# ADD STUDENT
# =====================================

@app.route('/add_student', methods=['POST'])
def add_student():
    if session.get('role') != 'admin':
        return redirect('/')

    roll_no = request.form['roll_no']
    name = request.form['name']
    course = request.form.get('course', 'BE CSE')
    semester = request.form.get('semester', '1')
    section = request.form.get('section', 'Section 1')
    email = request.form.get('email', '').strip()
    phone = request.form.get('phone', '').strip()
    password = request.form.get('password', '').strip() or roll_no
    photo = request.files.get('photo')

    photo_path = ""
    if photo and photo.filename:
        photo_path = f"static/student_faces/{roll_no}.jpg"
        photo.save(FACE_IMAGES_DIR / f"{roll_no}.jpg")

    conn = sqlite3.connect(database.DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute("""
    INSERT INTO students (roll_no, name, course, semester, section, email, phone, photo)
    VALUES (?,?,?,?,?,?,?,?)
    """, (roll_no, name, course, semester, section, email, phone, photo_path))

    database.upsert_user(
        cursor,
        username=roll_no,
        password=password,
        role="student",
        linked_id=roll_no,
        is_active=1,
    )

    conn.commit()
    conn.close()

    return redirect('/manage_students')


@app.route('/capture_student_face/<roll_no>')
def capture_student_face(roll_no):
    if session.get('role') != 'admin':
        return redirect('/')

    message = "Use the Capture face button on this page to open the in-browser camera preview."
    return redirect(f"/manage_students?face_status=success&face_message={quote(message)}")


@app.route('/save_face_samples', methods=['POST'])
def save_face_samples():
    if session.get('role') != 'admin':
        return jsonify({"ok": False, "message": "Admin access is required."}), 403

    payload = request.get_json(silent=True) or {}
    roll_no = str(payload.get("roll_no", "")).strip()
    samples = payload.get("samples") or []

    if not roll_no or not samples:
        return jsonify({"ok": False, "message": "Roll number and face samples are required."}), 400

    conn = sqlite3.connect(database.DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM students WHERE roll_no=?", (roll_no,))
    student = cursor.fetchone()

    if not student:
        conn.close()
        return jsonify({"ok": False, "message": "Student not found."}), 404

    sample_dir = FACE_IMAGES_DIR / roll_no
    sample_dir.mkdir(parents=True, exist_ok=True)

    for old_sample in sample_dir.glob("sample_*.jpg"):
        old_sample.unlink()

    saved_count = 0
    first_sample_bytes = None

    for index, sample in enumerate(samples[:30], start=1):
        try:
            _, encoded = sample.split(",", 1)
            image_bytes = base64.b64decode(encoded)
        except (ValueError, TypeError):
            continue

        if not image_bytes:
            continue

        if first_sample_bytes is None:
            first_sample_bytes = image_bytes

        (sample_dir / f"sample_{index:03d}.jpg").write_bytes(image_bytes)
        saved_count += 1

    if saved_count == 0:
        conn.close()
        return jsonify({"ok": False, "message": "No valid face samples were received."}), 400

    if first_sample_bytes:
        preview_path = FACE_IMAGES_DIR / f"{roll_no}.jpg"
        preview_path.write_bytes(first_sample_bytes)
        cursor.execute(
            "UPDATE students SET photo=? WHERE roll_no=?",
            (f"static/student_faces/{roll_no}.jpg", roll_no),
        )
        conn.commit()

    conn.close()

    return jsonify({
        "ok": True,
        "message": f"Saved {saved_count} face sample(s). Train the face model next.",
    })


# =====================================
# DELETE STUDENT
# =====================================

@app.route('/delete_student/<roll_no>')
def delete_student(roll_no):
    if session.get('role') != 'admin':
        return redirect('/')

    conn = sqlite3.connect(database.DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute("DELETE FROM students WHERE roll_no=?", (roll_no,))
    database.delete_user_for_profile(cursor, "student", roll_no)

    conn.commit()
    conn.close()

    return redirect('/manage_students')


# =====================================
# EDIT STUDENT
# =====================================

@app.route('/edit_student/<roll_no>')
def edit_student(roll_no):
    if session.get('role') != 'admin':
        return redirect('/')

    conn = sqlite3.connect(database.DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute("""
    SELECT roll_no, name, course, semester, section, email, phone, photo
    FROM students
    WHERE roll_no=?
    """, (roll_no,))
    student = cursor.fetchone()

    cursor.execute("""
    SELECT username, is_active
    FROM users
    WHERE role='student' AND linked_id=?
    """, (roll_no,))
    student_user = cursor.fetchone()
    conn.close()

    return render_template(
        'edit_student.html',
        student=student,
        student_user=student_user
    )


# =====================================
# UPDATE STUDENT
# =====================================

@app.route('/update_student', methods=['POST'])
def update_student():
    if session.get('role') != 'admin':
        return redirect('/')

    roll_no = request.form['roll_no']
    password = request.form.get('password', '').strip()
    is_active = 1 if request.form.get('is_active') == '1' else 0

    conn = sqlite3.connect(database.DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute("""
    SELECT password
    FROM users
    WHERE role='student' AND linked_id=?
    """, (roll_no,))
    existing_student_user = cursor.fetchone()

    if is_active and not password and (not existing_student_user or not existing_student_user[0]):
        is_active = 0

    cursor.execute("""
    UPDATE students
    SET name=?, course=?, semester=?, section=?, email=?, phone=?
    WHERE roll_no=?
    """, (
        request.form['name'],
        request.form['course'],
        request.form['semester'],
        request.form['section'],
        request.form['email'],
        request.form['phone'],
        roll_no
    ))

    if password:
        database.upsert_user(
            cursor,
            username=roll_no,
            password=password,
            role="student",
            linked_id=roll_no,
            is_active=is_active,
        )
    else:
        cursor.execute("""
        UPDATE users
        SET username=?, is_active=?, updated_at=?
        WHERE role='student' AND linked_id=?
        """, (roll_no, is_active, database.utc_now(), roll_no))

    conn.commit()
    conn.close()

    return redirect('/manage_students')


# =====================================
# MANAGE TEACHERS
# =====================================

@app.route('/manage_teachers')
def manage_teachers():
    if session.get('role') != 'admin':
        return redirect('/')

    conn = sqlite3.connect(database.DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute("""
    SELECT teacher_id, name, subject, department, email, phone, username, password
    FROM teachers
    """)
    teachers = cursor.fetchall()
    conn.close()

    return render_template(
        'manage_teachers.html',
        teachers=teachers
    )


# =====================================
# ADD TEACHER
# =====================================

@app.route('/add_teacher', methods=['POST'])
def add_teacher():
    if session.get('role') != 'admin':
        return redirect('/')

    conn = sqlite3.connect(database.DATABASE_PATH)
    cursor = conn.cursor()
    teacher_id = request.form.get('teacher_id', '').strip() or next_teacher_id(cursor)
    password = request.form['password']

    cursor.execute("""
    INSERT INTO teachers VALUES (?,?,?,?,?,?,?,?)
    """, (
        teacher_id,
        request.form['name'],
        request.form['subject'],
        request.form['department'],
        request.form.get('email', '').strip(),
        request.form.get('phone', '').strip(),
        teacher_id,
        password
    ))

    database.upsert_user(
        cursor,
        username=teacher_id,
        password=password,
        role="teacher",
        linked_id=teacher_id,
        is_active=1,
    )

    conn.commit()
    conn.close()

    return redirect('/manage_teachers')


# =====================================
# EDIT TEACHER
# =====================================

@app.route('/edit_teacher/<teacher_id>')
def edit_teacher(teacher_id):
    if session.get('role') != 'admin':
        return redirect('/')

    conn = sqlite3.connect(database.DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute("""
    SELECT teacher_id, name, subject, department, email, phone, username, password
    FROM teachers
    WHERE teacher_id=?
    """, (teacher_id,))
    teacher = cursor.fetchone()
    conn.close()

    return render_template(
        'edit_teacher.html',
        teacher=teacher
    )


# =====================================
# UPDATE TEACHER
# =====================================

@app.route('/update_teacher', methods=['POST'])
def update_teacher():
    if session.get('role') != 'admin':
        return redirect('/')

    teacher_id = request.form['teacher_id']
    username = teacher_id
    password = request.form['password']

    conn = sqlite3.connect(database.DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute("""
    UPDATE teachers
    SET name=?, subject=?, department=?, email=?, phone=?, username=?, password=?
    WHERE teacher_id=?
    """, (
        request.form['name'],
        request.form['subject'],
        request.form['department'],
        request.form.get('email', '').strip(),
        request.form.get('phone', '').strip(),
        username,
        password,
        teacher_id
    ))

    database.upsert_user(
        cursor,
        username=username,
        password=password,
        role="teacher",
        linked_id=teacher_id,
        is_active=1,
    )

    conn.commit()
    conn.close()

    return redirect('/manage_teachers')


# =====================================
# DELETE TEACHER
# =====================================

@app.route('/delete_teacher/<teacher_id>')
def delete_teacher(teacher_id):
    if session.get('role') != 'admin':
        return redirect('/')

    conn = sqlite3.connect(database.DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute("DELETE FROM teachers WHERE teacher_id=?", (teacher_id,))
    database.delete_user_for_profile(cursor, "teacher", teacher_id)

    conn.commit()
    conn.close()

    return redirect('/manage_teachers')


# =====================================
# TEACHER DASHBOARD
# =====================================

@app.route('/teacher')
def teacher_dashboard():
    if session.get('role') != 'teacher':
        return redirect('/')

    today = str(datetime.date.today())

    conn = sqlite3.connect(database.DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM students")
    total_students = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM attendance WHERE date=? AND status='Present'", (today,))
    present_today = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM attendance WHERE date=? AND status='Absent'", (today,))
    absent_today = cursor.fetchone()[0]

    total_today = present_today + absent_today
    percentage = 0

    if total_today > 0:
        percentage = round((present_today / total_today) * 100, 2)

    cursor.execute("""
    SELECT date,
           SUM(CASE WHEN status='Present' THEN 1 ELSE 0 END) AS present_count,
           SUM(CASE WHEN status='Absent' THEN 1 ELSE 0 END) AS absent_count
    FROM attendance
    GROUP BY date
    ORDER BY date DESC
    LIMIT 7
    """)
    daily_activity = list(reversed(cursor.fetchall()))

    cursor.execute("""
    SELECT COALESCE(subject, 'Unassigned') AS subject, COUNT(*) AS total
    FROM attendance
    GROUP BY COALESCE(subject, 'Unassigned')
    ORDER BY total DESC, subject ASC
    LIMIT 6
    """)
    subject_load = cursor.fetchall()

    max_daily_total = max([(row[1] or 0) + (row[2] or 0) for row in daily_activity], default=0)
    max_subject_load = max([row[1] for row in subject_load], default=0)

    cursor.execute("SELECT id, title, message, created_at FROM notices ORDER BY id DESC LIMIT 5")
    notices = cursor.fetchall()
    conn.close()

    return render_template(
        'teacher_dashboard.html',
        total_students=total_students,
        present_today=present_today,
        absent_today=absent_today,
        percentage=percentage,
        total_today=total_today,
        daily_activity=daily_activity,
        subject_load=subject_load,
        max_daily_total=max_daily_total,
        max_subject_load=max_subject_load,
        notices=notices,
        face_status=request.args.get('face_status'),
        face_message=request.args.get('face_message'),
    )


# =====================================
# MARK ATTENDANCE
# =====================================

@app.route('/mark_attendance')
def mark_attendance():
    if session.get('role') != 'teacher':
        return redirect('/')

    conn = sqlite3.connect(database.DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute("""
    SELECT roll_no, name, course, semester, section, email, phone, photo
    FROM students
    """)
    students = cursor.fetchall()
    conn.close()

    return render_template(
        'mark_attendance.html',
        students=students
    )


# =====================================
# SAVE ATTENDANCE
# =====================================

@app.route('/save_attendance', methods=['POST'])
def save_attendance():
    if session.get('role') != 'teacher':
        return redirect('/')

    today = str(datetime.date.today())
    subject = request.form['subject']

    conn = sqlite3.connect(database.DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute("""
    SELECT roll_no, name, course, semester, section, email, phone, photo
    FROM students
    """)
    students = cursor.fetchall()

    for student in students:
        roll_no = student[0]
        student_name = student[1]
        status = request.form.get(f"attendance_{roll_no}") or request.form.get(roll_no)

        cursor.execute("""
        INSERT INTO attendance (roll_no, student_name, subject, date, status)
        VALUES (?,?,?,?,?)
        """, (roll_no, student_name, subject, today, status))

    conn.commit()
    conn.close()

    return redirect('/teacher')


@app.route('/prepare_face_marking', methods=['POST'])
def prepare_face_marking():
    if session.get('role') != 'teacher':
        return jsonify({"ok": False, "message": "Teacher access is required."}), 403

    from src.attendance_system import train_model

    result = train_model.train_model()
    if result != 0:
        return jsonify({
            "ok": False,
            "message": "Face model training failed. Capture clear student face samples first.",
        }), 400

    return jsonify({
        "ok": True,
        "message": "Face model trained. Camera marking is ready.",
    })


@app.route('/recognize_face_frame', methods=['POST'])
def recognize_face_frame():
    if session.get('role') != 'teacher':
        return jsonify({"ok": False, "message": "Teacher access is required."}), 403

    if not TRAINER_PATH.exists() or not LABEL_MAP_PATH.exists():
        return jsonify({
            "ok": False,
            "message": "Train the face model before starting camera marking.",
        }), 400

    payload = request.get_json(silent=True) or {}
    subject = str(payload.get("subject", "")).strip()
    frame = payload.get("frame", "")

    if not subject:
        return jsonify({"ok": False, "message": "Select a subject first."}), 400

    try:
        import cv2
        import json
        import numpy as np

        _, encoded = frame.split(",", 1)
        frame_bytes = base64.b64decode(encoded)
        image_array = np.frombuffer(frame_bytes, dtype=np.uint8)
        image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
    except Exception:
        return jsonify({"ok": False, "message": "Camera frame could not be read."}), 400

    if image is None:
        return jsonify({"ok": False, "message": "Camera frame could not be decoded."}), 400

    recognizer = cv2.face.LBPHFaceRecognizer_create()
    recognizer.read(str(TRAINER_PATH))
    label_map = json.loads(LABEL_MAP_PATH.read_text(encoding="utf-8"))
    face_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    faces = face_cascade.detectMultiScale(
        gray,
        scaleFactor=1.2,
        minNeighbors=5,
    )

    if len(faces) == 0:
        return jsonify({"ok": True, "status": "waiting", "message": "No face in view."})

    x, y, w, h = max(faces, key=lambda face: face[2] * face[3])
    label, confidence = recognizer.predict(gray[y:y + h, x:x + w])
    roll_no = label_map.get(str(label))

    if not roll_no or confidence >= 70:
        return jsonify({
            "ok": True,
            "status": "unknown",
            "message": "Face not recognized. Move closer or capture better samples.",
            "confidence": round(float(confidence), 2),
        })

    today = str(datetime.date.today())
    conn = sqlite3.connect(database.DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM students WHERE roll_no=?", (roll_no,))
    student = cursor.fetchone()

    if not student:
        conn.close()
        return jsonify({"ok": True, "status": "unknown", "message": "Recognized face is not linked to a student."})

    student_name = student[0]
    result = upsert_attendance_record(
        cursor,
        roll_no=roll_no,
        student_name=student_name,
        subject=subject,
        date=today,
        status="Present",
    )
    conn.commit()
    conn.close()

    if result == "existing":
        message = f"{student_name} ({roll_no}) already marked for {subject}."
    elif result == "updated":
        message = f"{student_name} ({roll_no}) was already listed and is now marked present."
    else:
        message = f"{student_name} ({roll_no}) marked present."

    return jsonify({
        "ok": True,
        "status": result,
        "roll_no": roll_no,
        "student_name": student_name,
        "message": message,
        "confidence": round(float(confidence), 2),
    })


# =====================================
# VIEW ATTENDANCE
# =====================================

@app.route('/view_attendance')
def view_attendance():
    if session.get('role') not in ['teacher', 'admin']:
        return redirect('/')

    search = request.args.get('search')
    selected_date = request.args.get('date')
    selected_subject = request.args.get('subject')
    page = request.args.get('page', 1, type=int)

    per_page = 10
    offset = (page - 1) * per_page
    
    conn = sqlite3.connect(database.DATABASE_PATH)
    cursor = conn.cursor()

    query = """
    SELECT id, roll_no, student_name, subject, date, status
    FROM attendance
    WHERE 1=1
    """
    params = []

    if search:
        query += " AND (roll_no LIKE ? OR student_name LIKE ?)"
        params.extend([f'%{search}%', f'%{search}%'])

    if selected_date:
        query += " AND date=?"
        params.append(selected_date)

    if selected_subject:
        query += " AND subject=?"
        params.append(selected_subject)
        
    query += """
    ORDER BY date DESC
    LIMIT ?
    OFFSET ?
    """
    params.extend([per_page, offset])

    cursor.execute(query, params)
    records = cursor.fetchall()
    conn.close()

    return render_template(
        'view_attendance.html',
        records=records
    )


# =====================================
# EXPORT ATTENDANCE
# =====================================

@app.route('/export_attendance')
def export_attendance():
    conn = sqlite3.connect(database.DATABASE_PATH)
    query = """
    SELECT id, roll_no, student_name, subject, date, status
    FROM attendance
    """

    df = pd.read_sql_query(query, conn)
    conn.close()

    file_name = EXPORT_DIR / "attendance_report.xlsx"
    df.to_excel(file_name, index=False)

    return send_file(
        file_name,
        as_attachment=True
    )


# =====================================
# STUDENT DASHBOARD
# =====================================

@app.route('/student')
def student_dashboard():
    if session.get('role') != 'student':
        return redirect('/')

    roll_no = current_profile_id()

    conn = sqlite3.connect(database.DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute("""
    SELECT roll_no, name, course, semester, section, email, phone, photo
    FROM students
    WHERE roll_no=?
    """, (roll_no,))
    student = cursor.fetchone()

    cursor.execute("""
    SELECT id, roll_no, student_name, subject, date, status
    FROM attendance
    WHERE roll_no=?
    ORDER BY date DESC
    """, (roll_no,))
    records = cursor.fetchall()

    total_classes = len(records)
    present_count = sum(1 for record in records if record[5] == "Present")
    absent_count = total_classes - present_count
    percentage = round((present_count / total_classes) * 100, 2) if total_classes else 0

    cursor.execute("""
    SELECT COALESCE(subject, 'Unassigned') AS subject,
           COUNT(*) AS total,
           SUM(CASE WHEN status='Present' THEN 1 ELSE 0 END) AS present_count,
           SUM(CASE WHEN status='Absent' THEN 1 ELSE 0 END) AS absent_count
    FROM attendance
    WHERE roll_no=?
    GROUP BY COALESCE(subject, 'Unassigned')
    ORDER BY total DESC, subject ASC
    """, (roll_no,))
    subject_summary = cursor.fetchall()

    cursor.execute("""
    SELECT date,
           SUM(CASE WHEN status='Present' THEN 1 ELSE 0 END) AS present_count,
           COUNT(*) AS total
    FROM attendance
    WHERE roll_no=?
    GROUP BY date
    ORDER BY date DESC
    LIMIT 7
    """, (roll_no,))
    attendance_trend = list(reversed(cursor.fetchall()))

    max_subject_total = max([row[1] for row in subject_summary], default=0)

    cursor.execute("SELECT id, title, message, created_at FROM notices ORDER BY id DESC LIMIT 5")
    notices = cursor.fetchall()
    conn.close()

    return render_template(
        'student_dashboard.html',
        student=student,
        total_classes=total_classes,
        present_count=present_count,
        absent_count=absent_count,
        percentage=percentage,
        subject_summary=subject_summary,
        attendance_trend=attendance_trend,
        max_subject_total=max_subject_total,
        notices=notices,
        records=records
    )


# =====================================
# STUDENT PROFILE
# =====================================

@app.route('/student_profile')
def student_profile():
    if session.get('role') != 'student':
        return redirect('/')

    roll_no = current_profile_id()

    conn = sqlite3.connect(database.DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute("""
    SELECT roll_no, name, course, semester, section, email, phone, photo
    FROM students
    WHERE roll_no=?
    """, (roll_no,))
    student = cursor.fetchone()
    conn.close()

    return render_template(
        'student_profile.html',
        student=student
    )


@app.route('/edit_student_profile')
def edit_student_profile():
    if session.get('role') != 'student':
        return redirect('/')

    roll_no = current_profile_id()

    conn = sqlite3.connect(database.DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute("""
    SELECT roll_no, name, course, semester, section, email, phone, photo
    FROM students
    WHERE roll_no=?
    """, (roll_no,))
    student = cursor.fetchone()
    conn.close()

    return render_template(
        'edit_student_profile.html',
        student=student
    )


@app.route('/update_student_profile', methods=['POST'])
def update_student_profile():
    if session.get('role') != 'student':
        return redirect('/')

    roll_no = current_profile_id()
    email = request.form['email']
    phone = request.form['phone']
    photo = request.files.get('photo')

    conn = sqlite3.connect(database.DATABASE_PATH)
    cursor = conn.cursor()

    if photo and photo.filename:
        photo_path = f"static/student_faces/{roll_no}.jpg"
        photo.save(FACE_IMAGES_DIR / f"{roll_no}.jpg")

        cursor.execute("""
        UPDATE students
        SET email=?, phone=?, photo=?
        WHERE roll_no=?
        """, (email, phone, photo_path, roll_no))
    else:
        cursor.execute("""
        UPDATE students
        SET email=?, phone=?
        WHERE roll_no=?
        """, (email, phone, roll_no))

    conn.commit()
    conn.close()

    return redirect('/student_profile')


@app.route('/student_attendance')
def student_attendance():
    if session.get('role') != 'student':
        return redirect('/')

    roll_no = current_profile_id()
    selected_date = request.args.get('date')

    conn = sqlite3.connect(database.DATABASE_PATH)
    cursor = conn.cursor()

    query = "SELECT roll_no, subject, date, status FROM attendance WHERE roll_no=?"
    params = [roll_no]

    if selected_date:
        query += " AND date=?"
        params.append(selected_date)

    query += " ORDER BY date DESC"

    cursor.execute(query, params)
    records = cursor.fetchall()
    conn.close()

    return render_template(
        'student_attendance.html',
        records=records
    )


@app.route('/student_export_attendance')
def student_export_attendance():
    if session.get('role') != 'student':
        return redirect('/')

    roll_no = current_profile_id()

    conn = sqlite3.connect(database.DATABASE_PATH)
    query = "SELECT roll_no, subject, date, status FROM attendance WHERE roll_no=?"

    df = pd.read_sql_query(query, conn, params=(roll_no,))
    conn.close()

    file_name = EXPORT_DIR / f"{roll_no}_attendance.xlsx"
    df.to_excel(file_name, index=False)

    return send_file(
        file_name,
        as_attachment=True
    )


# =====================================
# START FACE ATTENDANCE
# =====================================


@app.route('/train_face_model')
def train_face_model():
    if session.get('role') != 'teacher':
        return redirect('/')

    result = subprocess.run(
        [sys.executable, "-m", "src.attendance_system.train_model"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        message = "Face model trained successfully. You can start face attendance now."
        return redirect(f"/teacher?face_status=success&face_message={quote(message)}")

    message = "Face training failed. Add clear student face photos, then train again."
    return redirect(f"/teacher?face_status=error&face_message={quote(message)}")


@app.route('/start_face_attendance')
def start_face_attendance():
    if session.get('role') != 'teacher':
        return redirect('/')

    if not TRAINER_PATH.exists() or not LABEL_MAP_PATH.exists():
        message = "Train the face model before starting camera attendance."
        return redirect(f"/teacher?face_status=error&face_message={quote(message)}")

    try:
        subprocess.Popen(
            [sys.executable, "-m", "src.attendance_system.face_attendance"],
            cwd=str(PROJECT_ROOT),
        )
    except OSError:
        message = "Camera attendance could not be started from this environment."
        return redirect(f"/teacher?face_status=error&face_message={quote(message)}")

    message = "Face attendance started. Press q in the camera window to stop."
    return redirect(f"/teacher?face_status=success&face_message={quote(message)}")


# =====================================
# MANAGE NOTICES
# =====================================

@app.route('/manage_notices')
def manage_notices():
    if session.get('role') != 'admin':
        return redirect('/')

    conn = sqlite3.connect(database.DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT id, title, message, created_at FROM notices ORDER BY id DESC")
    notices = cursor.fetchall()
    conn.close()

    return render_template(
        'manage_notices.html',
        notices=notices
    )


# =====================================
# ADD NOTICE
# =====================================

@app.route('/add_notice', methods=['POST'])
def add_notice():
    if session.get('role') != 'admin':
        return redirect('/')

    title = request.form['title']
    message = request.form['message']
    created_at = str(datetime.datetime.now())

    conn = sqlite3.connect(database.DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute("""
    INSERT INTO notices (title, message, created_at)
    VALUES (?,?,?)
    """, (title, message, created_at))

    conn.commit()
    conn.close()

    return redirect('/manage_notices')


# =====================================
# DELETE NOTICE
# =====================================

@app.route('/delete_notice/<int:id>')
def delete_notice(id):
    if session.get('role') != 'admin':
        return redirect('/')

    conn = sqlite3.connect(database.DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute("DELETE FROM notices WHERE id=?", (id,))
    conn.commit()
    conn.close()

    return redirect('/manage_notices')


# =====================================
# EDIT ATTENDANCE
# =====================================

@app.route('/edit_attendance/<int:attendance_id>')
def edit_attendance(attendance_id):
    if session.get('role') != 'teacher':
        return redirect('/')

    conn = sqlite3.connect(database.DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute("""
    SELECT id, roll_no, student_name, subject, date, status
    FROM attendance
    WHERE id=?
    """, (attendance_id,))

    attendance = cursor.fetchone()
    conn.close()

    return render_template(
        'edit_attendance.html',
        attendance=attendance
    )


# =====================================
# UPDATE ATTENDANCE
# =====================================

@app.route('/update_attendance', methods=['POST'])
def update_attendance():
    if session.get('role') != 'teacher':
        return redirect('/')

    attendance_id = request.form['attendance_id']
    status = request.form['status']

    conn = sqlite3.connect(database.DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute("""
    UPDATE attendance
    SET status=?
    WHERE id=?
    """, (status, attendance_id))

    conn.commit()
    conn.close()

    return redirect('/view_attendance')


# =====================================
# DELETE ATTENDANCE
# =====================================

@app.route('/delete_attendance/<int:attendance_id>')
def delete_attendance(attendance_id):
    if session.get('role') != 'teacher':
        return redirect('/')

    conn = sqlite3.connect(database.DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute("""
    DELETE FROM attendance
    WHERE id=?
    """, (attendance_id,))

    conn.commit()
    conn.close()

    return redirect('/view_attendance')


# =====================================
# MONTHLY ATTENDANCE REPORT
# =====================================

@app.route('/monthly_report')
def monthly_report():
    if session.get('role') not in ['teacher', 'admin']:
        return redirect('/')

    selected_month = request.args.get('month')

    conn = sqlite3.connect(database.DATABASE_PATH)
    query = """
    SELECT id, roll_no, student_name, subject, date, status
    FROM attendance
    """

    if selected_month:
        query += " WHERE strftime('%m', date)=?"
        month_number = selected_month.split('-')[1]
        df = pd.read_sql_query(query, conn, params=(month_number,))
    else:
        df = pd.read_sql_query(query, conn)

    conn.close()
    records = df.values.tolist()

    return render_template(
        'monthly_report.html',
        records=records
    )


# =====================================
# DOWNLOAD PDF REPORT
# =====================================

@app.route('/download_pdf_report')
def download_pdf_report():
    if session.get('role') not in ['teacher', 'admin']:
        return redirect('/')

    conn = sqlite3.connect(database.DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute("""
    SELECT roll_no, student_name, subject, date, status
    FROM attendance
    ORDER BY date DESC
    """)

    records = cursor.fetchall()
    conn.close()

    file_name = EXPORT_DIR / "attendance_report.pdf"
    doc = SimpleDocTemplate(str(file_name))
    elements = []

    style_sheet = styles.getSampleStyleSheet()
    title = Paragraph("Student Attendance Report", style_sheet['Title'])
    elements.append(title)
    elements.append(Spacer(1, 15))

    table_data = [["Roll No", "Student Name", "Subject", "Date", "Status"]]

    for row in records:
        table_data.append([row[0], row[1], row[2], row[3], row[4]])

    table = Table(table_data)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.blue),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold')
    ]))

    elements.append(table)
    doc.build(elements)

    return send_file(
        file_name,
        as_attachment=True
    )


# =====================================
# LOW ATTENDANCE WARNING
# =====================================

@app.route('/low_attendance')
def low_attendance():
    if session.get('role') not in ['teacher', 'admin']:
        return redirect('/')

    conn = sqlite3.connect(database.DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT roll_no, student_name, status FROM attendance")
    records = cursor.fetchall()
    conn.close()

    student_data = {}
    for row in records:
        roll_no = row[0]
        student_name = row[1]
        status = row[2]

        if roll_no not in student_data:
            student_data[roll_no] = {
                'name': student_name,
                'total': 0,
                'present': 0
            }

        student_data[roll_no]['total'] += 1
        if status == "Present":
            student_data[roll_no]['present'] += 1

    low_students = []
    for roll_no, data in student_data.items():
        percentage = round((data['present'] / data['total']) * 100, 2)
        if percentage < 75:
            low_students.append([roll_no, data['name'], percentage])

    return render_template(
        'low_attendance.html',
        students=low_students
    )


# =====================================
# FORGOT PASSWORD
# =====================================

@app.route('/forgot_password')
def forgot_password():
    return render_template(
        'forgot_password.html',
        password=None,
        error=None
    )


@app.route('/recover_password', methods=['POST'])
def recover_password():
    username = request.form['username']
    role = request.form['role']

    conn = sqlite3.connect(database.DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute("""
    SELECT password
    FROM users
    WHERE username=? AND role=? AND is_active=1
    """, (username, role))

    user = cursor.fetchone()
    conn.close()

    if user:
        return render_template(
            'forgot_password.html',
            password=user[0],
            error=None
        )

    return render_template(
        'forgot_password.html',
        password=None,
        error="User not found!"
    )


# =====================================
# ATTENDANCE ANALYTICS
# =====================================

@app.route('/attendance_analytics')
def attendance_analytics():
    if session.get('role') not in ['teacher', 'admin']:
        return redirect('/')

    conn = sqlite3.connect(database.DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute("""
    SELECT student_name, COUNT(*) as total_present
    FROM attendance
    WHERE status='Present'
    GROUP BY student_name
    ORDER BY total_present DESC
    LIMIT 5
    """)
    top_present = cursor.fetchall()

    cursor.execute("""
    SELECT student_name, COUNT(*) as total_absent
    FROM attendance
    WHERE status='Absent'
    GROUP BY student_name
    ORDER BY total_absent DESC
    LIMIT 5
    """)
    top_absent = cursor.fetchall()

    conn.close()

    return render_template(
        'attendance_analytics.html',
        top_present=top_present,
        top_absent=top_absent
    )


# =====================================
# LOGOUT
# =====================================

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')


# =====================================
# RUN APP
# =====================================

if __name__ == '__main__':
    app.run(debug=True)


