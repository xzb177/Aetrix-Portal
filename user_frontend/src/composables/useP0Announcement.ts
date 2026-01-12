/**
 * P0 公告 Composable
 *
 * 业务规则：
 * 1) 仅在首页触发 P0 公告弹层
 * 2) P0 为"必须看"：用户必须点击【我已知晓】才能关闭
 * 3) 弹过一次后不重复弹：按 announcementId 记录已读
 * 4) 公告过期不弹：支持 startAt/endAt（从 content 元数据读取）
 * 5) 弹层关闭后：首页仍展示一条【公告摘要条】
 */

import { ref, computed } from 'vue'
import { announcementApi } from '@/api'

// 公告数据结构
export interface Announcement {
  id: number
  title: string
  content: string
  type: 'system' | 'activity' | 'urgent'
  is_active: boolean
  created_at: string
  updated_at: string
}

// 公告元数据（从 content JSON 中解析）
export interface AnnouncementMetadata {
  startAt?: string  // ISO 8601 格式
  endAt?: string    // ISO 8601 格式
  level?: 'P0' | 'P1' | 'P2'  // 优先级
  displayType?: 'modal' | 'banner'  // 展示方式
}

// localStorage key 前缀
const P0_ACK_PREFIX = 'p0_ack_'

// 解析 content，支持纯文本或 JSON 格式
function parseContent(content: string): { text: string; metadata: AnnouncementMetadata } {
  try {
    // 尝试解析为 JSON
    const parsed = JSON.parse(content)
    if (parsed.text && typeof parsed.text === 'string') {
      return {
        text: parsed.text,
        metadata: parsed.metadata || {}
      }
    }
  } catch {
    // 不是 JSON，当作纯文本处理
  }
  return { text: content, metadata: {} }
}

// 检查公告是否在有效期内
function isActive(metadata: AnnouncementMetadata): boolean {
  const now = Date.now()

  if (metadata.startAt) {
    const startTime = new Date(metadata.startAt).getTime()
    if (now < startTime) return false
  }

  if (metadata.endAt) {
    const endTime = new Date(metadata.endAt).getTime()
    if (now > endTime) return false
  }

  return true
}

// 检查公告是否已读
function isAcked(announcementId: number): boolean {
  return localStorage.getItem(`${P0_ACK_PREFIX}${announcementId}`) === '1'
}

// 标记公告为已读
function ackP0(announcementId: number): void {
  localStorage.setItem(`${P0_ACK_PREFIX}${announcementId}`, '1')
}

// 清除已读标记（用于测试）
function clearAck(announcementId: number): void {
  localStorage.removeItem(`${P0_ACK_PREFIX}${announcementId}`)
}

// 筛选 P0 公告
// 规则：
// - type === 'urgent' 或 metadata.level === 'P0'
// - 在有效期内
// - 未被 ack
// - 按 updated_at 排序取最新一条
export function useP0Announcement() {
  const loading = ref(false)
  const announcements = ref<Announcement[]>([])
  const p0Announcement = ref<Announcement | null>(null)
  const p0Content = ref('')
  const showP0Modal = ref(false)
  const showSummaryBar = ref(false)

  // 获取公告列表
  const fetchAnnouncements = async () => {
    loading.value = true
    try {
      const res = await announcementApi.getAnnouncements({ limit: 20 })
      announcements.value = res.data || []
    } catch (error) {
      console.error('获取公告失败:', error)
      announcements.value = []
    } finally {
      loading.value = false
    }
  }

  // 筛选 P0 公告
  const pickP0Announcement = (): Announcement | null => {
    const now = Date.now()

    // 筛选符合条件的公告
    const candidates = announcements.value
      .map(announcement => {
        const { metadata } = parseContent(announcement.content)
        return { announcement, metadata }
      })
      .filter(({ announcement, metadata }) => {
        // 必须是激活状态
        if (!announcement.is_active) return false

        // 判断是否为 P0：type === 'urgent' 或 metadata.level === 'P0'
        const isP0 = announcement.type === 'urgent' || metadata.level === 'P0'
        if (!isP0) return false

        // 检查有效期
        if (!isActive(metadata)) return false

        // 检查是否已读
        if (isAcked(announcement.id)) return false

        return true
      })
      .sort((a, b) => {
        // 按 updated_at 降序排序
        return new Date(b.announcement.updated_at).getTime() - new Date(a.announcement.updated_at).getTime()
      })

    // 返回最新一条
    return candidates.length > 0 ? candidates[0].announcement : null
  }

  // 检查并显示 P0 公告
  const checkAndShowP0 = () => {
    const p0 = pickP0Announcement()
    if (p0) {
      p0Announcement.value = p0
      const { text } = parseContent(p0.content)
      p0Content.value = text
      showP0Modal.value = true
    }
  }

  // 打开 P0 弹窗（手动触发，如从摘要条点击）
  const openP0Modal = (announcement: Announcement) => {
    p0Announcement.value = announcement
    const { text } = parseContent(announcement.content)
    p0Content.value = text
    showP0Modal.value = true
  }

  // 关闭 P0 弹窗并标记已读
  const closeP0Modal = () => {
    if (p0Announcement.value) {
      ackP0(p0Announcement.value.id)
    }
    showP0Modal.value = false
    showSummaryBar.value = true
  }

  // 仅关闭弹窗（不标记已读，用于非 P0 公告查看）
  const dismissModal = () => {
    showP0Modal.value = false
  }

  // 获取已读的 P0 公告（用于显示摘要条）
  const getAckedP0Announcements = (): Announcement[] => {
    return announcements.value
      .filter(announcement => {
        if (!announcement.is_active) return false

        const { metadata } = parseContent(announcement.content)
        const isP0 = announcement.type === 'urgent' || metadata.level === 'P0'

        return isP0 && isActive(metadata) && isAcked(announcement.id)
      })
      .sort((a, b) => {
        return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
      })
  }

  // 初始化（在首页 onMounted 调用）
  const init = async () => {
    await fetchAnnouncements()

    // 检查是否有已读的 P0 公告，用于显示摘要条
    const ackedP0s = getAckedP0Announcements()
    if (ackedP0s.length > 0) {
      showSummaryBar.value = true
      p0Announcement.value = ackedP0s[0]
      const { text } = parseContent(ackedP0s[0].content)
      p0Content.value = text
    }

    // 检查并显示未读的 P0 公告
    checkAndShowP0()
  }

  return {
    // 状态
    loading,
    announcements,
    p0Announcement,
    p0Content,
    showP0Modal,
    showSummaryBar,

    // 方法
    fetchAnnouncements,
    pickP0Announcement,
    checkAndShowP0,
    openP0Modal,
    closeP0Modal,
    dismissModal,
    getAckedP0Announcements,
    init,

    // 工具函数（导出供外部使用）
    parseContent,
    isActive,
    ackP0,
    clearAck
  }
}

// 全局单例（确保整个应用只有一个 P0 弹窗实例）
let globalInstance: ReturnType<typeof useP0Announcement> | null = null

export function getP0AnnouncementInstance() {
  if (!globalInstance) {
    globalInstance = useP0Announcement()
  }
  return globalInstance
}
