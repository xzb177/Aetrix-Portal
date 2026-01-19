/**
 * 动画指令
 * 用法：v-animate="{ type: 'fade-in', delay: 100 }"
 */
import type { Directive } from 'vue'

export interface AnimateValue {
  type?: 'fade-in' | 'slide-in' | 'scale-in' | 'slide-up' | 'slide-down'
  delay?: number
  duration?: number
  stagger?: boolean
  index?: number
}

export const vAnimate: Directive<HTMLElement, AnimateValue | string> = {
  mounted(el, binding) {
    const options = typeof binding.value === 'string'
      ? { type: binding.value as AnimateValue['type'] }
      : binding.value || {}

    const {
      type = 'fade-in',
      delay = 0,
      duration = 300,
      stagger = false,
      index = 0
    } = options

    const finalDelay = stagger ? delay + (index * 50) : delay

    // 设置初始状态
    el.style.transition = `opacity ${duration}ms ease-out, transform ${duration}ms ease-out`

    switch (type) {
      case 'fade-in':
        el.style.opacity = '0'
        setTimeout(() => {
          el.style.opacity = '1'
        }, finalDelay)
        break

      case 'slide-in':
      case 'slide-up':
        el.style.opacity = '0'
        el.style.transform = 'translateY(20px)'
        setTimeout(() => {
          el.style.opacity = '1'
          el.style.transform = 'translateY(0)'
        }, finalDelay)
        break

      case 'slide-down':
        el.style.opacity = '0'
        el.style.transform = 'translateY(-20px)'
        setTimeout(() => {
          el.style.opacity = '1'
          el.style.transform = 'translateY(0)'
        }, finalDelay)
        break

      case 'scale-in':
        el.style.opacity = '0'
        el.style.transform = 'scale(0.8)'
        setTimeout(() => {
          el.style.opacity = '1'
          el.style.transform = 'scale(1)'
        }, finalDelay)
        break
    }
  }
}

/**
 * 列表交错动画指令
 * 用法：v-stagger="{ delay: 0, duration: 300 }"
 */
export const vStagger: Directive<HTMLElement, { delay?: number; duration?: number }> = {
  mounted(el, binding) {
    const { delay = 0, duration = 300 } = binding.value || {}
    const items = el.children

    Array.from(items).forEach((item, index) => {
      const elem = item as HTMLElement
      const itemDelay = delay + (index * 50)

      elem.style.opacity = '0'
      elem.style.transform = 'translateY(20px)'
      elem.style.transition = `opacity ${duration}ms ease-out, transform ${duration}ms ease-out`

      setTimeout(() => {
        elem.style.opacity = '1'
        elem.style.transform = 'translateY(0)'
      }, itemDelay)
    })
  }
}

/**
 * 视口进入动画指令
 * 用法：v-animate-when-visible
 */
export const vAnimateWhenVisible: Directive<HTMLElement> = {
  mounted(el) {
    el.style.opacity = '0'
    el.style.transform = 'translateY(30px)'
    el.style.transition = 'opacity 400ms ease-out, transform 400ms ease-out'

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach(entry => {
          if (entry.isIntersecting) {
            el.style.opacity = '1'
            el.style.transform = 'translateY(0)'
            observer.unobserve(el)
          }
        })
      },
      { threshold: 0.1 }
    )

    observer.observe(el)
  }
}

export default {
  animate: vAnimate,
  stagger: vStagger,
  'animate-when-visible': vAnimateWhenVisible
}
