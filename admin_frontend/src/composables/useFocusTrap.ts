import { onBeforeUnmount, watch, type Ref } from 'vue'

/**
 * 轻量 focus trap：激活时把 Tab 焦点循环锁在容器内，打开时自动聚焦第一个可聚焦元素，
 * 关闭时把焦点还给之前的位置。Esc 交给调用方处理。
 *
 * 只给手写的抽屉/弹窗用 —— el-drawer / el-dialog 自带 trap，不需要这个。
 */
export function useFocusTrap(
  containerRef: Ref<HTMLElement | null>,
  activeRef: Ref<boolean>,
) {
  function focusables(root: HTMLElement): HTMLElement[] {
    const els = root.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), input:not([disabled]), ' +
      'select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    )
    // 过滤不可见元素
    return [...els].filter((el) => el.getClientRects().length > 0)
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key !== 'Tab' || !activeRef.value) return
    const root = containerRef.value
    if (!root) return
    const items = focusables(root)
    if (!items.length) {
      e.preventDefault()
      return
    }
    const first = items[0]
    const last = items[items.length - 1]
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault()
      last.focus()
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault()
      first.focus()
    }
  }

  let prevFocus: HTMLElement | null = null

  watch(activeRef, (active) => {
    if (active) {
      prevFocus = document.activeElement as HTMLElement | null
      document.addEventListener('keydown', onKeydown)
      // 等抽屉动画开始后再聚焦，避免聚焦到 display:none 的元素
      requestAnimationFrame(() => {
        const root = containerRef.value
        if (!root || !activeRef.value) return
        const items = focusables(root)
        if (items[0]) items[0].focus()
      })
    } else {
      document.removeEventListener('keydown', onKeydown)
      if (prevFocus && document.contains(prevFocus)) prevFocus.focus()
      prevFocus = null
    }
  })

  onBeforeUnmount(() => {
    document.removeEventListener('keydown', onKeydown)
  })
}
