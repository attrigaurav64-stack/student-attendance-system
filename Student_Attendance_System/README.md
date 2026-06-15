# Student Attendance System

A Flask-based AI smart attendance management portal for an institute. The application supports admin, teacher, and student roles, stores records in SQLite, lets teachers mark attendance manually or through OpenCV face recognition, provides student attendance views, exports reports, and includes dashboards, analytics, notices, and low-attendance monitoring.

## Project Intent

The project is meant to centralize student attendance operations:

- Admins manage students, teachers, notices, and attendance reports.
- Teachers mark attendance, train the face model, start camera-based face attendance, review attendance records, and view analytics.
- Students view their attendance, profile details, notices, and downloadable attendance reports.

## Folder Structure

```text
.
├── app.py                         # Root entry point for the Flask web app
├── requirements.txt               # Python dependencies
├── README.md                      # Project documentation
├── changes.md                     # Chronological agent changelog
├── src/
│   └── attendance_system/
│       ├── app.py                 # Main Flask routes and application setup
│       ├── database.py            # SQLite schema/default user initialization
│       ├── cli.py                 # Legacy console attendance interface
│       ├── face_attendance.py     # Camera-based face attendance runner
│       └── train_model.py         # Face recognizer training script
├── web/
│   ├── templates/                 # Jinja HTML templates
│   └── static/                    # CSS and uploaded student face images
├── data/
│   ├── attendance.db              # Runtime SQLite database
│   └── legacy/                    # Preserved old/unclassified artifacts
├── exports/                       # Generated Excel/PDF attendance reports
├── models/                        # Generated OpenCV trainer model
└── scripts/                       # Maintenance scripts
```

## Setup With `venv` and `pip`

Run these commands from the project root directory.

### Windows PowerShell

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python app.py
```

If PowerShell blocks activation scripts, allow them for the current user and try activation again:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

### Windows Command Prompt

```bat
py -m venv .venv
.venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
python app.py
```

### macOS/Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python app.py
```

After the server starts, open the Flask URL shown in the terminal, usually `http://127.0.0.1:5000`.

To stop the server, press `Ctrl+C` in the terminal. To leave the virtual environment, run:

```bash
deactivate
```

## First Admin Account

The database no longer creates sample users. Create a real admin profile before using the admin dashboard:

```bash
python scripts/create_admin.py --admin-id ADM-0001 --name "System Admin" --email admin@example.com --username admin_user --password "change-this-password"
```

Each login account is linked to a real profile ID:

| Role | Linked profile ID |
| --- | --- |
| Admin | `admins.admin_id` |
| Teacher | `teachers.teacher_id` |
| Student | `students.roll_no` |

Students and teachers should be created from the admin dashboard with real credentials. Existing student records without credentials are kept as inactive accounts until an admin assigns a password.

## Common Workflows

- Add students from the admin dashboard. Uploaded student photos are stored under `web/static/student_faces/`, and student login accounts are linked to roll numbers.
- For face recognition, use Admin > Students > `Capture face` for each student. The page opens an in-browser camera preview, captures multiple samples, and saves them under `web/static/student_faces/<roll_no>/`.
- Add teachers from the admin dashboard. Teacher credentials are linked to teacher IDs in the `users` table.
- Mark manual attendance from the teacher dashboard. Records are stored in `data/attendance.db`.
- For live face marking, open Teacher > Mark Attendance, select the subject, and click `Train and start camera`. The page trains the current face model, opens an in-page camera preview, and marks recognized students present. If the same student is already marked for that subject/date, the page reports that they are already marked instead of creating another row.
- Download reports from the relevant dashboard. Generated files are written under `exports/`.
- Train face attendance after student face images or captured samples exist. Training creates both `models/trainer.yml` and `models/label_map.json`, so student roll numbers can remain real string IDs while OpenCV uses internal numeric labels:

```bash
python -m src.attendance_system.train_model
```

- Start face attendance from the teacher dashboard after both `models/trainer.yml` and `models/label_map.json` have been generated. Recognized students are saved under the `Face Recognition` subject for the current date, and repeated camera runs update the same same-day face-recognition record instead of creating duplicates.

## Problem Statement Coverage

The implemented system covers the submitted project statement through:

- AI/OpenCV face-recognition attendance with camera-based face sample capture, trained student face data, and automatic database marking.
- Role-based login and dashboards for admin, teacher, and student users.
- Digital SQLite record storage for students, teachers, users, attendance, and notices.
- Attendance analytics, present/absent summaries, subject activity charts, monthly reports, and low-attendance warnings.
- Excel and PDF attendance report exports.
- Notice publishing by admin with notices visible on teacher and student dashboards.

## Maintenance Scripts

Run these from the project root:

```bash
python scripts/fix_database.py
python scripts/reset_attendance.py
python scripts/create_admin.py --admin-id ADM-0001 --name "System Admin" --username admin_user --password "change-this-password"
```

`fix_database.py` adds the attendance subject column for older databases. `reset_attendance.py` clears attendance rows, so use it only when resetting test data. `create_admin.py` creates or updates a real admin profile and linked login.

## Notes

- Runtime paths are project-relative, so the app no longer depends on the shell's current working directory.
- Existing database/report artifacts were preserved and moved into `data/`, `data/legacy/`, or `exports/`.
- The face-recognition workflow requires a camera and a trained model file at `models/trainer.yml`.
