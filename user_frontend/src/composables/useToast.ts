import { ref } from 'vue'

export interface ToastMessage {
  id: number
  type: 'success' | 'error' | 'warning' | 'info'
  message: string
  duration?: number
}

const messages = ref<ToastMessage[]>([])
let messageId = 0

export function useToast() {
  const add = (message: string, type: ToastMessage['type'] = 'info', duration = 3000) => {
    const id = ++messageId
    messages.value.push({ id, type, message, duration })

    // 自动关闭
    if (duration > 0) {
      setTimeout(() => {
        remove(id)
      }, duration)
    }

    return id
  }

  const remove = (id: number) => {
    const index = messages.value.findIndex(m => m.id === id)
    if (index > -1) {
      messages.value.splice(index, 1)
    }
  }

  const success = (message: string, duration?: number) => add(message, 'success', duration)
  const error = (message: string, duration?: number) => add(message, 'error', duration)
  const warning = (message: string, duration?: number) => add(message, 'warning', duration)
  const info = (message: string, duration?: number) => add(message, 'info', duration)

  // 复制成功的快捷方法
  const copySuccess = (item = '内容') => success(`${item} 已复制`)

  return {
    messages,
    add,
    remove,
    success,
    error,
    warning,
    info,
    copySuccess
  }
}
