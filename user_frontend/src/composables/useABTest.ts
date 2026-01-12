/**
 * A/B 测试框架
 *
 * 支持功能：
 * - 实验/变体管理
 * - 用户分组（按 user_id 稳定哈希）
 * - 服务端配置同步
 * - 实验结果追踪
 */

import { ref, computed } from 'vue'
import { useAnalytics } from './useAnalytics'

// ==================== 类型定义 ====================

export interface Variant {
  id: string
  name: string
  weight: number // 0-100，变体权重
  config?: Record<string, any>
}

export interface Experiment {
  id: string
  name: string
  description: string
  variants: Variant[]
  isActive: boolean
  startDate?: string
  endDate?: string
  targetAudience?: {
    newUserOnly?: boolean
    minUserDays?: number
    customCondition?: () => boolean
  }
}

export interface ExperimentConfig {
  experiments: Experiment[]
  fallbackVariant?: string
}

// ==================== 哈希函数（用户分组） ====================

/**
 * 生成稳定哈希值，用于用户分组
 * 相同的 user_id 总是得到相同的哈希值
 */
function stableHash(str: string): number {
  let hash = 0
  for (let i = 0; i < str.length; i++) {
    const char = str.charCodeAt(i)
    hash = ((hash << 5) - hash) + char
    hash = hash & hash // 转换为 32 位整数
  }
  return Math.abs(hash)
}

/**
 * 根据哈希值选择变体
 */
function selectVariantByHash(
  userId: string,
  variants: Variant[]
): Variant {
  const hash = stableHash(userId)
  const maxHash = 0xFFFFFFFF // 32 位无符号整数最大值
  const normalizedHash = hash / maxHash // 0-1 之间

  // 计算权重区间
  let cumulativeWeight = 0
  for (const variant of variants) {
    cumulativeWeight += variant.weight
    if (normalizedHash <= cumulativeWeight / 100) {
      return variant
    }
  }

  // 默认返回第一个变体
  return variants[0]
}

// ==================== 状态管理 ====================

const experimentConfigs = ref<Experiment[]>([])
const assignedVariants = ref<Record<string, string>>({})
const isLoading = ref(false)
const analytics = useAnalytics()

// ==================== 初始化和配置 ====================

/**
 * 从服务器加载实验配置
 */
async function loadExperiments(): Promise<void> {
  isLoading.value = true
  try {
    const response = await fetch('/api/analytics/ab-tests')
    if (response.ok) {
      const config: ExperimentConfig = await response.json()
      experimentConfigs.value = config.experiments || []
    } else {
      // 加载失败使用默认配置
      experimentConfigs.value = getDefaultExperiments()
    }
  } catch (error) {
    console.warn('[ABTest] Failed to load experiments, using defaults:', error)
    experimentConfigs.value = getDefaultExperiments()
  } finally {
    isLoading.value = false
  }
}

/**
 * 获取默认实验配置（本地降级）
 */
function getDefaultExperiments(): Experiment[] {
  return [
    {
      id: 'login_page_layout',
      name: '登录页布局测试',
      description: '测试不同登录页布局对转化率的影响',
      isActive: false, // 默认关闭，需要服务端开启
      variants: [
        { id: 'control', name: '对照组（当前设计）', weight: 50 },
        { id: 'variant_a', name: '变体 A（简化版）', weight: 50 },
      ],
    },
    {
      id: 'subscription_card_style',
      name: '订阅卡片样式测试',
      description: '测试不同卡片样式对订阅转化率的影响',
      isActive: false,
      variants: [
        { id: 'control', name: '对照组（当前设计）', weight: 50 },
        { id: 'highlight_best_value', name: '突出性价比标签', weight: 50 },
      ],
    },
  ]
}

/**
 * 获取用户 ID
 */
function getUserId(): string | null {
  const userStore = window.__userStore__
  return userStore?.user?.id?.toString() || null
}

/**
 * 检查用户是否符合实验条件
 */
function checkUserEligibility(experiment: Experiment): boolean {
  if (!experiment.isActive) return false

  const userId = getUserId()
  if (!userId) return false

  const userStore = window.__userStore__

  // 检查目标受众条件
  if (experiment.targetAudience) {
    const { newUserOnly, minUserDays } = experiment.targetAudience

    // 检查是否仅限新用户
    if (newUserOnly) {
      const userCreatedAt = userStore?.user?.created_at
      if (userCreatedAt) {
        const daysSinceCreation = (Date.now() - new Date(userCreatedAt).getTime()) / (1000 * 60 * 60 * 24)
        if (daysSinceCreation > 7) {
          return false // 超过 7 天不算新用户
        }
      }
    }

    // 检查最小用户天数
    if (minUserDays) {
      const userCreatedAt = userStore?.user?.created_at
      if (userCreatedAt) {
        const daysSinceCreation = (Date.now() - new Date(userCreatedAt).getTime()) / (1000 * 60 * 60 * 24)
        if (daysSinceCreation < minUserDays) {
          return false
        }
      }
    }

    // 检查自定义条件
    if (experiment.targetAudience.customCondition) {
      try {
        if (!experiment.targetAudience.customCondition()) {
          return false
        }
      } catch {
        return false
      }
    }
  }

  return true
}

