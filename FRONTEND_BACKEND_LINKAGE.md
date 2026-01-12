# RoyalBot Portal - 前后台联动实现文档

## 概述

基于 EmbyController 的设计模式，实现了管理后台与用户前台的实时联动功能。管理员在后台的操作会通过 WebSocket 实时推送到用户前台，用户可以即时收到通知。

## 数据流架构

```
管理员操作 → 后台 API → notify_admin_event() → NotificationService
            → 站内信数据库 + WebSocket 推送 → 用户前台实时更新
```

## 后端实现

### 1. 多渠道通知服务 (`backend/notifications.py`)

- **InAppChannel**: 站内消息（默认）
- **EmailChannel**: 邮件通知（可选配置）
- **TelegramChannel**: Telegram 通知（可选配置）

### 2. 事件类型 (`AdminEvent`)

| 事件类型 | 说明 |
|---------|------|
| `exchange_code.generated` | 兑换码生成 |
| `ticket.created/replied/closed` | 工单状态变更 |
| `announcement.published/updated` | 公告发布/更新 |
| `subscription.manual/extended` | 订阅授予/延长 |
| `media_seek.approved/rejected/completed` | 求片状态更新 |
| `system.maintenance` | 系统维护通知 |

### 3. API 端点

#### 用户端 API (`/api/user/*`)
- `GET /messages` - 获取站内消息列表
- `GET /messages/unread-count` - 获取未读消息数
- `POST /messages/{id}/read` - 标记消息为已读
- `POST /messages/read-all` - 标记所有消息为已读
- `GET /tickets` - 获取我的工单
- `POST /tickets` - 创建工单
- `POST /tickets/{id}/messages` - 回复工单
- `GET /announcements` - 获取系统公告
- `POST /media-seek` - 提交求片请求

#### 管理端 API (`/api/admin/*`)
- `POST /announcements` - 创建公告（广播所有用户）
- `PUT /tickets/{id}` - 更新工单状态（通知用户）
- `POST /tickets/{id}/reply` - 回复工单（通知用户）
- `PUT /media-seek/{id}` - 更新求片状态（通知用户）
- `POST /subscriptions/grant` - 授予订阅（通知用户）
- `POST /messages/send` - 发送消息给指定用户
- `POST /messages/broadcast` - 广播消息给所有用户

### 4. WebSocket 端点

- `WS /ws/{user_id}` - 用户 WebSocket 连接
- 客户端发送 `{"action": "subscribe", "channels": [...]}` 订阅频道
- 服务端推送通知消息：
  ```json
  {
    "type": "station.ticket",
    "title": "工单有新回复",
    "message": "管理员回复了您的工单",
    "data": {"ticket_id": 123},
    "timestamp": "2026-01-06T12:00:00"
  }
  ```

## 前端实现

### 1. WebSocket 客户端 (`user_frontend/src/composables/useWebSocket.ts`)

```typescript
// 使用示例
const {
  connectionState,
  unreadCount,
  notifications,
  connect,
  disconnect,
  onMessage
} = useWebSocket()

// 订阅特定类型的消息
onMessage('station.ticket', (msg) => {
  console.log('收到工单消息:', msg)
})
```

### 2. 通知中心组件 (`user_frontend/src/components/NotificationCenter.vue`)

- 显示未读消息数量徽章
- 下拉面板显示最新通知
- 点击通知跳转到相关页面
- 支持标记已读、清空通知

### 3. 消息列表页面 (`user_frontend/src/views/MessagesView.vue`)

- 显示所有站内消息
- 按类型筛选（系统/工单/公告/订阅等）
- 搜索功能
- 批量标记已读

## 联动场景示例

### 场景 1: 管理员发布公告
1. 管理员在后台创建公告
2. `notify_all_users()` 广播通知
3. 所有在线用户的 WebSocket 收到推送
4. 用户前台通知中心显示新公告

### 场景 2: 管理员回复工单
1. 用户提交工单
2. 管理员在后台回复
3. `notify_admin_event(TICKET_REPLIED)` 发送通知
4. 用户 WebSocket 收到推送
5. 用户点击通知跳转到工单详情

### 场景 3: 管理员授予订阅
1. 管理员手动授予用户 VIP
2. `notify_admin_event(SUBSCRIPTION_MANUAL)` 发送通知
3. 用户收到站内消息：「恭喜获得订阅」

### 场景 4: 管理员处理求片
1. 用户提交求片请求
2. 管理员标记为"已批准"
3. `notify_admin_event(MEDIA_SEEK_APPROVED)` 发送通知
4. 用户收到求片状态更新通知

## 数据库表

### station_messages
站内消息存储表，用于持久化通知。

| 字段 | 类型 | 说明 |
|-----|------|-----|
| id | Integer | 主键 |
| from_user_id | Integer | 发送者（管理员ID），系统消息为空 |
| to_user_id | Integer | 接收用户ID |
| title | String | 消息标题 |
| content | Text | 消息内容 |
| message_type | String | 消息类型 |
| related_id | Integer | 关联ID（工单ID等） |
| is_read | Boolean | 是否已读 |
| read_at | DateTime | 已读时间 |
| created_at | DateTime | 创建时间 |

## 待完成功能

- [ ] JWT 认证实现（目前使用临时 token）
- [ ] 邮件发送功能（EmailChannel）
- [ ] Telegram 发送功能（TelegramChannel）
- [ ] 兑换码模型和 API 实现
- [ ] 管理员 WebSocket 通知（新工单提醒）
