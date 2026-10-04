/**
 * 站点品牌（能力：站点与品牌）—— 管理后台侧
 *
 * 与用户端（`user_frontend/src/composables/useBranding.ts`）读同一份配置，但落到**不同的令牌**：
 * 管理端用 `--primary*`（用户端是 `--au-primary*`）。主题色由后台自己填，改完刷新即生效，
 * 不需要重新构建前端。
 */
import { reactive } from 'vue'
import { siteApi, type Branding } from '@/api/site'

export const DEFAULT_SITE_NAME = 'Aetrix'
export const DEFAULT_THEME_COLOR = '#22d3ee'
// 管理后台页脚展示的版本号（views/Layout.vue 的 foot-version）。构建期写死，不读根目录
// VERSION —— 所以必须与 VERSION 保持一致，由 scripts/check_version.py 门禁守着：
// 它曾停在 v2.33.0 而 VERSION 已到 2.42.6，导致「看界面版本判断线上跑的是哪个构建」
// 变成一个假信号（页脚永远显示同一个值）。
export const APP_VERSION = 'v2.47.0'

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

/** 相对亮度（0~1，未做 sRGB 线性化，只用于「够不够亮」的阈值判断） */
function luminance(rgb: [number, number, number]): number {
  return (0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]) / 255
}

function toHex(rgb: [number, number, number]): string {
  const part = (v: number) => v.toString(16).padStart(2, '0')
  return `#${part(rgb[0])}${part(rgb[1])}${part(rgb[2])}`
}

/** 品牌色注入用的 <style>（随主题切换分叉深浅两套，见 applyBrandingTokens） */
let brandStyle: HTMLStyleElement | null = null

/**
 * 品牌主题色注入（v2.42.6 改造，对齐用户端 v2.42.3 的做法）
 *
 * 不再写 `documentElement.style`：inline 自定义属性优先级最高，
 * `html[data-theme='light']` 里的浅色覆盖**永远**赢不了它——
 * 所以外观切到白日时主色仍是亮青（#22d3ee），而浅色主题的说明文字、
 * 描边按钮文字都是「亮青压白底」，对比度只有 ~1.9:1，看不清。
 *
 * 改为注入一段 <style>，深浅各一条规则：
 *
 * - 深色（`:root:root`）用管理员填的原色；
 * - 浅色（`:root:root[data-theme='light']`）把品牌色连乘压暗到白底可读
 *   （亮度阈值 0.42），派生色（悬停/浅底/描边/文字色）跟着有效色重算。
 *
 * 选择器用 `:root:root` 提高特异性（0,2,0 > 浅色块的 0,1,1），
 * 防后续注入的同特异性样式表抢赢；主题切换只改 html 的 data-theme，
 * 两套品牌色即时切换，不需要重新计算。
 */
function applyBrandingTokens() {
  const rgb = hexToRgb(branding.theme_color)

  let light = [...rgb] as [number, number, number]
  for (let i = 0; i < 6 && luminance(light) > 0.42; i++) {
    light = [
      Math.max(0, Math.min(255, Math.round(light[0] * 0.82))),
      Math.max(0, Math.min(255, Math.round(light[1] * 0.82))),
      Math.max(0, Math.min(255, Math.round(light[2] * 0.82))),
    ]
  }

  const darkRules = [
    `--primary:${branding.theme_color}`,
    `--primary-hover:${shift(rgb, 1.16)}`,
    `--primary-active:${shift(rgb, 0.86)}`,
    `--primary-bg:${rgba(rgb, 0.12)}`,
    `--primary-soft:${rgba(rgb, 0.08)}`,
    `--primary-border:${rgba(rgb, 0.32)}`,
    `--primary-glow:${rgba(rgb, 0.28)}`,
    `--primary-on:${onColor(rgb)}`,
    `--border-focus:${rgba(rgb, 0.6)}`,
    `--gradient-brand:linear-gradient(135deg, ${branding.theme_color} 0%, ${shift(rgb, 0.72)} 100%)`,
    `--gradient-brand-hover:linear-gradient(135deg, ${shift(rgb, 1.16)} 0%, ${shift(rgb, 0.86)} 100%)`,
  ].join(';')

  const lightRules = [
    `--primary:${toHex(light)}`,
    `--primary-hover:${shift(light, 0.88)}`,
    `--primary-active:${shift(light, 0.76)}`,
    `--primary-bg:${rgba(light, 0.1)}`,
    `--primary-soft:${rgba(light, 0.08)}`,
    `--primary-border:${rgba(light, 0.28)}`,
    `--primary-glow:${rgba(light, 0.22)}`,
    `--primary-on:${onColor(light)}`,
    `--border-focus:${rgba(light, 0.55)}`,
    `--gradient-brand:linear-gradient(135deg, ${toHex(light)} 0%, ${shift(light, 0.72)} 100%)`,
    `--gradient-brand-hover:linear-gradient(135deg, ${shift(light, 0.88)} 0%, ${shift(light, 0.76)} 100%)`,
  ].join(';')

  if (!brandStyle) {
    brandStyle = document.createElement('style')
    brandStyle.id = 'brand-tokens'
    document.head.appendChild(brandStyle)
  }
  brandStyle.textContent =
    `:root:root{${darkRules}}:root:root[data-theme='light']{${lightRules}}`
}

export function applyBranding() {
  applyBrandingTokens()

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