// ==================== 变体分配 ====================

/**
 * 为用户分配实验变体
 */
function assignVariant(experimentId: string): Variant | null {
  const experiment = experimentConfigs.value.find(e => e.id === experimentId)
  if (!experiment) {
    return null
  }

  // 检查用户是否符合条件
  if (!checkUserEligibility(experiment)) {
    return null
  }

  // 检查是否已分配
  if (assignedVariants.value[experimentId]) {
    const variant = experiment.variants.find(v => v.id === assignedVariants.value[experimentId])
    return variant || experiment.variants[0]
  }

  const userId = getUserId()
  if (!userId) {
    return experiment.variants[0] // 未登录用户使用对照组
  }

  // 分配变体
  const selectedVariant = selectVariantByHash(userId, experiment.variants)
  assignedVariants.value[experimentId] = selectedVariant.id

  // 追踪分配事件
  analytics.track('ab_test_assignment', {
    experimentId,
    variantId: selectedVariant.id,
    experimentName: experiment.name,
    variantName: selectedVariant.name,
  })

  // 持久化存储
  saveAssignedVariants()

  return selectedVariant
}

/**
 * 从 localStorage 恢复已分配的变体
 */
function loadAssignedVariants(): void {
  try {
    const stored = localStorage.getItem('ab_test_variants')
    if (stored) {
      assignedVariants.value = JSON.parse(stored)
    }
  } catch {
    // 忽略错误
  }
}

/**
 * 保存已分配的变体到 localStorage
 */
function saveAssignedVariants(): void {
  try {
    localStorage.setItem('ab_test_variants', JSON.stringify(assignedVariants.value))
  } catch {
    // 忽略错误
  }
}

// ==================== 组合式函数 ====================

let initialized = false

export function useABTest() {
  if (!initialized) {
    loadAssignedVariants()
    loadExperiments()
    initialized = true
  }

  /**
   * 获取实验的变体
   */
  const getVariant = (experimentId: string): Variant | null => {
    return assignVariant(experimentId)
  }

  /**
   * 检查是否是某个变体
   */
  const isVariant = (experimentId: string, variantId: string): boolean => {
    const variant = getVariant(experimentId)
    return variant?.id === variantId
  }

  /**
   * 获取变体配置
   */
  const getVariantConfig = <T = Record<string, any>>(experimentId: string): T | null => {
    const variant = getVariant(experimentId)
    return (variant?.config as T) || null
  }

  /**
   * 强制设置变体（用于测试）
   */
  const forceVariant = (experimentId: string, variantId: string): void => {
    const experiment = experimentConfigs.value.find(e => e.id === experimentId)
    if (experiment) {
      const variant = experiment.variants.find(v => v.id === variantId)
      if (variant) {
        assignedVariants.value[experimentId] = variantId
        saveAssignedVariants()
      }
    }
  }

  /**
   * 重置所有变体分配
   */
  const resetVariants = (): void => {
    assignedVariants.value = {}
    localStorage.removeItem('ab_test_variants')
  }

  /**
   * 重新加载实验配置
   */
  const reloadExperiments = (): Promise<void> => {
    return loadExperiments()
  }

  /**
   * 获取所有活跃实验
   */
  const activeExperiments = computed(() => {
    return experimentConfigs.value.filter(e => e.isActive)
  })

  /**
   * 追踪 A/B 测试目标事件
   */
  const trackGoal = (goalName: string, value?: number, properties?: Record<string, any>): void => {
    analytics.track('ab_test_goal', {
      goal: goalName,
      value,
      ...properties,
      // 自动添加当前所有实验分配信息
      experiments: assignedVariants.value,
    })
  }

  return {
    // 状态
    isLoading,
    experiments: experimentConfigs,
    activeExperiments,
    assignedVariants,

    // 核心方法
    getVariant,
    isVariant,
    getVariantConfig,
    forceVariant,
    resetVariants,
    reloadExperiments,
    trackGoal,
  }
}

// ==================== 预定义实验辅助函数 ====================

/**
 * 订阅页面 - 卡片样式实验
 */
export function useSubscriptionCardTest() {
  const abTest = useABTest()
  const variant = computed(() => abTest.getVariant('subscription_card_style'))

  const showBestValueBadge = computed(() => {
    return variant.value?.id === 'highlight_best_value'
  })

  const getCardConfig = (planIndex: number) => {
    // 根据变体返回不同的卡片配置
    if (showBestValueBadge.value && planIndex === 1) {
      return {
        highlight: true,
        badgeText: '最受欢迎',
        extraPadding: true,
      }
    }
    return {
      highlight: false,
      badgeText: undefined,
      extraPadding: false,
    }
  }

  return {
    variant,
    showBestValueBadge,
    getCardConfig,
  }
}

/**
 * 登录页面 - 布局实验
 */
export function useLoginPageTest() {
  const abTest = useABTest()
  const variant = computed(() => abTest.getVariant('login_page_layout'))

  const showSimplifiedVersion = computed(() => {
    return variant.value?.id === 'variant_a'
  })

  return {
    variant,
    showSimplifiedVersion,
  }
}

// ==================== 全局类型声明 ====================

declare global {
  interface Window {
    __userStore__?: any
  }
}
