/**
 * 主题切换 Composable
 * 支持亮色/暗色主题切换，持久化到 localStorage
 */
import { ref, watch, onMounted } from 'vue'

export type Theme = 'light' | 'dark' | 'auto'

const STORAGE_KEY = 'royalbot-theme'

// 全局共享状态
const currentTheme = ref<Theme>('auto')
const resolvedTheme = ref<'light' | 'dark'>('dark')

// 从 localStorage 读取
const loadTheme = (): Theme => {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored === 'light' || stored === 'dark' || stored === 'auto') {
      return stored
    }
  } catch {
    // ignore
  }
  return 'auto'
}

// 保存到 localStorage
const saveTheme = (theme: Theme) => {
  try {
    localStorage.setItem(STORAGE_KEY, theme)
  } catch {
    // ignore
  }
}

// 解析最终使用的主题
const resolveTheme = (theme: Theme): 'light' | 'dark' => {
  if (theme === 'auto') {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  }
  return theme
}

// 应用主题到 DOM
const applyTheme = (theme: 'light' | 'dark') => {
  const body = document.body

  // 添加过渡动画类
  body.classList.add('theme-transition')

  if (theme === 'light') {
    document.documentElement.setAttribute('data-theme', 'light')
  } else {
    document.documentElement.removeAttribute('data-theme')
  }

  // 移除过渡动画类（延迟执行以确保过渡完成）
  setTimeout(() => {
    body.classList.remove('theme-transition')
  }, 300)

  resolvedTheme.value = theme
}

export function useTheme() {
  // 初始化
  onMounted(() => {
    currentTheme.value = loadTheme()
    applyTheme(resolveTheme(currentTheme.value))

    // 监听系统主题变化
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
    const handleChange = () => {
      if (currentTheme.value === 'auto') {
        applyTheme(resolveTheme('auto'))
      }
    }
    mediaQuery.addEventListener('change', handleChange)

    // 清理
    return () => {
      mediaQuery.removeEventListener('change', handleChange)
    }
  })

  // 监听主题变化
  watch(currentTheme, (newTheme) => {
    saveTheme(newTheme)
    applyTheme(resolveTheme(newTheme))
  })

  // 切换主题
  const setTheme = (theme: Theme) => {
    currentTheme.value = theme
  }

  // 切换到下一个主题（auto -> light -> dark -> auto）
  const toggleTheme = () => {
    const themes: Theme[] = ['auto', 'light', 'dark']
    const currentIndex = themes.indexOf(currentTheme.value)
    currentTheme.value = themes[(currentIndex + 1) % themes.length]
  }

  // 判断是否为暗色主题
  const isDark = () => resolvedTheme.value === 'dark'

  // 判断是否为亮色主题
  const isLight = () => resolvedTheme.value === 'light'

  return {
    theme: currentTheme,
    resolvedTheme,
    setTheme,
    toggleTheme,
    isDark,
    isLight
  }
}

// 单例模式，确保全局只有一个实例
let _instance: ReturnType<typeof useTheme> | null = null

export function useThemeSingleton() {
  if (!_instance) {
    _instance = useTheme()
  }
  return _instance
}
