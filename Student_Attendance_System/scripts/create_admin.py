import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.attendance_system import database


def parse_args():
    parser = argparse.ArgumentParser(
        description="Create or update a real admin profile and linked login account."
    )
    parser.add_argument("--admin-id", required=True, help="Stable admin ID, for example ADM-0001.")
    parser.add_argument("--name", required=True, help="Admin full name.")
    parser.add_argument("--email", default="", help="Admin email address.")
    parser.add_argument("--phone", default="", help="Admin phone number.")
    parser.add_argument("--username", required=True, help="Login username.")
    parser.add_argument("--password", required=True, help="Login password.")
    return parser.parse_args()


def main():
    args = parse_args()
    database.create_admin(
        admin_id=args.admin_id,
        name=args.name,
        email=args.email,
        phone=args.phone,
        username=args.username,
        password=args.password,
    )
    print(f"Admin {args.admin_id} is ready.")


if __name__ == "__main__":
    main()
