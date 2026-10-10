import { computed, onScopeDispose, ref, watch, type ComputedRef, type Ref } from 'vue'

const SAMPLE_W = 64
const SAMPLE_H = 96
const MIN_VALID_PIXELS = 100
const MIN_BRIGHTNESS_SUM = 60
const MAX_BRIGHTNESS_SUM = 700
const MIN_CHROMA = 30
const COLOR_ALPHA = 0.25
const DEDUPE_THRESHOLD = 32

interface VividColor {
  r: number
  g: number
  b: number
  chroma: number
}

const cache = new Map<string, string>()

function extractAmbiance(img: HTMLImageElement): string {
  const canvas = document.createElement('canvas')
  canvas.width = SAMPLE_W
  canvas.height = SAMPLE_H
  const ctx = canvas.getContext('2d', { willReadFrequently: true })
  if (!ctx) return ''

  ctx.drawImage(img, 0, 0, SAMPLE_W, SAMPLE_H)

  let data: Uint8ClampedArray
  try {
    data = ctx.getImageData(0, 0, SAMPLE_W, SAMPLE_H).data
  } catch {
    // canvas 被跨域图片污染，静默降级
    return ''
  }

  const vivid: VividColor[] = []

  for (let i = 0; i < data.length; i += 4) {
    const r = data[i]
    const g = data[i + 1]
    const b = data[i + 2]
    const sum = r + g + b
    if (sum < MIN_BRIGHTNESS_SUM || sum > MAX_BRIGHTNESS_SUM) continue
    const chroma = Math.max(r, g, b) - Math.min(r, g, b)
    if (chroma < MIN_CHROMA) continue
    vivid.push({ r, g, b, chroma })
  }

  if (vivid.length < MIN_VALID_PIXELS) return ''

  vivid.sort((a, b) => b.chroma - a.chroma)

  // 取前 3 个最鲜艳且互不相同的颜色
  const picked: VividColor[] = []
  for (const c of vivid) {
    if (picked.length >= 3) break
    const duplicate = picked.some(
      (p) =>
        Math.abs(p.r - c.r) < DEDUPE_THRESHOLD &&
        Math.abs(p.g - c.g) < DEDUPE_THRESHOLD &&
        Math.abs(p.b - c.b) < DEDUPE_THRESHOLD
    )
    if (!duplicate) picked.push(c)
  }
  // 兜底：不同色不足 3 个时按饱和度回填
  for (const c of vivid) {
    if (picked.length >= 3) break
    picked.push(c)
  }

  const [c1, c2, c3] = picked
  const rgba = (c: VividColor) => `rgba(${c.r},${c.g},${c.b},${COLOR_ALPHA})`

  return [
    `radial-gradient(ellipse 80% 60% at 20% 20%, ${rgba(c1)} 0%, transparent 70%)`,
    `radial-gradient(ellipse 80% 60% at 80% 30%, ${rgba(c2)} 0%, transparent 70%)`,
    `radial-gradient(ellipse 60% 50% at 50% 80%, ${rgba(c3)} 0%, transparent 70%)`,
  ].join(', ')
}

function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.crossOrigin = 'anonymous'
    img.decoding = 'async'

    const onLoad = () => {
      img.removeEventListener('load', onLoad)
      img.removeEventListener('error', onError)
      resolve(img)
    }
    const onError = () => {
      img.removeEventListener('load', onLoad)
      img.removeEventListener('error', onError)
      reject(new Error('Failed to load poster'))
    }

    img.addEventListener('load', onLoad)
    img.addEventListener('error', onError)
    img.src = url
  })
}

export function usePosterAmbiance(posterUrl: Ref<string>): { ambianceStyle: ComputedRef<string> } {
  const ambiance = ref('')
  let seq = 0

  watch(
    posterUrl,
    async (url) => {
      const current = ++seq

      if (!url) {
        ambiance.value = ''
        return
      }

      const cached = cache.get(url)
      if (cached !== undefined) {
        ambiance.value = cached
        return
      }

      try {
        const img = await loadImage(url)
        try {
          await img.decode()
        } catch {
          // decode 失败但 load 已成功，仍可安全绘制
        }
        if (current !== seq) return
        const style = extractAmbiance(img)
        cache.set(url, style)
        if (current !== seq) return
        ambiance.value = style
      } catch {
        // 加载失败时静默降级，不显示氛围光
        cache.set(url, '')
        if (current !== seq) return
        ambiance.value = ''
      }
    },
    { immediate: true }
  )

  onScopeDispose(() => {
    seq++
  })

  const ambianceStyle = computed(() => ambiance.value)

  return { ambianceStyle }
}
