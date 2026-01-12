/**
 * WebSocket 客户端 Composable
 * 实现前后台联动 - 接收管理员操作的通知
 */
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { useUserStore } from '@/stores/user'

// WebSocket 连接状态
export type WSConnectionState = 'connecting' | 'connected' | 'disconnected' | 'error'

// WebSocket 消息类型
export interface WSMessage {
  type: string
  title: string
  message: string
  data?: Record<string, any>
  timestamp: string
}

// 通知事件
export interface NotificationEvent {
  type: string
  title: string
  message: string
  data?: Record<string, any>
  read: boolean
  createdAt: Date
}

// 全局 WebSocket 实例
let ws: WebSocket | null = null
let reconnectTimer: ReturnType<typeof setTimeout> | null = null
let heartbeatTimer: ReturnType<typeof setInterval> | null = null
let reconnectAttempts = 0
const MAX_RECONNECT_ATTEMPTS = 5

// 全局消息处理器列表
const messageHandlers: Map<string, Set<(msg: WSMessage) => void>> = new Map()

// 全局状态
const connectionState = ref<WSConnectionState>('disconnected')
const unreadCount = ref(0)
const notifications = ref<NotificationEvent[]>([])

/**
 * WebSocket 客户端 Hook
 */
export function useWebSocket() {
  const userStore = useUserStore()
  const userId = ref<number | null>(null)

  /**
   * 获取 WebSocket URL
   */
  function getWsUrl(): string {
    const apiBaseUrl = import.meta.env.VITE_API_URL || 'http://localhost:8001'
    const wsProtocol = apiBaseUrl.startsWith('https') ? 'wss://' : 'ws://'
    const wsHost = apiBaseUrl.replace(/^https?:\/\//, '').replace(/\/$/, '')

    // 使用用户 ID 作为路径参数
    const uid = userId.value || userStore.user?.id
    if (!uid) {
      throw new Error('用户未登录')
    }

    return `${wsProtocol}${wsHost}/ws/${uid}`
  }

  /**
   * 连接 WebSocket
   */
  function connect() {
    if (ws && ws.readyState === WebSocket.OPEN) {
      return
    }

    if (!userStore.isLoggedIn || !userStore.user?.id) {
      return
    }

    userId.value = userStore.user.id
    connectionState.value = 'connecting'

    try {
      ws = new WebSocket(getWsUrl())

      ws.onopen = () => {
        console.log('[WebSocket] 连接成功')
        connectionState.value = 'connected'
        reconnectAttempts = 0

        // 订阅默认频道
        subscribe(['announcements', 'tickets', 'subscriptions'])

        // 启动心跳
        startHeartbeat()
      }

      ws.onmessage = (event) => {
        try {
          const data: WSMessage = JSON.parse(event.data)
          handleMessage(data)
        } catch (err) {
          console.error('[WebSocket] 解析消息失败:', err)
        }
      }

      ws.onclose = (event) => {
        console.log('[WebSocket] 连接关闭:', event.code, event.reason)
        connectionState.value = 'disconnected'
        stopHeartbeat()

        // 尝试重连
        if (reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
          reconnect()
        }
      }

      ws.onerror = (error) => {
        console.error('[WebSocket] 连接错误:', error)
        connectionState.value = 'error'
      }
    } catch (error) {
      console.error('[WebSocket] 创建连接失败:', error)
      connectionState.value = 'error'
      reconnect()
    }
  }

  /**
   * 断开连接
   */
  function disconnect() {
    if (ws) {
      ws.close()
      ws = null
    }
    stopHeartbeat()
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    connectionState.value = 'disconnected'
  }

  /**
   * 重连
   */
  function reconnect() {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
    }

    reconnectAttempts++
    const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), 30000)

    console.log(`[WebSocket] ${delay}ms 后尝试重连 (${reconnectAttempts}/${MAX_RECONNECT_ATTEMPTS})`)

    reconnectTimer = setTimeout(() => {
      if (userStore.isLoggedIn) {
        connect()
      }
    }, delay)
  }

  /**
   * 发送消息
   */
  function send(data: Record<string, any>) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(data))
    } else {
      console.warn('[WebSocket] 连接未建立，无法发送消息')
    }
  }

  /**
   * 订阅频道
   */
  function subscribe(channels: string[]) {
    send({
      action: 'subscribe',
      channels
    })
  }

  /**
   * 取消订阅频道
   */
  function unsubscribe(channels: string[]) {
    send({
      action: 'unsubscribe',
      channels
    })
  }

  /**
   * 处理收到的消息
   */
  function handleMessage(data: WSMessage) {
    // 处理连接确认
    if (data.type === 'connection.connected') {
      console.log('[WebSocket] 连接已确认，用户ID:', data.data?.user_id)
      return
    }

    // 处理订阅确认
    if (data.type === 'subscription.success') {
      console.log('[WebSocket] 订阅成功:', data.data?.channels)
      return
    }

    // 处理未读数更新
    if (data.type === 'station.unread_count') {
      unreadCount.value = data.data?.unread_count || 0
      return
    }

    // 处理心跳响应
    if (data.type === 'pong') {
      return
    }

    // 处理站内消息通知
    if (data.type.startsWith('station.')) {
      unreadCount.value++
      addNotification({
        type: data.type,
        title: data.title,
        message: data.message,
        data: data.data,
        read: false,
        createdAt: new Date(data.timestamp)
      })
    }

    // 调用注册的处理器
    const handlers = messageHandlers.get(data.type)
    if (handlers) {
      handlers.forEach(handler => handler(data))
    }

    // 调用通配符处理器
    const wildcardHandlers = messageHandlers.get('*')
    if (wildcardHandlers) {
      wildcardHandlers.forEach(handler => handler(data))
    }
  }

  /**
   * 启动心跳
   */
  function startHeartbeat() {
    stopHeartbeat()
    heartbeatTimer = setInterval(() => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        send({ action: 'ping' })
      }
    }, 30000) // 30秒心跳
  }

  /**
   * 停止心跳
   */
  function stopHeartbeat() {
    if (heartbeatTimer) {
      clearInterval(heartbeatTimer)
      heartbeatTimer = null
    }
  }

  /**
   * 添加消息处理器
   */
  function onMessage(type: string, handler: (msg: WSMessage) => void) {
    if (!messageHandlers.has(type)) {
      messageHandlers.set(type, new Set())
    }
    messageHandlers.get(type)!.add(handler)

    // 返回取消订阅函数
    return () => {
      const handlers = messageHandlers.get(type)
      if (handlers) {
        handlers.delete(handler)
      }
    }
  }

  /**
   * 添加通知到列表
   */
  function addNotification(notification: NotificationEvent) {
    notifications.value.unshift(notification)

    // 限制通知数量
    if (notifications.value.length > 50) {
      notifications.value = notifications.value.slice(0, 50)
    }
  }

  /**
   * 标记通知为已读
   */
  function markAsRead(notification: NotificationEvent) {
    notification.read = true
    if (notification.read) {
      unreadCount.value = Math.max(0, unreadCount.value - 1)
    }
  }

  /**
   * 清除所有通知
   */
  function clearNotifications() {
    notifications.value = []
    unreadCount.value = 0
  }

  // 监听登录状态变化
  watch(() => userStore.isLoggedIn, (isLoggedIn) => {
    if (isLoggedIn) {
      connect()
    } else {
      disconnect()
    }
  })

  return {
    // 状态
    connectionState,
    unreadCount,
    notifications,

    // 方法
    connect,
    disconnect,
    send,
    subscribe,
    unsubscribe,
    onMessage,
    markAsRead,
    clearNotifications
  }
}

/**
 * 全局 WebSocket 管理器
 * 用于在 App.vue 中初始化
 */
export function useWebSocketManager() {
  const { connect, disconnect } = useWebSocket()

  onMounted(() => {
    connect()
  })

  onUnmounted(() => {
    disconnect()
  })
}
