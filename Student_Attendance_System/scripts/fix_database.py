import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.attendance_system import database

conn = sqlite3.connect(database.DATABASE_PATH)
cursor = conn.cursor()

try:
    cursor.execute("""
    ALTER TABLE attendance
    ADD COLUMN subject TEXT
    """)
    print("Subject column added successfully!")

except Exception as e:
    print("Already exists or error:", e)

conn.commit()
conn.close()
