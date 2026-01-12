/**
 * 系统配置 Dirty State 管理
 * iOS 风格系统配置页面 - 状态管理 Composable
 */

import { ref, computed, type Ref } from 'vue'
import type { SettingItem, DirtyState, DirtyStateItem, SettingUpdateItem } from '@/types/settings'

export function useSettingsState(initialItems: Ref<SettingItem[]> = ref([])) {
  // 原始配置项列表
  const settings = ref<SettingItem[]>([])

  // Dirty State 记录
  const dirtyState = ref<DirtyState>({})

  // 仅显示已修改的配置
  const showModifiedOnly = ref(false)

  /**
   * 初始化状态（从 API 加载后调用）
   */
  const initializeState = (items: SettingItem[]) => {
    settings.value = items
    dirtyState.value = {}

    items.forEach(item => {
      dirtyState.value[item.key] = {
        original: item.value,
        current: item.value,
        dirty: false
      }
    })
  }

  /**
   * 更新单个配置值
   */
  const updateValue = (key: string, value: string): void => {
    if (dirtyState.value[key]) {
      dirtyState.value[key]!.current = value
      dirtyState.value[key]!.dirty = dirtyState.value[key]!.original !== value

      // 同步更新 settings 中的值（用于显示）
      const setting = settings.value.find(s => s.key === key)
      if (setting) {
        setting.value = value
      }
    }
  }

  /**
   * 获取当前编辑值
   */
  const getCurrentValue = (key: string): string => {
    return dirtyState.value[key]?.current ?? ''
  }

  /**
   * 检查单个配置是否已修改
   */
  const isDirty = (key: string): boolean => {
    return dirtyState.value[key]?.dirty ?? false
  }

  /**
   * 放弃所有修改
   */
  const discardChanges = (): void => {
    Object.keys(dirtyState.value).forEach(key => {
      const state = dirtyState.value[key]
      if (state) {
        state.current = state.original
        state.dirty = false

        // 同步恢复 settings 中的值
        const setting = settings.value.find(s => s.key === key)
        if (setting) {
          setting.value = state.original
        }
      }
    })
  }

  /**
   * 放弃单个配置的修改
   */
  const discardOne = (key: string): void => {
    const state = dirtyState.value[key]
    if (state) {
      state.current = state.original
      state.dirty = false

      const setting = settings.value.find(s => s.key === key)
      if (setting) {
        setting.value = state.original
      }
    }
  }

  /**
   * 获取所有已修改的配置项（用于提交）
   */
  const getDirtyItems = (): SettingUpdateItem[] => {
    return Object.entries(dirtyState.value)
      .filter(([_, state]) => state.dirty)
      .map(([key, state]) => ({ key, value: state.current }))
  }

  /**
   * 提交成功后更新原始值
   */
  const commitChanges = (): void => {
    Object.keys(dirtyState.value).forEach(key => {
      const state = dirtyState.value[key]
      if (state) {
        state.original = state.current
        state.dirty = false
      }
    })
  }

  /**
   * 检查指定 key 是否为敏感字段
   */
  const isSensitive = (key: string): boolean => {
    const setting = settings.value.find(s => s.key === key)
    if (!setting) return false
    return setting.sensitive ?? setting.type === 'password'
  }

  /**
   * 按分类分组配置项
   */
  const groupedSettings = computed(() => {
    const groups: Record<string, SettingItem[]> = {}

    let source = settings.value
    if (showModifiedOnly.value) {
      source = source.filter(item => dirtyState.value[item.key]?.dirty ?? false)
    }

    source.forEach(item => {
      if (!groups[item.category]) {
        groups[item.category] = []
      }
      groups[item.category]!.push(item)
    })

    return groups
  })

  /**
   * 已修改项数量
   */
  const dirtyCount = computed(() => {
    return Object.values(dirtyState.value).filter(s => s.dirty).length
  })

  /**
   * 是否有未保存的修改
   */
  const hasChanges = computed(() => dirtyCount.value > 0)

  /**
   * 获取指定分类的配置项
   */
  const getSettingsByCategory = (category: string): SettingItem[] => {
    return settings.value.filter(item => item.category === category)
  }

  /**
   * 根据搜索关键词过滤配置项
   */
  const searchSettings = (query: string): SettingItem[] => {
    if (!query) return settings.value

    const lowerQuery = query.toLowerCase()
    return settings.value.filter(item =>
      item.label?.toLowerCase().includes(lowerQuery) ||
      item.key?.toLowerCase().includes(lowerQuery) ||
      item.description?.toLowerCase().includes(lowerQuery)
    )
  }

  return {
    // 状态
    settings,
    dirtyState,
    showModifiedOnly,
    groupedSettings,
    dirtyCount,
    hasChanges,

    // 方法
    initializeState,
    updateValue,
    getCurrentValue,
    isDirty,
    isSensitive,
    discardChanges,
    discardOne,
    getDirtyItems,
    commitChanges,
    getSettingsByCategory,
    searchSettings
  }
}
