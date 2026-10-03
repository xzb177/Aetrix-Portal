/**
 * 复制到剪贴板（全站唯一切口）
 *
 * ## 为什么需要它
 * 原先每个页面各自写 `navigator.clipboard.writeText(...)`（个人中心 3 处、
 * 邀请页 2 处），失败就是一句 `toast.error('复制失败')`，**没有任何退路**。
 * 而 `navigator.clipboard` 只在**安全上下文**（HTTPS / localhost）里存在：
 *
 *   - 自建 Emby 部署大量是 http://192.168.x.x、http://<VPS IP> 直接访问，
 *     没有 TLS 也没有配反代证书——这种场景下 `navigator.clipboard` 是
 *     `undefined`，`navigator.clipboard.writeText(...)` 直接抛 TypeError；
 *   - 部分 App 内置 WebView、部分旧版 iOS Safari 同样拿不到它。
 *
 * 结果就是「点复制毫无反应」。这里给出真正的降级链，让三条要求同时成立：
 * 真的复制上、成功失败都告诉用户、HTTP 下也能用。
 *
 * ## 降级顺序（以及为什么是这个顺序）
 * 1. `navigator.clipboard.writeText` —— 唯一无感、不会打断选区的路径。
 *    **先同步判断它能不能用**，不要先 `await` 一个不存在的方法。
 * 2. `document.execCommand('copy')` + 屏外 `<textarea>` —— 非安全上下文、
 *    老浏览器、权限被拒时的通用兜底。它必须在**用户手势的同一个同步任务**里
 *    调用才稳，所以能同步判断时不要先 await 别的 promise。
 * 3. 都不行 → 返回失败，由调用方弹一条**可操作**的提示（长按手选），
 *    而不是「复制失败」四个字让用户自己猜。
 *
 * ## 屏外 textarea 的几个坑（都已在下面处理）
 * - 不能用 `display:none`：那样元素不可选，`select()` 无效，直接返回 false。
 * - 必须 `readonly`：iOS 上非只读 textarea 会弹起键盘打断流程。
 * - `font-size` 要 ≥16px，否则 iOS 聚焦时会自动放大页面。
 * - 用完要还原焦点，否则按钮的焦点环消失、键盘用户下一次 Tab 会从头开始。
 */
import { useToast } from '@/composables/useToast'

/** 实际生效的复制通道，用于测试与埋点区分 */
export type CopyMethod = 'clipboard' | 'execCommand'

export interface CopyResult {
  ok: boolean
  /** 成功的通道；失败为 null */
  method: CopyMethod | null
}

/**
 * Clipboard API 现在能不能用。
 *
 * 必须**同步**返回：调用方据此决定走哪条路。若先 `await` 再判断，
 * 到 execCommand 时用户手势可能已经被消耗掉，复制照样失败。
 */
export function canUseClipboardApi(): boolean {
  if (typeof window === 'undefined' || typeof navigator === 'undefined') return false
  // isSecureContext 为 false（http://非 localhost）时 clipboard 根本不存在；
  // 仍再判一次方法本身，兼容个别浏览器只给权限不给 API 的情况
  if (window.isSecureContext === false) return false
  return typeof navigator.clipboard?.writeText === 'function'
}

/** 屏外 textarea + execCommand('copy')：HTTP / 老浏览器 / 权限被拒时的兜底 */
function legacyCopy(text: string): CopyResult {
  if (typeof document === 'undefined' || typeof document.execCommand !== 'function') {
    return { ok: false, method: null }
  }
  const active = document.activeElement as HTMLElement | null
  const area = document.createElement('textarea')
  area.value = text
  // readonly 避免 iOS 弹键盘；autofocus 属性在这里没用，靠下面的 focus()
  area.setAttribute('readonly', '')
  area.setAttribute('aria-hidden', 'true')
  area.style.position = 'fixed'
  area.style.top = '0'
  area.style.left = '-9999px'
  area.style.opacity = '0'
  // iOS 聚焦小于 16px 的输入框会自动缩放页面
  area.style.fontSize = '16px'
  area.style.pointerEvents = 'none'
  document.body.appendChild(area)

  let ok = false
  try {
    area.focus()
    area.select()
    // 老 Safari 只认 setSelectionRange，只调 select() 会复制不到
    area.setSelectionRange(0, text.length)
    ok = document.execCommand('copy') === true
  } catch {
    ok = false
  } finally {
    document.body.removeChild(area)
    // 还原焦点：否则按钮的焦点环消失，键盘用户下一次 Tab 要从页面开头重来
    active?.focus?.()
  }
  return { ok, method: ok ? 'execCommand' : null }
}

/**
 * 复制一段文本，自动在 Clipboard API 与 execCommand 之间降级。
 *
 * 空串直接判失败——「复制空的东西」不是成功，别给用户假反馈。
 */
export async function writeToClipboard(text: string): Promise<CopyResult> {
  if (!text) return { ok: false, method: null }

  if (canUseClipboardApi()) {
    try {
      await navigator.clipboard.writeText(text)
      return { ok: true, method: 'clipboard' }
    } catch {
      // 权限被拒 / 文档失焦 / WebView 不支持：继续走下面的兜底
    }
  }
  return legacyCopy(text)
}

/**
 * 页面里复制按钮的入口：直接给成功 / 失败反馈。
 *
 * @param text  要复制的原文
 * @param label 给用户看的名字，用于「XX 已复制」与失败提示（默认「内容」）
 */
export function useClipboard() {
  const toast = useToast()

  /** @returns 是否真的复制成功（调用方据此决定要不要给「已复制」的内联反馈） */
  async function copy(text: string, label = '内容'): Promise<boolean> {
    const result = await writeToClipboard(text)
    if (result.ok) {
      toast.copySuccess(label)
      return true
    }
    // 失败必须可操作：告诉用户去哪儿手动复制，而不是只说「复制失败」
    toast.error(`复制失败，请长按选中${label}后手动复制`, 5000)
    return false
  }

  return { copy, writeToClipboard }
}