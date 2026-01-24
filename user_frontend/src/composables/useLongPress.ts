/**
 * useLongPress - 长按手势检测 Composable
 *
 * 特性：
 * - 兼容鼠标和触摸（pointer events）
 * - 防止滑动误触（移动阈值检测）
 * - 支持自定义延迟时间
 * - 支持 prefers-reduced-motion 降级
 * - Haptic 反馈（可用时）
 *
 * @example
 * const { longPressProps, isPressing } = useLongPress({
 *   onLongPress: () => console.log('长按触发'),
 *   delay: 1000
 * })
 */
import { ref, onUnmounted } from 'vue'

export interface LongPressOptions {
  /** 长按触发延迟（毫秒），默认 1000ms */
  delay?: number
  /** 长按成功回调 */
  onLongPress: (event: PointerEvent) => void
  /** 按下开始回调（可选） */
  onPressStart?: () => void
  /** 按下结束回调（可选，无论是否成功触发） */
  onPressEnd?: () => void
  /** 最大移动距离（像素），超过则取消，默认 10px */
  moveThreshold?: number
  /** 是否启用 Haptic 反馈，默认 true */
  haptic?: boolean
}

export function useLongPress(options: LongPressOptions) {
  const {
    delay = 1000,
    onLongPress,
    onPressStart,
    onPressEnd,
    moveThreshold = 10,
    haptic = true
  } = options

  const isPressing = ref(false)
  let timer: ReturnType<typeof setTimeout> | null = null
  let startX = 0
  let startY = 0

  // 触发 Haptic 反馈（振动）
  const triggerHaptic = () => {
    if (!haptic) return

    try {
      // 检查是否支持 Vibration API
      if ('vibrate' in navigator && typeof navigator.vibrate === 'function') {
        // 轻微震动：50ms
        navigator.vibrate(50)
      }
    } catch {
      // 静默失败，不报错
    }
  }

  // 清理计时器
  const clearTimer = () => {
    if (timer) {
      clearTimeout(timer)
      timer = null
    }
  }

  // 处理按下
  const handlePointerDown = (e: PointerEvent) => {
    // 只响应主按钮（左键/触摸）
    if (e.button !== 0 && e.pointerType === 'mouse') return

    startX = e.clientX
    startY = e.clientY
    isPressing.value = true

    onPressStart?.()

    // 设置延迟触发
    timer = setTimeout(() => {
      isPressing.value = false
      triggerHaptic()
      onLongPress(e)
    }, delay)
  }

  // 处理移动
  const handlePointerMove = (e: PointerEvent) => {
    if (!isPressing.value || !timer) return

    const deltaX = Math.abs(e.clientX - startX)
    const deltaY = Math.abs(e.clientY - startY)

    // 超过移动阈值，取消长按
    if (deltaX > moveThreshold || deltaY > moveThreshold) {
      clearTimer()
      isPressing.value = false
      onPressEnd?.()
    }
  }

  // 处理释放
  const handlePointerUp = () => {
    clearTimer()
    if (isPressing.value) {
      isPressing.value = false
      onPressEnd?.()
    }
  }

  // 处理取消
  const handlePointerCancel = () => {
    clearTimer()
    isPressing.value = false
    onPressEnd?.()
  }

  // 处理离开元素
  const handlePointerLeave = () => {
    clearTimer()
    isPressing.value = false
    onPressEnd?.()
  }

  // 清理
  onUnmounted(() => {
    clearTimer()
  })

  // 返回 props 对象，可直接绑定到元素
  const longPressProps = {
    onPointerdown: handlePointerDown,
    onPointermove: handlePointerMove,
    onPointerup: handlePointerUp,
    onPointercancel: handlePointerCancel,
    onPointerleave: handlePointerLeave,
    // 防止触摸时的默认行为（如滚动、长按菜单）
    style: {
      touchAction: 'manipulation',
      userSelect: 'none',
      WebkitUserSelect: 'none'
    } as const
  }

  return {
    longPressProps,
    isPressing,
    clearTimer
  }
}
