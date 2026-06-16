import sqlite3
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
DATABASE_PATH = DATA_DIR / "attendance.db"
VALID_ROLES = {"admin", "teacher", "student"}


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_connection(database_path=DATABASE_PATH):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(database_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def table_columns(cursor, table_name):
    return {row[1] for row in cursor.execute(f"PRAGMA table_info({table_name})")}


def add_column(cursor, table_name, column_name, column_definition):
    if column_name not in table_columns(cursor, table_name):
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_definition}")


def connect_db(database_path=DATABASE_PATH, verbose=True):
    conn = get_connection(database_path)
    cursor = conn.cursor()

    create_tables(cursor)
    migrate_existing_tables(cursor)
    normalize_attendance_table(cursor)
    sync_identity_data(cursor)

    conn.commit()
    conn.close()

    if verbose:
        print("Database schema synchronized successfully.")


def create_tables(cursor):
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT,
        role TEXT,
        linked_id TEXT,
        is_active INTEGER DEFAULT 1,
        created_at TEXT,
        updated_at TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS admins (
        admin_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        email TEXT,
        phone TEXT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        created_at TEXT,
        updated_at TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS students (
        roll_no TEXT PRIMARY KEY,
        name TEXT,
        course TEXT,
        semester TEXT,
        section TEXT,
        email TEXT,
        phone TEXT,
        photo TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS teachers (
        teacher_id TEXT PRIMARY KEY,
        name TEXT,
        subject TEXT,
        department TEXT,
        email TEXT,
        phone TEXT,
        username TEXT UNIQUE,
        password TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        roll_no TEXT,
        student_name TEXT,
        subject TEXT,
        date TEXT,
        status TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS notices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        message TEXT,
        created_at TEXT
    )
    """)


def migrate_existing_tables(cursor):
    add_column(cursor, "users", "linked_id", "linked_id TEXT")
    add_column(cursor, "users", "is_active", "is_active INTEGER DEFAULT 1")
    add_column(cursor, "users", "created_at", "created_at TEXT")
    add_column(cursor, "users", "updated_at", "updated_at TEXT")

    cursor.execute("""
    UPDATE users
    SET created_at=COALESCE(created_at, ?),
        updated_at=COALESCE(updated_at, ?),
        is_active=COALESCE(is_active, 1)
    """, (utc_now(), utc_now()))

    cursor.execute("""
    UPDATE students
    SET photo='static/' || photo
    WHERE photo IS NOT NULL
      AND photo != ''
      AND photo NOT LIKE 'static/%'
    """)


def normalize_attendance_table(cursor):
    expected_order = ["id", "roll_no", "student_name", "subject", "date", "status"]
    current_order = [
        row[1]
        for row in cursor.execute("PRAGMA table_info(attendance)").fetchall()
    ]

    if current_order == expected_order:
        return

    current_columns = set(current_order)
    required_columns = set(expected_order)
    if not required_columns.issubset(current_columns):
        return

    cursor.execute("""
    CREATE TABLE attendance_normalized (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        roll_no TEXT,
        student_name TEXT,
        subject TEXT,
        date TEXT,
        status TEXT
    )
    """)

    cursor.execute("""
    INSERT INTO attendance_normalized (
        id, roll_no, student_name, subject, date, status
    )
    SELECT id, roll_no, student_name, subject, date, status
    FROM attendance
    """)

    cursor.execute("DROP TABLE attendance")
    cursor.execute("ALTER TABLE attendance_normalized RENAME TO attendance")


def sync_identity_data(cursor):
    remove_legacy_default_users(cursor)
    sync_admin_profiles(cursor)
    sync_teacher_users(cursor)
    sync_student_users(cursor)
    deactivate_orphan_users(cursor)
    
    # Auto-create a default admin if none exist (needed for fresh deployments)
    count = cursor.execute("SELECT COUNT(*) FROM admins").fetchone()[0]
    if count == 0:
        cursor.execute("""
        INSERT INTO admins (admin_id, name, email, phone, username, password, created_at, updated_at)
        VALUES ('ADM-0001', 'Administrator', '', '', 'admin', 'admin123', ?, ?)
        """, (utc_now(), utc_now()))
        
        upsert_user(
            cursor,
            username="admin",
            password="admin123",
            role="admin",
            linked_id="ADM-0001",
            is_active=1
        )


def remove_legacy_default_users(cursor):
    legacy_default_users = [
        ("admin", "1234", "admin"),
        ("teacher", "1234", "teacher"),
        ("student", "1234", "student"),
    ]

    for username, password, role in legacy_default_users:
        cursor.execute("""
        DELETE FROM users
        WHERE username=? AND password=? AND role=?
        """, (username, password, role))


def sync_admin_profiles(cursor):
    existing_admins = cursor.execute("""
    SELECT id, username, password, linked_id
    FROM users
    WHERE role='admin'
    """).fetchall()

    for user_id, username, password, linked_id in existing_admins:
        admin_id = linked_id or f"ADM-{user_id:04d}"
        cursor.execute("""
        INSERT OR IGNORE INTO admins (
            admin_id, name, email, phone, username, password, created_at, updated_at
        )
        VALUES (?, ?, '', '', ?, ?, ?, ?)
        """, (
            admin_id,
            f"Administrator {admin_id}",
            username,
            password,
            utc_now(),
            utc_now(),
        ))

        cursor.execute("""
        UPDATE admins
        SET username=?, password=?, updated_at=?
        WHERE admin_id=?
        """, (username, password, utc_now(), admin_id))

        cursor.execute("""
        UPDATE users
        SET linked_id=?, is_active=1, updated_at=?
        WHERE id=?
        """, (admin_id, utc_now(), user_id))


def sync_teacher_users(cursor):
    teachers = cursor.execute("""
    SELECT teacher_id, password
    FROM teachers
    """).fetchall()

    for teacher_id, password in teachers:
        cursor.execute("""
        UPDATE teachers
        SET username=?
        WHERE teacher_id=?
        """, (teacher_id, teacher_id))

        upsert_user(
            cursor,
            username=teacher_id,
            password=password or "",
            role="teacher",
            linked_id=teacher_id,
            is_active=1,
        )


def sync_student_users(cursor):
    students = cursor.execute("SELECT roll_no FROM students").fetchall()

    for (roll_no,) in students:
        existing = cursor.execute("""
        SELECT id
        FROM users
        WHERE role='student' AND linked_id=?
        """, (roll_no,)).fetchone()

        if not existing:
            username_match = cursor.execute("""
            SELECT id
            FROM users
            WHERE role='student' AND username=?
            """, (roll_no,)).fetchone()

            if username_match:
                cursor.execute("""
                UPDATE users
                SET linked_id=?, updated_at=?
                WHERE id=?
                """, (roll_no, utc_now(), username_match[0]))
            else:
                cursor.execute("""
                INSERT INTO users (
                    username, password, role, linked_id, is_active, created_at, updated_at
                )
                VALUES (?, '', 'student', ?, 0, ?, ?)
                """, (roll_no, roll_no, utc_now(), utc_now()))


def deactivate_orphan_users(cursor):
    cursor.execute("""
    DELETE FROM users
    WHERE linked_id IS NULL
    """)

    cursor.execute("""
    UPDATE users
    SET is_active=0, updated_at=?
    WHERE role='teacher'
      AND linked_id NOT IN (SELECT teacher_id FROM teachers)
    """, (utc_now(),))

    cursor.execute("""
    UPDATE users
    SET is_active=0, updated_at=?
    WHERE role='student'
      AND linked_id NOT IN (SELECT roll_no FROM students)
    """, (utc_now(),))

    cursor.execute("""
    UPDATE users
    SET is_active=0, updated_at=?
    WHERE role='admin'
      AND linked_id NOT IN (SELECT admin_id FROM admins)
    """, (utc_now(),))


def upsert_user(cursor, username, password, role, linked_id, is_active=1):
    if role not in VALID_ROLES:
        raise ValueError(f"Invalid role: {role}")

    existing = cursor.execute("""
    SELECT id
    FROM users
    WHERE role=? AND linked_id=?
    """, (role, linked_id)).fetchone()

    if not existing:
        existing = cursor.execute("""
        SELECT id
        FROM users
        WHERE role=? AND username=?
        """, (role, username)).fetchone()

    if existing:
        cursor.execute("""
        UPDATE users
        SET username=?, password=?, linked_id=?, is_active=?, updated_at=?
        WHERE id=?
        """, (username, password, linked_id, is_active, utc_now(), existing[0]))
    else:
        cursor.execute("""
        INSERT INTO users (
            username, password, role, linked_id, is_active, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (username, password, role, linked_id, is_active, utc_now(), utc_now()))


def delete_user_for_profile(cursor, role, linked_id):
    cursor.execute("""
    DELETE FROM users
    WHERE role=? AND linked_id=?
    """, (role, linked_id))


def create_admin(admin_id, name, email, phone, username, password, database_path=DATABASE_PATH):
    conn = get_connection(database_path)
    cursor = conn.cursor()
    create_tables(cursor)
    migrate_existing_tables(cursor)

    existing = cursor.execute(
        "SELECT admin_id FROM admins WHERE admin_id=?",
        (admin_id,)
    ).fetchone()

    if existing:
        cursor.execute("""
        UPDATE admins
        SET name=?, email=?, phone=?, username=?, password=?, updated_at=?
        WHERE admin_id=?
        """, (name, email, phone, username, password, utc_now(), admin_id))
    else:
        cursor.execute("""
        INSERT INTO admins (
            admin_id, name, email, phone, username, password, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (admin_id, name, email, phone, username, password, utc_now(), utc_now()))

    upsert_user(
        cursor,
        username=username,
        password=password,
        role="admin",
        linked_id=admin_id,
        is_active=1,
    )

    conn.commit()
    conn.close()


if __name__ == "__main__":
    connect_db()
