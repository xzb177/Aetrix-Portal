/**
 * 全局 AuthSheet 状态管理
 *
 * 用于从任何地方（路由守卫、API 拦截器等）触发登录/注册弹窗
 */
import { ref, readonly } from 'vue'

const showAuthSheet = ref(false)

export function useAuthSheet() {
  const open = () => {
    showAuthSheet.value = true
  }

  const close = () => {
    showAuthSheet.value = false
  }

  return {
    showAuthSheet: readonly(showAuthSheet),
    openAuthSheet: open,
    closeAuthSheet: close,
  }
}
