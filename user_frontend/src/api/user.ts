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

/** 设置播放线路偏好；非法值由后端 400 拒绝。 */
export async function setPlayLine(line: PlayLine): Promise<PlayLine> {
  const { line: saved } = await api.put<never, { line: string }>('/api/user/emby/play-line', { line })
  return normalizeLine(saved)
}
