"""测试辅助：向本地临时 e2e 数据库注入一个 is_staff 用户。

用法（仅本地验证环境）：
    DATABASE_URL="sqlite:////tmp/rbtest/e2e.db" python3 scripts/_e2e_mkstaff.py
"""
import os

from backend.database import SessionLocal
from backend import models
from backend.security import hash_password

db = SessionLocal()
if not db.query(models.WebUser).filter(models.WebUser.username == "staffer").first():
    u = models.WebUser(
        username="staffer",
        password_hash=hash_password("secret123"),
        is_staff=True,
        is_active=True,
    )
    db.add(u)
    db.commit()
    print("staff created", u.id)
else:
    print("staff exists")
db.close()
