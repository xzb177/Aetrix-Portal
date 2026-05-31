"""
风控服务

实现账号安全和异常检测：
- 多设备/共享检测
- 异常登录检测
- 操作行为分析
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func, and_

from database.models import (
    WebUser, UserEmbyAccount, UserSubscription,
    UserAuditLog, EmbyServer
)
from utils.emby_client import EmbyClient
from utils.notifier import send_risk_alert_message

logger = logging.getLogger(__name__)


# ==================== 配置 ====================

# 风控阈值配置
RISK_CONFIG = {
    # 最大同时活跃设备数（Emby sessions）
    'MAX_CONCURRENT_DEVICES': 3,

    # 最大不同IP地址数（24小时内）
    'MAX_DIFFERENT_IPS': 5,

    # 最短登录间隔（秒，防止爆破）
    'MIN_LOGIN_INTERVAL': 3,

    # 登录失败次数阈值
    'MAX_LOGIN_FAILURES': 5,

    # 登录失败锁定时间（分钟）
    'LOGIN_FAILURE_LOCKOUT': 30,

    # IP地理位置变化检测（是否启用）
    'CHECK_LOCATION_CHANGE': True,
}


# ==================== 账号共享检测 ====================

async def detect_account_sharing(
    user_id: int,
    emby_user_id: str,
    server_url: str,
    api_key: str
) -> Dict:
    """
    检测账号共享行为

    检测点：
    1. 同时活跃的设备数量
    2. 24小时内不同IP地址数量
    3. 同时播放的流数量

    Args:
        user_id: 用户ID
        emby_user_id: Emby 用户ID
        server_url: Emby 服务器地址
        api_key: API Key

    Returns:
        检测结果字典
    """
    try:
        emby_client = EmbyClient(server_url, api_key)

        # 获取用户会话信息（Emby 需要扩展 API）
        # 这里模拟检测结果
        risk_level = "low"
        reasons = []

        # TODO: 实际实现需要调用 Emby API 获取 sessions
        # sessions = emby_client.get_user_sessions(emby_user_id)

        # 检测1: 同时活跃设备数
        # active_devices = len([s for s in sessions if s.get('IsActive', False)])
        # if active_devices > RISK_CONFIG['MAX_CONCURRENT_DEVICES']:
        #     risk_level = "high"
        #     reasons.append(f"同时活跃设备数过多: {active_devices}")

        # 检测2: 同时播放的流
        # active_streams = len([s for s in sessions if s.get('NowPlayingItem')])
        # if active_streams > 1:
        #     risk_level = "medium"
        #     reasons.append(f"检测到同时播放: {active_streams} 路")

        return {
            'risk_level': risk_level,
            'reasons': reasons,
            'detected_at': datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"账号共享检测失败: {e}")
        return {
            'risk_level': 'unknown',
            'reasons': [f"检测失败: {str(e)}"],
            'detected_at': datetime.now().isoformat()
        }


async def check_concurrent_streams(
    user_id: int,
    db: Session
) -> Optional[Dict]:
    """
    检查用户是否有并发播放行为

    Args:
        user_id: 用户ID
        db: 数据库会话

    Returns:
        检测结果，无异常返回 None
    """
    try:
        # 获取用户的 Emby 账号
        accounts = db.query(UserEmbyAccount).filter(
            UserEmbyAccount.user_id == user_id
        ).all()

        for account in accounts:
            server = db.query(EmbyServer).filter(
                EmbyServer.id == account.server_id
            ).first()

            if server and server.is_active:
                result = await detect_account_sharing(
                    user_id=user_id,
                    emby_user_id=account.emby_user_id,
                    server_url=server.url,
                    api_key=server.api_key
                )

                if result['risk_level'] in ['medium', 'high']:
                    return result

        return None

    except Exception as e:
        logger.error(f"并发播放检测失败: {e}")
        return None


# ==================== 异常登录检测 ====================

class LoginTracker:
    """登录追踪器（Redis 存储，支持多实例部署）"""

    _redis = None

    @classmethod
    def _get_redis(cls):
        if cls._redis is None:
            from utils.redis_client import get_sync_redis
            cls._redis = get_sync_redis()
        return cls._redis

    @classmethod
    def check_login_allowed(cls, user_id: int, ip_address: str) -> Tuple[bool, Optional[str]]:
        """检查是否允许登录"""
        now = datetime.now()
        redis = cls._get_redis()
        if not redis.available:
            return True, None  # Redis 不可用时降级放行

        # 检查是否被锁定
        locked_until = redis.get(f"login_lock:{user_id}")
        if locked_until:
            lock_time = datetime.fromisoformat(locked_until)
            if now < lock_time:
                remaining = int((lock_time - now).total_seconds() / 60)
                return False, f"登录失败过多，请 {remaining} 分钟后再试"

        # 检查登录间隔（防爆破）
        last_attempt = redis.get(f"login_last:{user_id}")
        if last_attempt:
            interval = (now - datetime.fromisoformat(last_attempt)).total_seconds()
            if interval < RISK_CONFIG['MIN_LOGIN_INTERVAL']:
                return False, "登录过于频繁，请稍后再试"

        return True, None

    @classmethod
    def record_login_success(cls, user_id: int, ip_address: str, user_agent: str):
        """记录成功登录"""
        now = datetime.now()
        redis = cls._get_redis()
        if not redis.available:
            return

        # 清除失败记录
        redis.delete(f"login_attempts:{user_id}", f"login_lock:{user_id}")

        # 记录登录历史（用 Redis list，保留最近 100 条）
        import json
        history_key = f"login_history:{user_id}"
        record = json.dumps({"ip": ip_address, "ua": user_agent, "time": now.isoformat()})
        redis._client.lpush(history_key, record) if redis._client else None
        if redis._client:
            redis._client.ltrim(history_key, 0, 99)
        redis.expire(history_key, 86400 * 7)  # 7 天过期

        logger.info(f"记录用户 {user_id} 登录成功: IP={ip_address}")

    @classmethod
    def record_login_failure(cls, user_id: int, ip_address: str):
        """记录登录失败"""
        now = datetime.now()
        redis = cls._get_redis()
        if not redis.available:
            return

        # 更新失败次数和时间
        attempts_key = f"login_attempts:{user_id}"
        attempts = redis.incr(attempts_key)
        redis.expire(attempts_key, 3600)  # 1 小时窗口
        redis.set(f"login_last:{user_id}", now.isoformat(), ex=3600)

        # 检查是否需要锁定
        if attempts and int(attempts) >= RISK_CONFIG['MAX_LOGIN_FAILURES']:
            lock_until = now + timedelta(minutes=RISK_CONFIG['LOGIN_FAILURE_LOCKOUT'])
            redis.set(f"login_lock:{user_id}", lock_until.isoformat(),
                       ex=RISK_CONFIG['LOGIN_FAILURE_LOCKOUT'] * 60)
            logger.warning(f"用户 {user_id} 登录失败过多，已锁定 {RISK_CONFIG['LOGIN_FAILURE_LOCKOUT']} 分钟")

    @classmethod
    def get_recent_ips(cls, user_id: int, hours: int = 24) -> List[str]:
        """获取用户最近的 IP 地址列表"""
        redis = cls._get_redis()
        if not redis.available or not redis._client:
            return []

        history_key = f"login_history:{user_id}"
        records = redis._client.lrange(history_key, 0, 99)
        cutoff = datetime.now() - timedelta(hours=hours)
        ips = set()
        import json
        for r in records:
            try:
                data = json.loads(r)
                if datetime.fromisoformat(data["time"]) > cutoff:
                    ips.add(data["ip"])
            except Exception:
                continue
        return list(ips)

    @classmethod
    def check_new_location(cls, user_id: int, ip_address: str) -> bool:
        """检查是否为新位置登录"""
        recent_ips = cls.get_recent_ips(user_id, hours=24)
        return ip_address not in recent_ips and len(recent_ips) > 0


# ==================== 操作行为分析 ====================

def analyze_user_behavior(
    user_id: int,
    db: Session,
    days: int = 7
) -> Dict:
    """
    分析用户操作行为

    分析维度：
    1. 登录频率
    2. 操作类型分布
    3. 异常操作模式

    Args:
        user_id: 用户ID
        db: 数据库会话
        days: 分析天数

    Returns:
        分析结果
    """
    try:
        from database.models import UserAuditLog

        cutoff = datetime.now() - timedelta(days=days)

        # 获取操作日志
        logs = db.query(UserAuditLog).filter(
            UserAuditLog.user_id == user_id,
            UserAuditLog.created_at >= cutoff
        ).all()

        # 统计操作类型
        action_counts = {}
        for log in logs:
            action_counts[log.action] = action_counts.get(log.action, 0) + 1

        # 分析异常模式
        anomalies = []

        # 检测1: 密码重置次数过多
        if action_counts.get('reset_password', 0) > 3:
            anomalies.append("密码重置频繁")

        # 检测2: 账号领取次数过多
        if action_counts.get('claim_account', 0) > 5:
            anomalies.append("账号领取频繁")

        # 检测3: 短时间内大量操作
        if len(logs) > 100:
            anomalies.append("操作频率异常")

        return {
            'total_actions': len(logs),
            'action_distribution': action_counts,
            'anomalies': anomalies,
            'risk_score': min(len(anomalies) * 20, 100)
        }

    except Exception as e:
        logger.error(f"用户行为分析失败: {e}")
        return {
            'total_actions': 0,
            'action_distribution': {},
            'anomalies': [],
            'risk_score': 0
        }


# ==================== 风险评分 ====================

def calculate_risk_score(
    user_id: int,
    db: Session
) -> Dict:
    """
    计算用户综合风险评分

    Args:
        user_id: 用户ID
        db: 数据库会话

    Returns:
        风险评分结果
    """
    try:
        risk_factors = []
        total_score = 0

        # 因子1: 操作行为异常
        behavior = analyze_user_behavior(user_id, db)
        if behavior['risk_score'] > 0:
            risk_factors.append(f"操作行为异常: {behavior['risk_score']}分")
            total_score += behavior['risk_score']

        # 因子2: 多IP登录
        recent_ips = LoginTracker.get_recent_ips(user_id, hours=24)
        if len(recent_ips) > RISK_CONFIG['MAX_DIFFERENT_IPS']:
            risk_factors.append(f"多IP登录: {len(recent_ips)}个IP")
            total_score += 30

        # 因子3: 登录失败次数
        attempts = LoginTracker._login_attempts.get(user_id, {}).get('attempts', 0)
        if attempts > 0:
            risk_factors.append(f"登录失败: {attempts}次")
            total_score += min(attempts * 10, 50)

        # 计算风险等级
        if total_score >= 80:
            level = "critical"
        elif total_score >= 50:
            level = "high"
        elif total_score >= 30:
            level = "medium"
        else:
            level = "low"

        return {
            'score': total_score,
            'level': level,
            'factors': risk_factors,
            'user_id': user_id
        }

    except Exception as e:
        logger.error(f"风险评分计算失败: {e}")
        return {
            'score': 0,
            'level': 'unknown',
            'factors': [],
            'user_id': user_id
        }
