/**
 * 全局 AuthSheet 状态管理
 *
 * 用于从任何地方（路由守卫、API 拦截器等）触发登录/注册弹窗
 */
import { ref, readonly } from 'vue'
import { useRouter } from 'vue-router'

const showAuthSheet = ref(false)

export function useAuthSheet() {
  const router = useRouter()

  const open = (redirectUrl?: string) => {
    // 保存当前页面路径，用于登录成功后跳转
    const redirect = redirectUrl || router.currentRoute.value.fullPath
    sessionStorage.setItem('auth_redirect', redirect)
    showAuthSheet.value = true
  }

  const close = () => {
    showAuthSheet.value = false
  }

  // 获取保存的重定向地址并清除
  const getRedirectAndClear = () => {
    const redirect = sessionStorage.getItem('auth_redirect') || '/'
    sessionStorage.removeItem('auth_redirect')
    return redirect
  }

  return {
    showAuthSheet: readonly(showAuthSheet),
    openAuthSheet: open,
    closeAuthSheet: close,
    getRedirectAndClear,
  }
}
