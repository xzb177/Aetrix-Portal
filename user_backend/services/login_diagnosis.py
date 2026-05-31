"""
登录自诊断服务
用户登录失败时自动检测问题原因，返回可读的诊断结果
"""
import logging
import time
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session

from database.models import WebUser, EmbyServer, UserEmbyAccount, UserSubscription
from utils.emby_client import EmbyClient

logger = logging.getLogger(__name__)


class LoginDiagnosis:
    """登录自诊断引擎"""

    @staticmethod
    def diagnose(
        username: str,
        db: Session,
        client_ip: str = "",
        user_agent: str = ""
    ) -> Dict[str, Any]:
        """
        全面诊断登录问题

        Returns:
            {
                "can_login": bool,
                "issues": [{"type": str, "severity": str, "message": str, "action": str}],
                "server_status": [...],
                "account_info": {...}
            }
        """
        issues = []
        server_status = []
        account_info = {}

        # 1. 检查用户是否存在
        user = db.query(WebUser).filter(WebUser.username == username).first()
        if not user:
            return {
                "can_login": False,
                "issues": [{
                    "type": "user_not_found",
                    "severity": "error",
                    "message": "用户名不存在",
                    "action": "请检查用户名是否正确，或注册新账号"
                }],
                "server_status": [],
                "account_info": {}
            }

        account_info["username"] = user.username
        account_info["is_active"] = user.is_active
        account_info["created_at"] = user.created_at.isoformat() if user.created_at else None

        # 2. 检查账号状态
        if not user.is_active:
            issues.append({
                "type": "account_disabled",
                "severity": "error",
                "message": "账号已被禁用",
                "action": "请联系管理员启用账号"
            })

        # 3. 检查订阅状态
        subscription = db.query(UserSubscription).filter(
            UserSubscription.user_id == user.id,
            UserSubscription.status == 'active'
        ).first()

        if subscription:
            from datetime import datetime
            if subscription.end_date and subscription.end_date < datetime.now():
                issues.append({
                    "type": "subscription_expired",
                    "severity": "warning",
                    "message": f"订阅已于 {subscription.end_date.strftime('%Y-%m-%d')} 过期",
                    "action": "请续费以恢复 Emby 访问权限"
                })
                account_info["subscription_status"] = "expired"
                account_info["expired_at"] = subscription.end_date.isoformat()
            else:
                account_info["subscription_status"] = "active"
                account_info["expires_at"] = subscription.end_date.isoformat() if subscription.end_date else None
        else:
            issues.append({
                "type": "no_subscription",
                "severity": "warning",
                "message": "未找到有效订阅",
                "action": "请购买订阅套餐以获得 Emby 访问权限"
            })
            account_info["subscription_status"] = "none"

        # 4. 检查 Emby 账号
        emby_accounts = db.query(UserEmbyAccount).filter(
            UserEmbyAccount.user_id == user.id
        ).all()

        if not emby_accounts:
            issues.append({
                "type": "no_emby_account",
                "severity": "warning",
                "message": "未找到 Emby 账号",
                "action": "订阅后请到首页领取 Emby 账号"
            })
        else:
            for account in emby_accounts:
                server = db.query(EmbyServer).filter(EmbyServer.id == account.server_id).first()
                server_name = server.name if server else f"Server#{account.server_id}"

                if not account.is_active:
                    issues.append({
                        "type": "emby_account_disabled",
                        "severity": "error",
                        "message": f"Emby 账号 ({server_name}) 已禁用",
                        "action": "账号可能因订阅过期被禁用，续费后将自动恢复"
                    })

                # 5. 检查 Emby 服务器连通性
                if server:
                    diag = LoginDiagnosis._check_server(server)
                    server_status.append(diag)
                    if not diag["reachable"]:
                        issues.append({
                            "type": "server_unreachable",
                            "severity": "error",
                            "message": f"Emby 服务器 ({server_name}) 无法连接",
                            "action": "服务器可能正在维护，请稍后重试或联系管理员"
                        })

        # 6. 检查 IP 风控
        from services.risk_control import LoginTracker
        allowed, reason = LoginTracker.check_login_allowed(user.id, client_ip)
        if not allowed:
            issues.append({
                "type": "rate_limited",
                "severity": "error",
                "message": reason or "登录过于频繁",
                "action": "请稍后再试"
            })

        # 7. 检查新位置登录
        if client_ip:
            is_new = LoginTracker.check_new_location(user.id, client_ip)
            if is_new:
                issues.append({
                    "type": "new_location",
                    "severity": "info",
                    "message": f"检测到新位置登录 ({client_ip[:8]}...)",
                    "action": "如果是你本人操作，请忽略"
                })

        # 汇总判断
        can_login = not any(i["severity"] == "error" for i in issues)

        return {
            "can_login": can_login,
            "issues": issues,
            "server_status": server_status,
            "account_info": account_info
        }

    @staticmethod
    def _check_server(server: EmbyServer) -> Dict[str, Any]:
        """检查单个 Emby 服务器状态"""
        try:
            client = EmbyClient(server.url, server.api_key)
            start = time.time()
            result = client.test_connection()
            latency = int((time.time() - start) * 1000)

            return {
                "server_id": server.id,
                "name": server.name,
                "url": server.url,
                "reachable": result.get("success", False),
                "latency_ms": latency,
                "is_active": server.is_active,
                "current_users": server.current_users,
                "max_users": server.max_users,
                "info": result.get("info", {})
            }
        except Exception as e:
            error_msg = "连接超时" if "timeout" in str(e).lower() else "连接失败"
            return {
                "server_id": server.id,
                "name": server.name,
                "url": server.url,
                "reachable": False,
                "error": error_msg,
                "is_active": server.is_active
            }

    @staticmethod
    def quick_check(db: Session) -> Dict[str, Any]:
        """快速检查所有 Emby 服务器状态（管理端用）"""
        servers = db.query(EmbyServer).all()
        results = []
        all_healthy = True

        for server in servers:
            diag = LoginDiagnosis._check_server(server)
            results.append(diag)
            if not diag["reachable"]:
                all_healthy = False

        return {
            "all_healthy": all_healthy,
            "total_servers": len(servers),
            "online_count": sum(1 for r in results if r["reachable"]),
            "servers": results
        }
