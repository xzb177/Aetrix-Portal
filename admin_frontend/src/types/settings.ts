/**
 * 系统配置类型定义
 * iOS 风格系统配置页面
 */

/**
 * 配置项数据类型
 */
export type SettingType = 'text' | 'password' | 'url' | 'number' | 'boolean' | 'select'

/**
 * 单个配置项
 */
export interface SettingItem {
  /** 配置键名 */
  key: string
  /** 配置显示名称（中文） */
  label: string
  /** 配置当前值 */
  value: string
  /** 配置描述 */
  description?: string
  /** 配置类型 */
  type: SettingType
  /** 所属分类 */
  category: string
  /** 下拉选项（仅 type=select 时使用） */
  options?: SettingOption[]
  /** 是否为敏感字段（API Token 等） */
  sensitive?: boolean
  /** 是否必填 */
  required?: boolean
  /** 默认值 */
  default?: string
  /** 验证正则 */
  pattern?: string
}

/**
 * 下拉选项
 */
export interface SettingOption {
  /** 选项显示值 */
  label: string
  /** 选项实际值 */
  value: string
}

/**
 * 配置分类
 */
export interface SettingCategory {
  /** 分类名称 */
  name: string
  /** 分类描述 */
  description?: string
  /** 该分类下的配置项数量 */
  count?: number
  /** 排序权重 */
  order?: number
}

/**
 * Dirty State 状态项
 */
export interface DirtyStateItem {
  /** 服务器原始值 */
  original: string
  /** 当前编辑值 */
  current: string
  /** 是否已修改 */
  dirty: boolean
}

/**
 * Dirty State 集合
 */
export type DirtyState = Record<string, DirtyStateItem>

/**
 * 批量更新请求项
 */
export interface SettingUpdateItem {
  key: string
  value: string
}

/**
 * 导入/导出配置项
 */
export interface SettingImportItem {
  key: string
  value: string
  description?: string
}
