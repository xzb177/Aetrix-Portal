"""
模型加载器
使用 importlib 直接加载管理员模型，避免触发 database/__init__.py
"""
import sys
import os
import importlib.util

# 获取 admin_backend 目录的路径
current_dir = os.path.dirname(os.path.abspath(__file__))
admin_dir = os.path.dirname(current_dir)

# 加载 models/admin.py
models_admin_path = os.path.join(admin_dir, "models", "admin.py")
spec = importlib.util.spec_from_file_location("models_admin", models_admin_path)
models_admin = importlib.util.module_from_spec(spec)
sys.modules['models_admin'] = models_admin
spec.loader.exec_module(models_admin)

# 导出模型类
AdminUser = models_admin.AdminUser
AdminRole = models_admin.AdminRole
AdminLog = models_admin.AdminLog
Permission = models_admin.Permission

__all__ = ['AdminUser', 'AdminRole', 'AdminLog', 'Permission']
