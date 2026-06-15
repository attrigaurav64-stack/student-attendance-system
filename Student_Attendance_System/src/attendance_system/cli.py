import sqlite3
import pandas as pd
from datetime import datetime
from . import database


database.connect_db(verbose=False)
def login():
    role = input(
        "Enter Role (admin/teacher/student): "
    )

    username = input(
        "Enter Username: "
    )

    password = input(
        "Enter Password: "
    )

    conn = sqlite3.connect(database.DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute("""
    SELECT id
    FROM users
    WHERE username=?
      AND password=?
      AND role=?
      AND is_active=1
    """, (username, password, role))

    user = cursor.fetchone()
    conn.close()

    if user:
        print(
            "\nLogin Successful!"
        )
        return True

    print(
        "Wrong Username or Password"
    )
    return False

def add_student():
    roll_no = input("Enter Roll Number: ")
    name = input("Enter Student Name: ")
    course = input("Enter Course: ")
    semester = input("Enter Semester: ")

    conn = sqlite3.connect(database.DATABASE_PATH)
    cursor = conn.cursor()

    try:
        cursor.execute(
            "INSERT INTO students (roll_no, name, course, semester) VALUES (?, ?, ?, ?)",
            (roll_no, name, course, semester)
        )
        conn.commit()
        print("Student Added Successfully!")
    except sqlite3.IntegrityError:
        print("Roll Number Already Exists!")

    conn.close()


def mark_attendance():
    roll_no = input("Enter Roll Number: ")

    conn = sqlite3.connect(database.DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT roll_no, name, course, semester, section, email, phone, photo
        FROM students
        WHERE roll_no=?
        """,
        (roll_no,)
    )

    student = cursor.fetchone()

    if student:
        subject = input("Enter Subject: ")
        status_value = input("Present/Absent (P/A): ").upper()
        status = "Present" if status_value == "P" else "Absent"
        date = datetime.now().strftime("%Y-%m-%d")

        cursor.execute(
            """
            INSERT INTO attendance
            (roll_no, student_name, subject, date, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            (roll_no, student[1], subject, date, status)
        )

        conn.commit()
        print("Attendance Marked!")
    else:
        print("Student Not Found!")

    conn.close()


def view_report():
    conn = sqlite3.connect(database.DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT students.roll_no,
               students.name,
               attendance.date,
               attendance.status
        FROM attendance
        JOIN students
        ON students.roll_no = attendance.roll_no
        """
    )

    records = cursor.fetchall()

    print("\n===== ATTENDANCE REPORT =====")

    student_data = {}

    for row in records:
        roll_no = row[0]
        name = row[1]
        status = row[3]

        if roll_no not in student_data:
            student_data[roll_no] = {
                "name": name,
                "total": 0,
                "present": 0
            }

        student_data[roll_no]["total"] += 1

        if status == "P":
            student_data[roll_no]["present"] += 1

    for roll_no, data in student_data.items():
        percentage = (data["present"] / data["total"]) * 100

        print(f"\nRoll No: {roll_no}")
        print(f"Name: {data['name']}")
        print(f"Attendance: {percentage:.2f}%")

    print("\nAttendance Report")
    print("-" * 50)

    for row in records:
        print(
            f"Roll No: {row[0]} | "
            f"Name: {row[1]} | "
            f"Date: {row[2]} | "
            f"Status: {row[3]}"
        )

    conn.close()


def search_student():
    roll_no = input("Enter Roll Number: ")

    conn = sqlite3.connect(database.DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT roll_no, name, course, semester, section, email, phone, photo
        FROM students
        WHERE roll_no=?
        """,
        (roll_no,)
    )

    student = cursor.fetchone()

    if student:
        print("\nStudent Found")
        print("Roll No:", student[0])
        print("Name:", student[1])
    else:
        print("Student Not Found!")

    conn.close()


def export_excel():
    conn = sqlite3.connect(database.DATABASE_PATH)

    query = """
    SELECT students.roll_no,
           students.name,
           attendance.date,
           attendance.status
    FROM attendance
    JOIN students
    ON students.roll_no = attendance.roll_no
    """

    df = pd.read_sql_query(query, conn)
    df.to_excel(database.PROJECT_ROOT / "exports" / "attendance_report.xlsx", index=False)

    conn.close()

    print("Excel File Created!")


def attendance_percentage():
    roll_no = input("Enter Roll Number: ")

    conn = sqlite3.connect(database.DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT COUNT(*) FROM attendance
        WHERE roll_no=?
        """,
        (roll_no,)
    )

    total = cursor.fetchone()[0]

    cursor.execute(
        """
        SELECT COUNT(*) FROM attendance
        WHERE roll_no=? AND status='P'
        """,
        (roll_no,)
    )

    present = cursor.fetchone()[0]

    if total > 0:
        percentage = (present / total) * 100
        print(f"Attendance Percentage: {percentage:.2f}%")
    else:
        print("No attendance record found!")

    conn.close()


def run_cli():
    if not login():
        return

    while True:
        print("\n===== STUDENT ATTENDANCE SYSTEM =====")
        print("1. Add Student")
        print("2. Mark Attendance")
        print("3. View Attendance Report")
        print("4. Search Student")
        print("5. Attendance Percentage")
        print("6. Export to Excel")
        print("7. Exit")

        choice = input("Enter Choice: ")

        if choice == "1":
            add_student()
        elif choice == "2":
            mark_attendance()
        elif choice == "3":
            view_report()
        elif choice == "4":
            search_student()
        elif choice == "5":
            attendance_percentage()
        elif choice == "6":
            export_excel()
        elif choice == "7":
            print("Exiting...")
            break
        else:
            print("Invalid Choice!")


if __name__ == "__main__":
    run_cli()

