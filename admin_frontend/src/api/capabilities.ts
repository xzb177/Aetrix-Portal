/**
 * v2.19.0 外部服务能力中心 API（/api/admin/capabilities/*）
 *
 * 后端把每个能力的**字段表**一起下发（`spec.fields`），前端只负责按类型渲染 →
 * 以后后端加一个能力 / 加一个字段，这里一行都不用改，也不会出现「界面漏了字段」。
 * 密钥字段后端只回 `******`，提交 `******` 表示不修改。
 */
import { get, post, put } from '@/utils/request'

export type CapabilityFieldType = 'str' | 'secret' | 'int' | 'bool' | 'select'

export interface CapabilityField {
  key: string
  label: string
  type: CapabilityFieldType
  default?: string
  hint?: string
  placeholder?: string
  required?: boolean
  /** type = select 时的可选项 */
  options?: string[]
}

export interface CapabilitySpec {
  title: string
  desc: string
  group: string
  docs_hint?: string
  fields: CapabilityField[]
  test_label?: string
}

export interface CapabilityCard {
  slug: string
  title: string
  desc: string
  group: string
  docs_hint?: string
  /** 能力当前是否在生效 */
  enabled: boolean
  /** 字段是否配齐（与开关无关） */
  configured: boolean
  /** 当前值（密钥为掩码） */
  fields: Record<string, string>
  test_label: string
}

export interface CapabilityDetail {
  spec: CapabilitySpec
  item: CapabilityCard
  values: Record<string, string>
}

export interface CapabilityTestResult {
  ok: boolean
  message: string
  detail?: Record<string, unknown>
}

export const fetchCapabilities = () =>
  get<{ capabilities: CapabilityCard[] }>('/capabilities')

export const fetchCapability = (slug: string) =>
  get<CapabilityDetail>(`/capabilities/${slug}`)

export const saveCapability = (slug: string, values: Record<string, string>) =>
  put<{ success: boolean } & CapabilityDetail>(`/capabilities/${slug}`, { values })

/** 真实连通性测试：故意不写配置，只验证「这套凭据到底能不能用」 */
export const testCapability = (slug: string, payload: Record<string, unknown> = {}) =>
  post<CapabilityTestResult>(`/capabilities/${slug}/test`, { payload })
