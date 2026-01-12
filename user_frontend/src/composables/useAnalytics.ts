/**
 * 埋点系统 - 用户行为追踪
 *
 * 事件类型定义：
 * - page_view: 页面浏览
 * - click: 点击事件
 * - form_submit: 表单提交
 * - conversion: 转化事件（订阅/充值等）
 * - error: 错误事件
 * - custom: 自定义事件
 */

import { ref } from 'vue'

// ==================== 类型定义 ====================

export type EventType =
  | 'page_view'
  | 'click'
  | 'form_submit'
  | 'conversion'
  | 'error'
  | 'custom'

export interface AnalyticsEvent {
  id: string
  type: EventType
  name: string
  properties?: Record<string, any>
  timestamp: number
  userId?: number
  sessionId: string
  page?: string
  referrer?: string
  userAgent?: string
}

export interface ConversionEvent extends AnalyticsEvent {
  type: 'conversion'
  conversionType: 'subscription' | 'recharge' | 'register' | 'trial'
  value?: number
  currency?: string
}

// ==================== 会话管理 ====================

let sessionId: string
let sessionStartTime: number

function initSession() {
  const stored = sessionStorage.getItem('analytics_session')
  if (stored) {
    const data = JSON.parse(stored)
    // 会话超时时间：30 分钟
    if (Date.now() - data.timestamp < 30 * 60 * 1000) {
      sessionId = data.sessionId
      sessionStartTime = data.timestamp
      return
    }
  }
  sessionId = generateId()
  sessionStartTime = Date.now()
  saveSession()
}

