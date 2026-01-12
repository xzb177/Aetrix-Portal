"""
Emby API 客户端
用于与 Emby 服务器交互，创建用户、管理账号等
"""
import requests
import secrets
import string
from typing import Optional, Dict, Any, List
from datetime import datetime


class EmbyClient:
    """Emby API 客户端"""

    def __init__(self, server_url: str, api_key: str):
        """
        初始化 Emby 客户端

        Args:
            server_url: Emby 服务器地址 (如: http://emby.example.com:8096)
            api_key: Emby API Key
        """
        self.server_url = server_url.rstrip('/')
        self.api_key = api_key
        self.headers = {
            'X-Emby-Token': api_key,
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }

    def _request(self, method: str, endpoint: str, **kwargs) -> Optional[Dict]:
        """
        发送 HTTP 请求

        Args:
            method: HTTP 方法
            endpoint: API 端点
            **kwargs: 其他请求参数

        Returns:
            响应数据
        """
        url = f"{self.server_url}{endpoint}"
        try:
            response = requests.request(method, url, headers=self.headers, timeout=10, **kwargs)
            response.raise_for_status()
            if response.status_code == 204:  # No Content
                return None
            return response.json()
        except requests.RequestException as e:
            print(f"Emby API 请求失败: {e}")
            return None

    def test_connection(self) -> Dict[str, Any]:
        """
        测试服务器连接

        Returns:
            {'success': bool, 'message': str, 'info': dict}
        """
        try:
            # 获取系统信息
            info = self._request('GET', '/System/Info')
            if info:
                return {
                    'success': True,
                    'message': '连接成功',
                    'info': {
                        'server_name': info.get('ServerName'),
                        'version': info.get('Version'),
                        'operating_system': info.get('OperatingSystem')
                    }
                }
            return {'success': False, 'message': '无法连接到服务器'}
        except Exception as e:
            return {'success': False, 'message': f'连接失败: {str(e)}'}

    def get_users_count(self) -> int:
        """
        获取服务器用户总数

        Returns:
            用户数量
        """
        users = self._request('GET', '/Users')
        if users:
            # 排除隐藏的系统账户，只统计普通用户
            # 隐藏账户通常有 'Hidden' 属性或名称以特殊字符开头
            return len([u for u in users if not u.get('Hidden', False)])
        return 0

    def get_users(self) -> List[Dict]:
        """
        获取所有用户列表

        Returns:
            用户列表
        """
        users = self._request('GET', '/Users')
        if users:
            return [
                {
                    'id': u.get('Id'),
                    'name': u.get('Name'),
                    'has_password': u.get('HasPassword', False),
                    'last_login': u.get('LastLoginDate'),
                    'last_activity': u.get('LastActivityDate')
                }
                for u in users
            ]
        return []

    def user_exists(self, username: str) -> bool:
        """
        检查用户是否存在

        Args:
            username: 用户名

        Returns:
            是否存在
        """
        users = self.get_users()
        return any(u['name'] == username for u in users)

    def create_user(
        self,
        username: str,
        password: str,
        email: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        创建新用户

        重要：根据 Emby API 文档，创建用户时不能直接设置密码。
        必须先创建用户，然后通过单独的 API 设置密码。

        Args:
            username: 用户名
            password: 密码
            email: 邮箱（可选）

        Returns:
            {'success': bool, 'user_id': str, 'message': str}
        """
        # 检查用户是否已存在
        if self.user_exists(username):
            return {'success': False, 'message': f'用户 {username} 已存在'}

        try:
            # 步骤 1: 创建用户（不包含密码）
            user_data = {'Name': username}
            if email:
                user_data['Email'] = email

            result = self._request('POST', '/Users/New', json=user_data)
            if not result:
                return {'success': False, 'message': '创建用户失败: 服务器无响应'}

            user_id = result.get('Id')
            if not user_id:
                return {'success': False, 'message': '创建用户失败: 未返回用户 ID'}

            # 步骤 2: 设置密码（必须步骤，否则用户无法登录）
            if password:
                try:
                    password_response = requests.post(
                        f"{self.server_url}/Users/{user_id}/Password",
                        headers=self.headers,
                        json={'NewPassword': password, 'ResetPassword': False},
                        timeout=10
                    )
                    password_response.raise_for_status()
                    # 204 No Content 表示成功
                    if password_response.status_code not in [200, 204]:
                        raise Exception(f"密码设置返回状态码: {password_response.status_code}")
                except Exception as e:
                    # 密码设置失败，删除用户并返回错误
                    self.delete_user(user_id)
                    return {'success': False, 'message': f'用户创建成功，但密码设置失败: {str(e)}'}

            return {
                'success': True,
                'user_id': user_id,
                'message': f'用户 {username} 创建成功'
            }
        except Exception as e:
            return {'success': False, 'message': f'创建用户失败: {str(e)}'}

    def update_user_password(self, user_id: str, new_password: str) -> bool:
        """
        更新用户密码

        Args:
            user_id: 用户 ID
            new_password: 新密码

        Returns:
            是否成功
        """
        result = self._request('POST', f'/Users/{user_id}/Password', json={
            'NewPassword': new_password,
            'ResetPassword': False
        })
        return result is not None

    def delete_user(self, user_id: str) -> bool:
        """
        删除用户

        Args:
            user_id: 用户 ID

        Returns:
            是否成功
        """
        result = self._request('DELETE', f'/Users/{user_id}')
        return result is not None

    def get_user_id(self, username: str) -> Optional[str]:
        """
        根据用户名获取用户 ID

        Args:
            username: 用户名

        Returns:
            用户 ID
        """
        users = self.get_users()
        for user in users:
            if user['name'] == username:
                return user['id']
        return None

    def disable_user(self, user_id: str) -> bool:
        """
        禁用用户

        Args:
            user_id: 用户 ID

        Returns:
            是否成功
        """
        # Emby 没有直接的禁用 API，可以通过修改密码或删除来实现
        # 这里使用修改随机密码的方式
        random_password = self.generate_password(16)
        return self.update_user_password(user_id, random_password)

    @staticmethod
    def generate_password(length: int = 12) -> str:
        """
        生成随机密码

        Args:
            length: 密码长度

        Returns:
            随机密码
        """
        alphabet = string.ascii_letters + string.digits + '!@#$%^&*'
        return ''.join(secrets.choice(alphabet) for _ in range(length))

    def get_latest_items(self, limit: int = 20) -> List[Dict]:
        """
        获取最近播放/添加的媒体项

        Args:
            limit: 返回数量限制

        Returns:
            最近播放的媒体列表
        """
        # 使用 Users/Items/Latest 端点获取最近播放
        items = self._request('GET', f'/Users/Items/Latest?Limit={limit}&IncludeItemTypes=Movie,Episode')
        if items:
            return [
                {
                    'id': item.get('Id'),
                    'name': item.get('Name'),
                    'type': item.get('Type'),
                    'series_name': item.get('SeriesName'),
                    'season_id': item.get('SeasonId'),
                    'primary_image_tag': item.get('ImageTags', {}).get('Primary'),
                    'thumb_image_tag': item.get('ImageTags', {}).get('Thumb'),
                    'backdrop_image_tag': item.get('ImageTags', {}).get('Backdrop'),
                    'production_year': item.get('ProductionYear'),
                    'community_rating': item.get('CommunityRating'),
                    'run_time_ticks': item.get('RunTimeTicks'),
                    'date_created': item.get('DateCreated'),
                }
                for item in items
            ]
        return []

    def get_recently_played(self, user_id: str, limit: int = 20) -> List[Dict]:
        """
        获取指定用户的最近播放记录

        Args:
            user_id: Emby 用户 ID
            limit: 返回数量限制

        Returns:
            最近播放的媒体列表
        """
        # 使用 Users/{userId}/Items/Resume 端点获取继续播放项
        items = self._request('GET', f'/Users/{user_id}/Items/Resume?Limit={limit}')
        if items:
            return [
                {
                    'id': item.get('Id'),
                    'name': item.get('Name'),
                    'type': item.get('Type'),
                    'series_name': item.get('SeriesName'),
                    'season_id': item.get('SeasonId'),
                    'primary_image_tag': item.get('ImageTags', {}).get('Primary'),
                    'thumb_image_tag': item.get('ImageTags', {}).get('Thumb'),
                    'backdrop_image_tag': item.get('ImageTags', {}).get('Backdrop'),
                    'production_year': item.get('ProductionYear'),
                    'community_rating': item.get('CommunityRating'),
                    'run_time_ticks': item.get('RunTimeTicks'),
                    'played_percentage': item.get('UserData', {}).get('PlayedPercentage'),
                    'last_played_date': item.get('UserData', {}).get('LastPlayedDate'),
                }
                for item in items
            ]
        return []

    def get_item_image_url(self, item_id: str, image_tag: str = None, image_type: str = 'Primary') -> str:
        """
        获取媒体图片 URL

        Args:
            item_id: 媒体 ID
            image_tag: 图片标签（用于缓存）
            image_type: 图片类型 (Primary/Thumb/Backdrop)

        Returns:
            图片 URL
        """
        url = f"{self.server_url}/Items/{item_id}/Images/{image_type}"
        if image_tag:
            url += f"?tag={image_tag}"
        return url

    @staticmethod
    def generate_username(user_id: int, prefix: str = 'rb') -> str:
        """
        生成 Emby 用户名

        Args:
            user_id: 用户 ID
            prefix: 前缀

        Returns:
            用户名
        """
        return f'{prefix}_{user_id}'

    # ==================== P0: 权限策略映射 ====================

    def set_user_policy(
        self,
        user_id: str,
        max_active_sessions: int = 3,
        enable_video_playback: bool = True,
        enable_audio_playback: bool = True,
        enable_content_deletion: bool = False,
        enable_content_downloading: bool = False,
        enable_sync_transcoding: bool = True,
        enable_media_conversion: bool = True,
        max_streaming_bitrate: int = 150000000,  # 默认 150Mbps
        blocked_tags: Optional[List[str]] = None,
        enabled_folders: Optional[List[str]] = None
    ) -> bool:
        """
        设置用户策略（权限映射）

        Args:
            user_id: Emby 用户 ID
            max_active_sessions: 最大同时活跃会话数（防账号共享）
            enable_video_playback: 是否允许视频播放
            enable_audio_playback: 是否允许音频播放
            enable_content_deletion: 是否允许删除内容
            enable_content_downloading: 是否允许下载
            enable_sync_transcoding: 是否允许转码
            enable_media_conversion: 是否允许媒体转换
            max_streaming_bitrate: 最大码率（bps）
            blocked_tags: 屏蔽的标签
            enabled_folders: 允许访问的媒体库文件夹ID列表

        Returns:
            是否成功
        """
        # 获取用户当前信息
        user_info = self._request('GET', f'/Users/{user_id}')
        if not user_info:
            return False

        # 构建策略数据
        policy = user_info.get('Policy', {})

        # 更新策略
        policy.update({
            'MaxActiveSessions': max_active_sessions,
            'EnableVideoPlayback': enable_video_playback,
            'EnableAudioPlayback': enable_audio_playback,
            'EnableContentDeletion': enable_content_deletion,
            'EnableContentDownloading': enable_content_downloading,
            'EnableSyncTranscoding': enable_sync_transcoding,
            'EnableMediaConversion': enable_media_conversion,
            'MaxStreamingBitrate': max_streaming_bitrate,
        })

        if blocked_tags:
            policy['BlockedTags'] = blocked_tags

        if enabled_folders is not None:
            policy['EnabledFolders'] = enabled_folders

        # 更新用户策略
        result = self._request('POST', f'/Users/{user_id}/Policy', json=policy)
        return result is not None

    def get_user_policy(self, user_id: str) -> Optional[Dict]:
        """
        获取用户策略

        Args:
            user_id: Emby 用户 ID

        Returns:
            用户策略字典
        """
        user_info = self._request('GET', f'/Users/{user_id}')
        if user_info:
            return user_info.get('Policy')
        return None

    def get_active_sessions(self, user_id: Optional[str] = None) -> List[Dict]:
        """
        获取活跃会话（用于账号共享检测）

        Args:
            user_id: Emby 用户 ID（None 表示获取所有会话）

        Returns:
            活跃会话列表
        """
        sessions = self._request('GET', '/Sessions')
        if not sessions:
            return []

        result = []
        for session in sessions:
            # 过滤用户
            if user_id and session.get('UserId') != user_id:
                continue

            # 只返回活跃会话
            if not session.get('NowPlayingItem') and session.get('UserName'):
                continue

            result.append({
                'id': session.get('Id'),
                'user_id': session.get('UserId'),
                'user_name': session.get('UserName'),
                'client': session.get('Client'),
                'device_name': session.get('DeviceName'),
                'device_type': session.get('DeviceType'),
                'remote_addr': session.get('RemoteEndPoint'),
                'now_playing': session.get('NowPlayingItem'),
                'play_state': session.get('PlayState'),
            })

        return result

    def detect_concurrent_streams(self, user_id: str) -> Dict[str, Any]:
        """
        检测用户并发播放情况

        Args:
            user_id: Emby 用户 ID

        Returns:
            检测结果
        """
        sessions = self.get_active_sessions(user_id)

        active_streams = [s for s in sessions if s.get('now_playing')]
        unique_devices = set(s.get('device_name', 'unknown') for s in sessions)

        return {
            'total_sessions': len(sessions),
            'active_streams': len(active_streams),
            'unique_devices': len(unique_devices),
            'devices': list(unique_devices),
            'is_suspicious': len(active_streams) > 1 or len(unique_devices) > 2
        }


def load_emby_server(server_url: str, api_key: str) -> EmbyClient:
    """
    加载 Emby 服务器客户端

    Args:
        server_url: 服务器地址
        api_key: API Key

    Returns:
        EmbyClient 实例
    """
    return EmbyClient(server_url, api_key)


async def create_emby_user(
    server_url: str,
    api_key: str,
    username: str,
    password: str,
    email: Optional[str] = None
) -> Optional[str]:
    """
    在 Emby 服务器上创建新用户

    Args:
        server_url: Emby 服务器地址
        api_key: Emby API Key
        username: 用户名
        password: 密码
        email: 邮箱（可选）

    Returns:
        成功时返回用户 ID，失败时返回 None
    """
    try:
        client = EmbyClient(server_url, api_key)
        result = client.create_user(username, password, email)
        if result.get('success'):
            return result.get('user_id')
        return None
    except Exception as e:
        print(f"创建 Emby 用户失败: {e}")
        return None
