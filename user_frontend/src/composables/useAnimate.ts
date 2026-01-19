/**
 * 微交互动画 Composable
 * 提供元素淡入、列表交错动画等效果
 */
import { ref, onMounted, nextTick } from 'vue'

export interface AnimationOptions {
  duration?: number
  delay?: number
  stagger?: number
  easing?: string
}

/**
 * 元素淡入动画
 * @param options 动画配置
 */
export function useFadeIn(options: AnimationOptions = {}) {
  const {
    duration = 300,
    delay = 0,
    easing = 'ease-out'
  } = options

  const element = ref<HTMLElement>()
  const isVisible = ref(false)

  onMounted(() => {
    nextTick(() => {
      setTimeout(() => {
        isVisible.value = true
      }, delay)
    })
  })

  const bind = (el: HTMLElement) => {
    element.value = el
    el.style.opacity = '0'
    el.style.transition = `opacity ${duration}ms ${easing}`

    nextTick(() => {
      setTimeout(() => {
        el.style.opacity = '1'
      }, delay)
    })
  }

  return {
    element,
    isVisible,
    bind
  }
}

/**
 * 列表交错动画
 * @param selector 列表项选择器
 * @param options 动画配置
 */
export function useStaggerAnimation(options: AnimationOptions = {}) {
  const {
    duration = 300,
    delay = 0,
    stagger = 50,
    easing = 'ease-out'
  } = options

  const container = ref<HTMLElement>()
  const isAnimated = ref(false)

  const animate = () => {
    if (!container.value) return

    const items = container.value.children
    if (!items.length) return

    Array.from(items).forEach((item, index) => {
      const el = item as HTMLElement
      el.style.opacity = '0'
      el.style.transform = 'translateY(20px)'
      el.style.transition = `opacity ${duration}ms ${easing}, transform ${duration}ms ${easing}`

      setTimeout(() => {
        el.style.opacity = '1'
        el.style.transform = 'translateY(0)'
      }, delay + (index * stagger))
    })

    isAnimated.value = true
  }

  onMounted(() => {
    nextTick(() => {
      animate()
    })
  })

  return {
    container,
    isAnimated,
    animate
  }
}

/**
 * 滑入动画
 */
export function useSlideIn(options: AnimationOptions = {}) {
  const {
    duration = 300,
    delay = 0,
    easing = 'ease-out',
    stagger = 50
  } = options

  const element = ref<HTMLElement>()
  const isVisible = ref(false)

  onMounted(() => {
    nextTick(() => {
      setTimeout(() => {
        isVisible.value = true
      }, delay)
    })
  })

  const bind = (el: HTMLElement) => {
    element.value = el
    el.style.transform = 'translateY(-20px)'
    el.style.opacity = '0'
    el.style.transition = `opacity ${duration}ms ${easing}, transform ${duration}ms ${easing}`

    nextTick(() => {
      setTimeout(() => {
        el.style.opacity = '1'
        el.style.transform = 'translateY(0)'
      }, delay)
    })
  }

  return {
    element,
    isVisible,
    bind
  }
}

/**
 * 缩放淡入动画
 */
export function useScaleIn(options: AnimationOptions = {}) {
  const {
    duration = 300,
    delay = 0,
    easing = 'cubic-bezier(0.34, 1.56, 0.64, 1)'
  } = options

  const element = ref<HTMLElement>()
  const isVisible = ref(false)

  onMounted(() => {
    nextTick(() => {
      setTimeout(() => {
        isVisible.value = true
      }, delay)
    })
  })

  const bind = (el: HTMLElement) => {
    element.value = el
    el.style.transform = 'scale(0.8)'
    el.style.opacity = '0'
    el.style.transition = `opacity ${duration}ms ${easing}, transform ${duration}ms ${easing}`

    nextTick(() => {
      setTimeout(() => {
        el.style.opacity = '1'
        el.style.transform = 'scale(1)'
      }, delay)
    })
  }

  return {
    element,
    isVisible,
    bind
  }
}

/**
 * 观察者动画 - 当元素进入视口时触发动画
 */
export function useIntersectionAnimation(options: AnimationOptions & {
  threshold?: number
  once?: boolean
} = {}) {
  const {
    duration = 400,
    easing = 'ease-out',
    threshold = 0.1,
    once = true
  } = options

  const elements = ref<Set<HTMLElement>>(new Set())
  const observer = ref<IntersectionObserver | null>(null)

  const addElement = (el: HTMLElement) => {
    elements.value.add(el)
    el.style.opacity = '0'
    el.style.transform = 'translateY(30px)'
    el.style.transition = `opacity ${duration}ms ${easing}, transform ${duration}ms ${easing}`

    if (observer.value) {
      observer.value.observe(el)
    }
  }

  const removeElement = (el: HTMLElement) => {
    elements.value.delete(el)
    if (observer.value) {
      observer.value.unobserve(el)
    }
  }

  onMounted(() => {
    observer.value = new IntersectionObserver(
      (entries) => {
        entries.forEach(entry => {
          if (entry.isIntersecting) {
            const el = entry.target as HTMLElement
            el.style.opacity = '1'
            el.style.transform = 'translateY(0)'

            if (once) {
              observer.value?.unobserve(el)
            }
          } else if (!once) {
            const el = entry.target as HTMLElement
            el.style.opacity = '0'
            el.style.transform = 'translateY(30px)'
          }
        })
      },
      { threshold }
    )

    elements.value.forEach(el => {
      observer.value?.observe(el)
    })
  })

  return {
    addElement,
    removeElement
  }
}
