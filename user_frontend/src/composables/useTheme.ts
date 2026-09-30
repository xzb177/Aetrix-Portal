import { ref, computed, onMounted, onBeforeUnmount } from 'vue'

/**
 * 三档外观切换（v2.42.2）：跟随系统 / 白日 / 黑暗。
 *
 * 实际生效的主题（resolved）只有两个：dark（默认，即现有 Aurora 深蓝青）
 * 与 light（html[data-theme="light"]，独立调色的暖调纸白）。第三档「跟随系统」
 * 只是存储值上的缺省——resolved 由 prefers-color-scheme 实时决定，系统切换时
 * 无刷新跟随（监听 change 事件）。
 *
 * 口径与 index.html 里的主题预套用脚本一致：localStorage('aetrix-theme')，
 * 提前写好 data-theme 避免首屏闪深底（FOUC）；这里负责后续切换与系统联动。
 *
 * 顶栏的 meta theme-color 跟随 resolved 切换：移动端浏览器工具栏不再固定深色。
 */

type ThemePreference = 'system' | 'light' | 'dark'
type ResolvedTheme = 'light' | 'dark'

const STORAGE_KEY = 'aetrix-theme'

const preference = ref<ThemePreference>('system')
const systemLight = ref(false)
const metaTheme: HTMLMetaElement | null =
  typeof document !== 'undefined'
    ? document.querySelector('meta[name="theme-color"]')
    : null

function readStored(): ThemePreference {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    return stored === 'light' || stored === 'dark' || stored === 'system' ? stored : 'system'
  } catch {
    return 'system'
  }
}

function writeStored(value: ThemePreference) {
  try {
    localStorage.setItem(STORAGE_KEY, value)
  } catch {
    /* 隐私模式等存不了就算了：本次会话内仍生效 */
  }
}

/** 实际生效的主题：三档折叠成两档 */
const resolved = computed<ResolvedTheme>(() => {
  if (preference.value === 'system') return systemLight.value ? 'light' : 'dark'
  return preference.value
})

function applyTheme() {
  const html = document.documentElement
  if (resolved.value === 'light') html.setAttribute('data-theme', 'light')
  else html.removeAttribute('data-theme')
  // 浅色下浏览器工具栏跟底色（与 --au-bg 一致），深色维持原 #070b12
  metaTheme?.setAttribute('content', resolved.value === 'light' ? '#f5f8fb' : '#070b12')
}

function setPreference(value: ThemePreference) {
  preference.value = value
  writeStored(value)
  applyTheme()
}

let mql: MediaQueryList | null = null
let onSystemChange: ((e: MediaQueryListEvent) => void) | null = null

function initTheme() {
  preference.value = readStored()
  if (typeof window === 'undefined' || !window.matchMedia) {
    applyTheme()
    return
  }
  mql = window.matchMedia('(prefers-color-scheme: light)')
  systemLight.value = mql.matches
  // Safari < 14 只有 addListener，补上兜底
  onSystemChange = (e) => {
    systemLight.value = e.matches
    applyTheme()
  }
  if (mql.addEventListener) mql.addEventListener('change', onSystemChange)
  else if (mql.addListener) mql.addListener(onSystemChange)
  applyTheme()
}

function disposeTheme() {
  if (mql && onSystemChange) {
    if (mql.removeEventListener) mql.removeEventListener('change', onSystemChange)
    else if (mql.removeListener) mql.removeListener(onSystemChange)
  }
  mql = null
  onSystemChange = null
}

/** 首页 / 顶栏各调一次也安全：init 幂等，重复调用只是重复挂同一个监听前的清理 */
export function useTheme() {
  onMounted(() => {
    disposeTheme()
    initTheme()
  })
  onBeforeUnmount(disposeTheme)
  return { preference, resolved, setPreference }
}
