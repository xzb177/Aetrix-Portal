"""
管理员用户模型
支持多角色权限系统
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, JSON, ForeignKey, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class AdminRole(Base):
    """管理员角色"""
    __tablename__ = 'admin_roles'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), unique=True, nullable=False)  # 角色名称：super_admin, admin, operator
    display_name = Column(String(100), nullable=False)  # 显示名称
    description = Column(Text)  # 角色描述
    permissions = Column(JSON)  # 权限列表
    is_system = Column(Boolean, default=False)  # 是否系统角色（不可删除）
    created_at = Column(DateTime, default=datetime.now)


class AdminUser(Base):
    """管理员用户"""
    __tablename__ = 'admin_users'

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False)  # 用户名
    password_hash = Column(String(255), nullable=False)  # 密码哈希
    role = Column(String(50), nullable=False, default="operator")  # 角色
    is_active = Column(Boolean, default=True)  # 是否启用
    last_login = Column(DateTime)  # 最后登录时间
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now)

    # 关联角色
    role_obj = relationship("AdminRole", foreign_keys=[role], primaryjoin="AdminUser.role==AdminRole.name")

    def __repr__(self):
        return f"<AdminUser(id={self.id}, username='{self.username}', role='{self.role}')>"


class AdminLog(Base):
    """管理员操作日志"""
    __tablename__ = 'admin_logs'

    __table_args__ = (
        Index('idx_adminlog_admin', 'admin_id'),
        Index('idx_adminlog_action', 'action'),
        Index('idx_adminlog_created', 'created_at'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    admin_id = Column(Integer, nullable=True, index=True)  # 操作管理员ID (可为NULL，用于登录失败等场景)
    admin_username = Column(String(50))  # 操作管理员用户名
    action = Column(String(100), nullable=False, index=True)  # 操作类型
    resource = Column(String(100))  # 操作资源
    resource_id = Column(String(100))  # 资源ID
    details = Column(JSON)  # 操作详情
    ip_address = Column(String(50))  # IP地址
    user_agent = Column(String(500))  # 用户代理
    created_at = Column(DateTime, default=datetime.now, index=True)


class Permission:
    """权限定义"""

    # 角色权限映射
    ROLE_PERMISSIONS = {
        "super_admin": [
            # 用户管理
            "users.view", "users.edit", "users.delete", "users.vip", "users.manage",
            # Emby 管理
            "emby.view", "emby.edit", "emby.push", "emby.unbind", "emby.manage",
            # 推送管理
            "push.view", "push.send", "push.config",
            # 活动管理
            "activities.view", "activities.create", "activities.edit", "activities.delete",
            # 统计分析
            "stats.view",
            # 订阅管理
            "subscriptions.view", "subscriptions.edit", "subscriptions.delete",
            # 门户用户
            "portal_users.view", "portal_users.edit", "portal_users.delete",
            # 公告管理
            "announcements.view", "announcements.create", "announcements.edit", "announcements.delete",
            # 工单管理
            "tickets.view", "tickets.reply", "tickets.close",
            # 系统管理
            "system.admins", "system.roles", "system.logs", "system.config", "system.view",
            # 支付管理
            "payment.config", "payment.orders", "payment.view",
            # 线路管理
            "routes.view", "routes.create", "routes.update", "routes.delete",
        ],
        "admin": [
            "users.view", "users.edit", "users.vip",
            "emby.view", "emby.push",
            "push.view", "push.send",
            "activities.view", "activities.create", "activities.edit",
            "stats.view",
            "subscriptions.view", "subscriptions.edit",
            "portal_users.view", "portal_users.edit",
            "announcements.view", "announcements.create", "announcements.edit",
            "tickets.view", "tickets.reply",
            "system.logs",
            "payment.orders",
            "system.view",
            "routes.view", "routes.create", "routes.update",
        ],
        "operator": [
            "users.view",
            "emby.view",
            "push.view", "push.send",
            "activities.view",
            "stats.view",
            "subscriptions.view",
            "portal_users.view",
            "announcements.view",
            "tickets.view",
            "system.view",
            "payment.view",
            "routes.view",
        ],
        "viewer": [
            "stats.view",
            "system.view",
        ],
    }

    # 权限描述
    PERMISSION_DESCRIPTIONS = {
        # 用户管理
        "users.view": "查看Telegram用户",
        "users.edit": "编辑用户信息",
        "users.delete": "删除用户",
        "users.vip": "管理VIP状态",
        "users.manage": "用户全权管理",
        # Emby 管理
        "emby.view": "查看Emby数据",
        "emby.edit": "编辑Emby绑定",
        "emby.push": "手动推送影片",
        "emby.unbind": "解绑Emby账号",
        "emby.manage": "Emby服务器管理",
        # 推送管理
        "push.view": "查看推送记录",
        "push.send": "发送推送",
        "push.config": "配置推送规则",
        # 活动管理
        "activities.view": "查看活动",
        "activities.create": "创建活动",
        "activities.edit": "编辑活动",
        "activities.delete": "删除活动",
        # 统计分析
        "stats.view": "查看统计数据",
        # 订阅管理
        "subscriptions.view": "查看订阅套餐",
        "subscriptions.edit": "编辑订阅套餐",
        "subscriptions.delete": "删除订阅套餐",
        # 门户用户
        "portal_users.view": "查看门户用户",
        "portal_users.edit": "编辑门户用户",
        "portal_users.delete": "删除门户用户",
        # 公告管理
        "announcements.view": "查看公告",
        "announcements.create": "创建公告",
        "announcements.edit": "编辑公告",
        "announcements.delete": "删除公告",
        # 工单管理
        "tickets.view": "查看工单",
        "tickets.reply": "回复工单",
        "tickets.close": "关闭工单",
        # 系统管理
        "system.admins": "管理管理员",
        "system.roles": "管理角色权限",
        "system.logs": "查看操作日志",
        "system.config": "修改系统配置",
        "system.view": "查看系统信息",
        # 支付管理
        "payment.config": "配置支付",
        "payment.orders": "查看支付订单",
        "payment.view": "查看支付信息",
        # 线路管理
        "routes.view": "查看线路配置",
        "routes.create": "创建线路",
        "routes.update": "修改线路",
        "routes.delete": "删除线路",
    }

    # 权限分组
    PERMISSION_GROUPS = {
        "用户管理": ["users.view", "users.edit", "users.delete", "users.vip", "users.manage"],
        "Emby管理": ["emby.view", "emby.edit", "emby.push", "emby.unbind", "emby.manage"],
        "推送管理": ["push.view", "push.send", "push.config"],
        "活动管理": ["activities.view", "activities.create", "activities.edit", "activities.delete"],
        "数据统计": ["stats.view"],
        "订阅管理": ["subscriptions.view", "subscriptions.edit", "subscriptions.delete"],
        "门户用户": ["portal_users.view", "portal_users.edit", "portal_users.delete"],
        "公告管理": ["announcements.view", "announcements.create", "announcements.edit", "announcements.delete"],
        "工单管理": ["tickets.view", "tickets.reply", "tickets.close"],
        "系统管理": ["system.admins", "system.roles", "system.logs", "system.config", "system.view"],
        "支付管理": ["payment.config", "payment.orders", "payment.view"],
        "线路管理": ["routes.view", "routes.create", "routes.update", "routes.delete"],
    }

    @classmethod
    def get_permissions(cls, role: str) -> list:
        """获取角色的权限列表"""
        return cls.ROLE_PERMISSIONS.get(role, [])

    @classmethod
    def has_permission(cls, role: str, permission: str) -> bool:
        """检查角色是否有指定权限"""
        return permission in cls.ROLE_PERMISSIONS.get(role, [])

    @classmethod
    def all_permissions(cls) -> dict:
        """获取所有权限定义"""
        return cls.PERMISSION_DESCRIPTIONS
