"""
管理员和角色管理 API - 管理后台
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime
import pytz

from admin_database import AdminSessionLocal as SessionLocal
from admin_utils.models_loader import AdminUser, AdminRole, Permission
from admin_utils.auth import get_password_hash, is_super_admin, get_current_admin

router = APIRouter()


def get_db():
    """获取数据库会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ==================== 角色管理 ====================

@router.get("/roles")
async def get_roles(
    db: Session = Depends(get_db),
    admin = Depends(is_super_admin)
):
    """获取所有角色"""
    roles = db.query(AdminRole).all()
    result = []
    for role in roles:
        # 获取使用此角色的管理员数量
        user_count = db.query(AdminUser).filter(AdminUser.role == role.name).count()
        result.append({
            "id": role.id,
            "name": role.name,
            "display_name": role.display_name,
            "description": role.description,
            "permissions": role.permissions or Permission.get_permissions(role.name),
            "is_system": role.is_system,
            "user_count": user_count,
            "created_at": role.created_at
        })
    return result


@router.post("/roles")
async def create_role(
    data: dict,
    db: Session = Depends(get_db),
    admin = Depends(is_super_admin)
):
    """创建新角色"""
    # 检查角色名是否已存在
    existing = db.query(AdminRole).filter(AdminRole.name == data.get('name')).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="角色名已存在"
        )

    role = AdminRole(
        name=data.get('name'),
        display_name=data.get('display_name'),
        description=data.get('description'),
        permissions=data.get('permissions', []),
        is_system=False
    )
    db.add(role)
    db.commit()
    db.refresh(role)

    return {"message": "角色创建成功", "id": role.id}


@router.put("/roles/{role_id}")
async def update_role(
    role_id: int,
    data: dict,
    db: Session = Depends(get_db),
    admin = Depends(is_super_admin)
):
    """更新角色"""
    role = db.query(AdminRole).filter(AdminRole.id == role_id).first()
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="角色不存在"
        )

    if role.is_system:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="系统角色不能修改"
        )

    if 'display_name' in data:
        role.display_name = data['display_name']
    if 'description' in data:
        role.description = data['description']
    if 'permissions' in data:
        role.permissions = data['permissions']

    db.commit()
    return {"message": "角色更新成功"}


@router.delete("/roles/{role_id}")
async def delete_role(
    role_id: int,
    db: Session = Depends(get_db),
    admin = Depends(is_super_admin)
):
    """删除角色"""
    role = db.query(AdminRole).filter(AdminRole.id == role_id).first()
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="角色不存在"
        )

    if role.is_system:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="系统角色不能删除"
        )

    # 检查是否有管理员使用此角色
    user_count = db.query(AdminUser).filter(AdminUser.role == role.name).count()
    if user_count > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"还有 {user_count} 个管理员使用此角色，无法删除"
        )

    db.delete(role)
    db.commit()
    return {"message": "角色删除成功"}


# ==================== 权限定义 ====================

@router.get("/permissions")
async def get_permissions(
    admin = Depends(get_current_admin)
):
    """获取所有权限定义"""
    return {
        "groups": Permission.PERMISSION_GROUPS,
        "descriptions": Permission.PERMISSION_DESCRIPTIONS
    }


# ==================== 管理员管理 ====================

@router.get("/admins")
async def get_admins(
    db: Session = Depends(get_db),
    admin = Depends(get_current_admin)
):
    """获取所有管理员"""
    admins = db.query(AdminUser).all()
    result = []
    for adm in admins:
        # 获取角色信息
        role_obj = db.query(AdminRole).filter(AdminRole.name == adm.role).first()
        result.append({
            "id": adm.id,
            "username": adm.username,
            "role": adm.role,
            "role_display_name": role_obj.display_name if role_obj else adm.role,
            "is_active": adm.is_active,
            "last_login": adm.last_login,
            "created_at": adm.created_at
        })
    return result


@router.post("/admins")
async def create_admin(
    data: dict,
    db: Session = Depends(get_db),
    admin = Depends(is_super_admin)
):
    """创建新管理员"""
    # 检查用户名是否已存在
    existing = db.query(AdminUser).filter(AdminUser.username == data.get('username')).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户名已存在"
        )

    # 验证密码长度
    password = data.get('password', '')
    if len(password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="密码长度至少为6位"
        )

    # 验证角色是否存在
    role = data.get('role', 'operator')
    role_obj = db.query(AdminRole).filter(AdminRole.name == role).first()
    if not role_obj and role not in Permission.ROLE_PERMISSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="无效的角色"
        )

    new_admin = AdminUser(
        username=data.get('username'),
        password_hash=get_password_hash(password),
        role=role,
        is_active=data.get('is_active', True)
    )
    db.add(new_admin)
    db.commit()
    db.refresh(new_admin)

    return {"message": "管理员创建成功", "id": new_admin.id}


@router.put("/admins/{admin_id}")
async def update_admin(
    admin_id: int,
    data: dict,
    db: Session = Depends(get_db),
    current_admin = Depends(get_current_admin)
):
    """更新管理员"""
    target_admin = db.query(AdminUser).filter(AdminUser.id == admin_id).first()
    if not target_admin:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="管理员不存在"
        )

    # 非超级管理员只能修改自己的状态
    if current_admin.role != 'super_admin' and current_admin.id != admin_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只能修改自己的信息"
        )

    # 不能修改超级管理员
    if target_admin.role == 'super_admin' and current_admin.id != admin_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="不能修改超级管理员"
        )

    if 'role' in data and current_admin.role == 'super_admin':
        # 验证角色是否存在
        role = data['role']
        role_obj = db.query(AdminRole).filter(AdminRole.name == role).first()
        if not role_obj and role not in Permission.ROLE_PERMISSIONS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="无效的角色"
            )
        target_admin.role = role

    if 'is_active' in data and current_admin.role == 'super_admin':
        target_admin.is_active = data['is_active']

    if 'password' in data and data['password']:
        if len(data['password']) < 6:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="密码长度至少为6位"
            )
        target_admin.password_hash = get_password_hash(data['password'])

    target_admin.updated_at = datetime.now()
    db.commit()

    return {"message": "管理员更新成功"}


@router.delete("/admins/{admin_id}")
async def delete_admin(
    admin_id: int,
    db: Session = Depends(get_db),
    current_admin = Depends(get_current_admin)
):
    """删除管理员"""
    if current_admin.id == admin_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不能删除自己"
        )

    target_admin = db.query(AdminUser).filter(AdminUser.id == admin_id).first()
    if not target_admin:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="管理员不存在"
        )

    if target_admin.role == 'super_admin':
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不能删除超级管理员"
        )

    db.delete(target_admin)
    db.commit()

    return {"message": "管理员删除成功"}


@router.post("/admins/{admin_id}/reset-password")
async def reset_admin_password(
    admin_id: int,
    db: Session = Depends(get_db),
    current_admin = Depends(get_current_admin)
):
    """重置管理员密码（生成随机密码）"""
    import secrets
    import string

    target_admin = db.query(AdminUser).filter(AdminUser.id == admin_id).first()
    if not target_admin:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="管理员不存在"
        )

    # 生成随机密码
    password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12))
    target_admin.password_hash = get_password_hash(password)
    target_admin.updated_at = datetime.now()
    db.commit()

    return {
        "message": "密码重置成功",
        "password": password
    }