function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).substring(2, 11)}`
}

function saveSession() {
  sessionStorage.setItem('analytics_session', JSON.stringify({
    sessionId,
    timestamp: Date.now(),
  }))
}

// ==================== 事件队列 ====================

const eventQueue = ref<AnalyticsEvent[]>([])
const isQueueProcessing = ref(false)
const MAX_QUEUE_SIZE = 50
const FLUSH_INTERVAL = 10000 // 10 秒

// ==================== 工具函数 ====================

function getPagePath(): string {
  return window.location.pathname
}

function getReferrer(): string {
  return document.referrer || 'direct'
}

function getUserAgent(): string {
  return navigator.userAgent
}

function getUserId(): number | undefined {
  const userStore = window.__userStore__
  return userStore?.user?.id
}

// ==================== 核心追踪函数 ====================

/**
 * 追踪事件
 */
function track(
  name: string,
  properties: Record<string, any> = {},
  type: EventType = 'custom'
): string {
  const eventId = generateId()

  const event: AnalyticsEvent = {
    id: eventId,
    type,
    name,
    properties,
    timestamp: Date.now(),
    userId: getUserId(),
    sessionId,
    page: getPagePath(),
    referrer: getReferrer(),
    userAgent: getUserAgent(),
  }

  eventQueue.value.push(event)

  // 队列达到最大值时立即发送
  if (eventQueue.value.length >= MAX_QUEUE_SIZE) {
    flushEvents()
  }

  // 开发环境打印日志
  if (import.meta.env.DEV) {
    console.log('[Analytics]', event)
  }

  return eventId
}

/**
 * 追踪页面浏览
 */
function trackPageView(page?: string, properties: Record<string, any> = {}) {
  track('page_view', {
    page: page || getPagePath(),
    title: document.title,
    ...properties,
  }, 'page_view')
}

/**
 * 追踪点击事件
 */
function trackClick(element: string, properties: Record<string, any> = {}) {
  track('click', {
    element,
    ...properties,
  }, 'click')
}

/**
 * 追踪表单提交
 */
function trackFormSubmit(formName: string, properties: Record<string, any> = {}) {
  track('form_submit', {
    form: formName,
    ...properties,
  }, 'form_submit')
}

/**
 * 追踪转化事件
 */
function trackConversion(
  conversionType: ConversionEvent['conversionType'],
  value?: number,
  properties: Record<string, any> = {}
): string {
  return track('conversion', {
    conversionType,
    value,
    currency: 'CNY',
    ...properties,
  }, 'conversion')
}

/**
 * 追踪错误事件
 */
function trackError(error: Error | string, context: Record<string, any> = {}) {
  const errorMessage = typeof error === 'string' ? error : error.message
  const errorStack = typeof error === 'string' ? undefined : error.stack

  track('error', {
    message: errorMessage,
    stack: errorStack,
    ...context,
  }, 'error')
}

// ==================== 事件发送 ====================

/**
 * 发送事件到服务器
 */
async function flushEvents(): Promise<boolean> {
  if (isQueueProcessing.value || eventQueue.value.length === 0) {
    return false
  }

  isQueueProcessing.value = true

  const eventsToSend = [...eventQueue.value]
  eventQueue.value = []

  try {
    const response = await fetch('/api/analytics/events', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        events: eventsToSend,
        sessionId,
        timestamp: Date.now(),
      }),
    })

    if (!response.ok) {
      throw new Error(`Analytics flush failed: ${response.status}`)
    }

    if (import.meta.env.DEV) {
      console.log('[Analytics] Flushed', eventsToSend.length, 'events')
    }

    return true
  } catch (error) {
    // 发送失败，将事件放回队列
    eventQueue.value = [...eventsToSend, ...eventQueue.value]
    console.error('[Analytics] Flush error:', error)
    return false
  } finally {
    isQueueProcessing.value = false
  }
}

/**
 * 定时刷新队列
 */
function startFlushTimer() {
  setInterval(flushEvents, FLUSH_INTERVAL)
}

// ==================== 预定义事件 ====================

/**
 * 首页事件
 */
export const homeEvents = {
  view: () => trackPageView('/home'),
  clickEnter: (accountType: string) => trackClick('enter_emby', { accountType }),
  clickCopyAll: (accountType: string) => trackClick('copy_all_account', { accountType }),
  toggleAccountDetails: (expanded: boolean) => trackClick('toggle_account_details', { expanded }),
  openGuide: () => trackClick('open_connection_guide'),
}

/**
 * 登录页事件
 */
export const loginEvents = {
  view: () => trackPageView('/login'),
  clickTelegramLogin: () => trackClick('telegram_login'),
  clickPasswordLogin: () => trackClick('password_login'),
  submitLoginForm: (method: string) => trackFormSubmit('login', { method }),
  loginSuccess: (method: string) => trackConversion('register', 0, { method }),
  loginFail: (method: string, error: string) => trackError(`Login failed: ${error}`, { method }),
}

/**
 * 订阅页事件
 */
export const subscriptionEvents = {
  view: () => trackPageView('/subscription'),
  clickPlan: (planId: string, planName: string) => trackClick('select_plan', { planId, planName }),
  toggleFAQ: (questionId: string) => trackClick('toggle_faq', { questionId }),
  openPayment: (planId: string, amount: number) => trackClick('open_payment', { planId, amount }),
  subscriptionSuccess: (planId: string, amount: number) =>
    trackConversion('subscription', amount, { planId }),
}

/**
 * 充值页事件
 */
export const rechargeEvents = {
  view: () => trackPageView('/recharge'),
  selectAmount: (amount: number, tag?: string) => trackClick('select_amount', { amount, tag }),
  openPayment: (amount: number) => trackClick('open_recharge_payment', { amount }),
  rechargeSuccess: (amount: number) => trackConversion('recharge', amount),
}

/**
 * 账号相关事件
 */
export const accountEvents = {
  view: () => trackPageView('/profile'),
  claimAccount: (accountId: string) => trackClick('claim_account', { accountId }),
  extendAccount: (accountId: string) => trackClick('extend_account', { accountId }),
  renewAccount: (accountId: string) => trackClick('renew_account', { accountId }),
}

// ==================== 组合式函数 ====================

let initialized = false

export function useAnalytics() {
  if (!initialized) {
    initSession()
    startFlushTimer()
    initialized = true

    // 页面卸载时发送剩余事件
    window.addEventListener('beforeunload', () => {
      if (eventQueue.value.length > 0) {
        navigator.sendBeacon('/api/analytics/events', JSON.stringify({
          events: eventQueue.value,
          sessionId,
          timestamp: Date.now(),
        }))
      }
    })

    // 监听页面可见性变化，页面重新可见时刷新
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden && eventQueue.value.length > 0) {
        flushEvents()
      }
    })
  }

  return {
    // 基础方法
    track,
    trackPageView,
    trackClick,
    trackFormSubmit,
    trackConversion,
    trackError,
    flushEvents,

    // 预定义事件
    home: homeEvents,
    login: loginEvents,
    subscription: subscriptionEvents,
    recharge: rechargeEvents,
    account: accountEvents,

    // 状态
    eventQueue,
    isQueueProcessing,
    sessionId,
  }
}

// ==================== 全局初始化 ====================

// 在应用启动时自动初始化
declare global {
  interface Window {
    __userStore__?: any
  }
}
