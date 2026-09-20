"""测试辅助：升级指定用户为 is_staff（默认 boss）。

用法（仅本地验证环境）：
    DATABASE_URL="sqlite:////tmp/rbtest/e2e.db" python3 scripts/_e2e_mkstaff.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import SessionLocal
from backend import models

username = os.environ.get("E2E_STAFF_USER", "boss")

db = SessionLocal()
u = db.query(models.WebUser).filter(models.WebUser.username == username).first()
if u is None:
    raise SystemExit(f"user not found: {username}")
u.is_staff = True
u.is_active = True
db.commit()
print(f"staff granted to {username} (uid={u.id})")
db.close()
