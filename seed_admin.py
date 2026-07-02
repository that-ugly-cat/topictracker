"""
Run once to create the first admin user.

  python seed_admin.py admin@example.com MyPassword123 "Admin Name"
"""
import sys
from pathlib import Path

Path("data").mkdir(exist_ok=True)

from models import User, init_db, SessionLocal
from auth import hash_password

email    = sys.argv[1] if len(sys.argv) > 1 else "admin@topictracker.local"
password = sys.argv[2] if len(sys.argv) > 2 else "changeme"
name     = sys.argv[3] if len(sys.argv) > 3 else "Admin"

init_db()
db = SessionLocal()

if db.query(User).filter(User.email == email).first():
    print(f"User {email} already exists.")
else:
    db.add(User(email=email, name=name, password_hash=hash_password(password), is_admin=True))
    db.commit()
    print(f"Admin created: {email}")

db.close()
