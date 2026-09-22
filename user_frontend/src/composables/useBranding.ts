/**
 * 站点品牌（能力：站点与品牌）
 *
 * 管理后台「系统设置 → 站点与品牌」里填的站名 / Logo / 主题色 / SEO，在这里落地：
 *
 * - **主题色**：覆盖 Aurora 令牌 `--au-primary` 及其派生值（悬停色、浅底、描边、上面那层文字）。
 *   只改一个 `--au-primary` 是不够的——按钮上的文字色、悬停色、浅底都各有各的令牌，
 *   只换主色会让页面变成「新主色 + 旧配色」，所以这里一起算出来。
 * - **标题与 meta**：浏览器标题、描述、关键词。
 *
 * 拉取失败（后端没起、老版本后端没有这个端点）时**保持默认值**：品牌信息不该把页面拖住。
 */
import { reactive } from 'vue'
import { brandingApi, type Branding } from '@/api'

export const DEFAULT_SITE_NAME = 'Aetrix'
export const DEFAULT_THEME_COLOR = '#22d3ee'

export const branding = reactive<Branding>({
  site_name: DEFAULT_SITE_NAME,
  logo_url: '',
  theme_color: DEFAULT_THEME_COLOR,
  seo_title: '',
  seo_description: '',
  seo_keywords: '',
})

let initialized = false

/** 页面标题：`页面名 - 站名`（没有页面名时用 SEO 标题或站名） */
export function pageTitle(page?: string): string {
  if (page) return `${page} - ${branding.site_name}`
  return branding.seo_title || branding.site_name
}

function hexToRgb(hex: string): [number, number, number] {
  let value = hex.replace('#', '').trim()
  if (value.length === 3) value = value.split('').map((c) => c + c).join('')
  if (value.length === 8) value = value.slice(0, 6)   // 忽略 alpha，透明度由各令牌自己定
  const num = Number.parseInt(value, 16)
  if (!Number.isFinite(num) || value.length !== 6) return [34, 211, 238]
  return [(num >> 16) & 255, (num >> 8) & 255, num & 255]
}

function rgba(rgb: [number, number, number], alpha: number): string {
  return `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, ${alpha})`
}

/** 变暗（悬停/按下态用）：按比例压暗，比「调透明度」在深色底上更自然 */
function darken(rgb: [number, number, number], factor: number): string {
  const part = (v: number) => Math.max(0, Math.min(255, Math.round(v * factor)))
  return `rgb(${part(rgb[0])}, ${part(rgb[1])}, ${part(rgb[2])})`
}

/** 主色上的文字色：按亮度选深/浅，保证对比度 */
function onColor(rgb: [number, number, number]): string {
  const luminance = (0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]) / 255
  return luminance > 0.6 ? '#05141c' : '#ffffff'
}

function setMeta(name: string, content: string) {
  if (!content) return
  let tag = document.querySelector<HTMLMetaElement>(`meta[name="${name}"]`)
  if (!tag) {
    tag = document.createElement('meta')
    tag.setAttribute('name', name)
    document.head.appendChild(tag)
  }
  tag.setAttribute('content', content)
}

/** 把品牌信息写进文档（主题色令牌 / 标题 / meta） */
export function applyBranding() {
  const rgb = hexToRgb(branding.theme_color)
  const style = document.documentElement.style
  style.setProperty('--au-primary', branding.theme_color)
  style.setProperty('--au-primary-strong', darken(rgb, 0.85))
  style.setProperty('--au-primary-deep', darken(rgb, 0.55))
  style.setProperty('--au-primary-soft', rgba(rgb, 0.12))
  style.setProperty('--au-primary-mid', rgba(rgb, 0.2))
  style.setProperty('--au-primary-border', rgba(rgb, 0.28))
  style.setProperty('--au-primary-glow', rgba(rgb, 0.35))
  style.setProperty('--au-on-primary', onColor(rgb))
  style.setProperty('--au-border-focus', rgba(rgb, 0.55))

  // 标题策略：路由守卫已经写过「页面名 - 旧站名」，这里只把站名那段换掉，
  // 不能直接覆盖成 SEO 标题——否则刚打开 /media 时标题里的「媒体库」会丢。
  const suffix = ` - ${DEFAULT_SITE_NAME}`
  if (document.title.endsWith(suffix)) {
    document.title = `${document.title.slice(0, -suffix.length)} - ${branding.site_name}`
  } else {
    document.title = pageTitle()
  }
  setMeta('description', branding.seo_description)
  setMeta('keywords', branding.seo_keywords)
}

/** 启动时拉一次（幂等；失败保持默认值） */
export async function initBranding(): Promise<void> {
  if (initialized) return
  initialized = true
  try {
    const info = await brandingApi.get()
    Object.assign(branding, info)
  } catch {
    return
  }
  applyBranding()
}
