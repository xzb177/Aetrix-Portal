import { onUnmounted, ref } from 'vue'

/**
 * 响应式断点（与 `styles/responsive.css`、`Layout.vue` 里的断点保持一致）
 *
 * 大多数适配靠 CSS 完成；只有「同一张表格在手机上要不要少一列 / 列多宽」这种
 * 结构性的差异才需要 JS 判断，所以这里只暴露两个布尔量。
 */
export const BREAKPOINT_PHONE = 640
export const BREAKPOINT_TABLET = 1024

function createQuery(query: string) {
  const matches = ref(false)
  if (typeof window === 'undefined' || !window.matchMedia) return matches

  const mql = window.matchMedia(query)
  matches.value = mql.matches
  const onChange = (e: MediaQueryListEvent) => { matches.value = e.matches }
  mql.addEventListener('change', onChange)
  // 只能在组件 setup 里调用（需要 onUnmounted 清理监听）
  onUnmounted(() => mql.removeEventListener('change', onChange))
  return matches
}

export function useBreakpoint() {
  return {
    /** 手机（≤640px）：页面结构可以做减法 */
    isPhone: createQuery(`(max-width: ${BREAKPOINT_PHONE}px)`),
    /** 平板及以下（≤1024px）：侧边栏是抽屉 */
    isTablet: createQuery(`(max-width: ${BREAKPOINT_TABLET}px)`),
  }
}
