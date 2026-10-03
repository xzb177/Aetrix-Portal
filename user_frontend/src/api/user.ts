/**
 * 用户端个人设置 API（门户后端 /api/user/*）。
 *
 * 目前只有播放线路偏好；以后再加别的用户级开关也放这里，
 * 不要散落到各业务 api 文件里。
 */
import api from '@/api'

/**
 * 播放线路：
 * - direct = 直连线路（默认，客户端直连网盘）；
 * - cdn = CDN 线路（播放三层第 2/3 层预留）：播放地址走管理员预留的 CDN 域名，
 *   热门分片由边缘缓存；管理员开启 CDN 后后端才会置 cdn_enabled，界面上供选择；
 * - cache = 本地缓存线路：优先从 VPS 本地读热门片，本地没有则回源并触发缓存；
 *   管理员开启本地缓存后后端才会置 cache_enabled，界面上供选择；
 * - relay = 中转线路（经服务器转发）。
 */
export type PlayLine = 'direct' | 'cdn' | 'cache' | 'relay'

function normalizeLine(line: unknown): PlayLine {
  if (line === 'relay') return 'relay'
  if (line === 'cdn') return 'cdn'
  if (line === 'cache') return 'cache'
  return 'direct'
}

/** 查询当前用户的播放线路偏好（无记录时后端回 direct）+ CDN / 本地缓存是否已启用 */
export async function getPlayLine(): Promise<{ line: PlayLine; cdnEnabled: boolean; cacheEnabled: boolean }> {
  const res = await api.get<never, { line?: string; cdn_enabled?: boolean; cache_enabled?: boolean }>(
    '/api/user/emby/play-line',
  )
  return {
    line: normalizeLine(res.line),
    cdnEnabled: res.cdn_enabled === true,
    cacheEnabled: res.cache_enabled === true,
  }
}

/**
 * 设置播放线路偏好；非法值由后端 400 拒绝。
 *
 * ## 为什么不能直接解构响应
 * 旧写法是 ``const { line: saved } = await api.put(...)``，有两个会直接变成
 * 「切换失败」的坑：
 *
 * 1. **响应体不是对象时解构本身抛 TypeError**（空响应体 / 反代返回 200 +
 *    空体）。这个 TypeError 会冒到调用方的 catch，用户看到的是无信息量的
 *    「切换失败，请重试」——查了半天也不知道后端到底回没回。
 * 2. **后端没回显目标线路时，``normalizeLine`` 兜底成 direct**，于是请求
 *    “切到中转”的用户会被界面显示成「已切换到直连线路」，而库里存的其实
 *    是中转。看起来就是「切换不成功」——但方向正好相反。
 *
 * 所以这里显式校验：**必须确认后端把偏好存成了我们要的那条线**，
 * 否则当作失败抛出，而不是报一个假的成功。
 */
export async function setPlayLine(line: PlayLine): Promise<PlayLine> {
  const res = await api.put<never, { line?: string } | null>('/api/user/emby/play-line', { line })
  const saved = normalizeLine(res?.line)
  if (saved !== line) {
    throw new Error(
      `播放线路未切换成功：期望 ${line}，服务器返回 ${res?.line ?? '空响应'}`,
    )
  }
  return saved
}
