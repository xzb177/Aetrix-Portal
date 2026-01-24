/**
 * Feature Flags 配置
 *
 * 用于控制新功能的启用/禁用，支持：
 * 1. 默认值配置
 * 2. localStorage 覆盖（用于测试）
 * 3. URL 参数覆盖（?ff=UI_V2:true,STICKY_CTA:false）
 *
 * 使用方式：
 * import { featureFlags } from '@/config/featureFlags'
 * if (featureFlags.UI_V2) { ... }
 */

export interface FeatureFlagConfig {
  /** Neo-Noir 2.0 新UI样式/组件 */
  UI_V2: boolean
  /** 底部固定CTA条 */
  STICKY_CTA: boolean
  /** 邀请增长组件 */
  GROWTH_INVITE: boolean
  /** 个人中心彩蛋：长按 Holo-ID 卡片进入调试模式 */
  PROFILE_EASTER_EGG: boolean
  /** 舰桥个人中心新UI：Aetrix Bridge Profile */
  PROFILE_BRIDGE: boolean
  /** 线路配置功能：启用后台线路管理分流 */
  ROUTE_CONFIG: boolean
}

// 默认配置
const DEFAULT_FLAGS: FeatureFlagConfig = {
  UI_V2: true,
  STICKY_CTA: false,
  GROWTH_INVITE: false,
  PROFILE_EASTER_EGG: true,
  PROFILE_BRIDGE: true,
  ROUTE_CONFIG: false, // 默认关闭，需要后台配置完成后再开启
}

// 从 localStorage 读取覆盖配置
function getLocalStorageFlags(): Partial<FeatureFlagConfig> {
  if (typeof window === 'undefined') return {}

  try {
    const stored = localStorage.getItem('feature_flags')
    if (!stored) return {}

    return JSON.parse(stored)
  } catch {
    return {}
  }
}

// 从 URL 参数读取覆盖配置（格式：?ff=UI_V2:true,STICKY_CTA:false）
function getUrlParamFlags(): Partial<FeatureFlagConfig> {
  if (typeof window === 'undefined') return {}

  try {
    const params = new URLSearchParams(window.location.search)
    const ffParam = params.get('ff')
    if (!ffParam) return {}

    const result: Partial<FeatureFlagConfig> = {}
    ffParam.split(',').forEach((pair) => {
      const [key, value] = pair.split(':')
      if (value === 'true' || value === 'false') {
        result[key.trim() as keyof FeatureFlagConfig] = value === 'true'
      }
    })

    return result
  } catch {
    return {}
  }
}

// 合并配置
function mergeFlags(): FeatureFlagConfig {
  const localOverrides = getLocalStorageFlags()
  const urlOverrides = getUrlParamFlags()

  return {
    ...DEFAULT_FLAGS,
    ...localOverrides,
    ...urlOverrides,
  }
}

// 导出合并后的配置
let _flags: FeatureFlagConfig | null = null

export const featureFlags: FeatureFlagConfig = new Proxy({} as FeatureFlagConfig, {
  get(target, prop: keyof FeatureFlagConfig) {
    if (!_flags) {
      _flags = mergeFlags()
    }
    return _flags[prop]
  },
})

// 重新加载配置（用于动态切换）
export function reloadFeatureFlags(): FeatureFlagConfig {
  _flags = mergeFlags()
  return _flags
}

// 设置 flag（用于测试面板）
export function setFeatureFlag<K extends keyof FeatureFlagConfig>(
  key: K,
  value: FeatureFlagConfig[K]
): void {
  if (typeof window === 'undefined') return

  const current = getLocalStorageFlags()
  const updated = { ...current, [key]: value }

  localStorage.setItem('feature_flags', JSON.stringify(updated))
  _flags = mergeFlags()
}

// 重置所有 flags 到默认值
export function resetFeatureFlags(): void {
  if (typeof window === 'undefined') return

  localStorage.removeItem('feature_flags')
  _flags = mergeFlags()
}

// 获取当前配置（用于调试）
export function getFeatureFlagsInfo(): {
  current: FeatureFlagConfig
  defaults: FeatureFlagConfig
  overrides: Partial<FeatureFlagConfig>
} {
  const localOverrides = getLocalStorageFlags()

  return {
    current: _flags || mergeFlags(),
    defaults: DEFAULT_FLAGS,
    overrides: localOverrides,
  }
}
