/**
 * Feature Flags Composable
 *
 * Vue 3 Composition API 友好封装
 *
 * @example
 * const { UI_V2, STICKY_CTA, setFlag, reset } = useFeatureFlags()
 */
import { ref, computed, type Ref } from 'vue'
import {
  featureFlags,
  setFeatureFlag as _setFlag,
  resetFeatureFlags as _resetFlags,
  reloadFeatureFlags,
  getFeatureFlagsInfo,
  type FeatureFlagConfig,
} from '@/config/featureFlags'

// 响应式状态
const flags = ref<FeatureFlagConfig>(featureFlags) as Ref<FeatureFlagConfig>

export function useFeatureFlags() {
  // 各个 flag 的 computed 引用
  const UI_V2 = computed(() => flags.value.UI_V2)
  const STICKY_CTA = computed(() => flags.value.STICKY_CTA)
  const GROWTH_INVITE = computed(() => flags.value.GROWTH_INVITE)
  const PROFILE_EASTER_EGG = computed(() => flags.value.PROFILE_EASTER_EGG)
  const PROFILE_BRIDGE = computed(() => flags.value.PROFILE_BRIDGE)
  const ROUTE_CONFIG = computed(() => flags.value.ROUTE_CONFIG)

  // 设置单个 flag
  function setFlag<K extends keyof FeatureFlagConfig>(
    key: K,
    value: FeatureFlagConfig[K]
  ): void {
    _setFlag(key, value)
    flags.value = { ...flags.value, [key]: value }
  }

  // 重置所有 flags
  function reset(): void {
    _resetFlags()
    flags.value = reloadFeatureFlags()
  }

  // 重新加载配置
  function reload(): void {
    flags.value = reloadFeatureFlags()
  }

  // 调试信息
  function debug() {
    return getFeatureFlagsInfo()
  }

  return {
    // Flags
    UI_V2,
    STICKY_CTA,
    GROWTH_INVITE,
    PROFILE_EASTER_EGG,
    PROFILE_BRIDGE,
    ROUTE_CONFIG,
    // 原始对象（支持动态访问）
    flags,
    // 操作方法
    setFlag,
    reset,
    reload,
    debug,
  }
}
