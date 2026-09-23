/**
 * 站点品牌（能力：站点与品牌）—— 管理后台侧
 *
 * 与用户端（`user_frontend/src/composables/useBranding.ts`）读同一份配置，但落到**不同的令牌**：
 * 管理端用 `--primary*`（用户端是 `--au-primary*`）。主题色由后台自己填，改完刷新即生效，
 * 不需要重新构建前端。
 */
import { reactive } from 'vue'
import { siteApi, type Branding } from '@/api/site'

export const DEFAULT_SITE_NAME = 'RoyalBot'
export const DEFAULT_THEME_COLOR = '#22d3ee'
export const APP_VERSION = 'v2.23.1'

export const branding = reactive<Branding>({
  site_name: DEFAULT_SITE_NAME,
  logo_url: '',
  theme_color: DEFAULT_THEME_COLOR,
  seo_title: '',
  seo_description: '',
  seo_keywords: '',
})

let initialized = false

export function siteName(): string {
  return branding.site_name || DEFAULT_SITE_NAME
}

export function adminTitle(page?: string): string {
  return page ? `${page} · ${siteName()} 管理后台` : `${siteName()} 管理后台`
}

function hexToRgb(hex: string): [number, number, number] {
  let value = hex.replace('#', '').trim()
  if (value.length === 3) value = value.split('').map((c) => c + c).join('')
  if (value.length === 8) value = value.slice(0, 6)
  const num = Number.parseInt(value, 16)
  if (!Number.isFinite(num) || value.length !== 6) return [34, 211, 238]
  return [(num >> 16) & 255, (num >> 8) & 255, num & 255]
}

const rgba = (rgb: [number, number, number], alpha: number) =>
  `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, ${alpha})`

/** 提亮 / 压暗（主色悬停与按下态） */
function shift(rgb: [number, number, number], factor: number): string {
  const part = (v: number) => Math.max(0, Math.min(255, Math.round(v * factor)))
  return `rgb(${part(rgb[0])}, ${part(rgb[1])}, ${part(rgb[2])})`
}

/** 主色上的文字色：按亮度选深/浅，保证对比度 */
function onColor(rgb: [number, number, number]): string {
  const luminance = (0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]) / 255
  return luminance > 0.6 ? '#05202a' : '#ffffff'
}

export function applyBranding() {
  const rgb = hexToRgb(branding.theme_color)
  const style = document.documentElement.style
  style.setProperty('--primary', branding.theme_color)
  style.setProperty('--primary-hover', shift(rgb, 1.16))
  style.setProperty('--primary-active', shift(rgb, 0.86))
  style.setProperty('--primary-bg', rgba(rgb, 0.12))
  style.setProperty('--primary-soft', rgba(rgb, 0.08))
  style.setProperty('--primary-border', rgba(rgb, 0.32))
  style.setProperty('--primary-glow', rgba(rgb, 0.28))
  style.setProperty('--primary-on', onColor(rgb))
  style.setProperty('--border-focus', rgba(rgb, 0.6))
  style.setProperty('--gradient-brand',
    `linear-gradient(135deg, ${branding.theme_color} 0%, ${shift(rgb, 0.72)} 100%)`)
  style.setProperty('--gradient-brand-hover',
    `linear-gradient(135deg, ${shift(rgb, 1.16)} 0%, ${shift(rgb, 0.86)} 100%)`)

  // 标题：路由守卫先写的是「页面名 · 旧站名 管理后台」，这里只换站名那段，
  // 别把页面名（例如「用户管理」）冲掉。
  const suffix = `· ${DEFAULT_SITE_NAME} 管理后台`
  if (document.title.endsWith(suffix)) {
    document.title = `${document.title.slice(0, -suffix.length)}· ${siteName()} 管理后台`
  } else {
    document.title = adminTitle()
  }

  let tag = document.querySelector<HTMLMetaElement>('meta[name="description"]')
  if (branding.seo_description) {
    if (!tag) {
      tag = document.createElement('meta')
      tag.setAttribute('name', 'description')
      document.head.appendChild(tag)
    }
    tag.setAttribute('content', branding.seo_description)
  }
}

export async function initBranding(): Promise<void> {
  if (initialized) return
  initialized = true
  try {
    Object.assign(branding, await siteApi.branding())
  } catch {
    return // 拿不到就用默认品牌，后台不该因为一次请求失败而变白屏
  }
  applyBranding()
}
