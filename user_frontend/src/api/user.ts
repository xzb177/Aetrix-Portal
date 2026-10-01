/**
 * 用户端个人设置 API（门户后端 /api/user/*）。
 *
 * 目前只有播放线路偏好；以后再加别的用户级开关也放这里，
 * 不要散落到各业务 api 文件里。
 */
import api from '@/api'

/** 播放线路：direct = 直连线路（默认，客户端直连网盘）；relay = 中转线路（经服务器转发） */
export type PlayLine = 'direct' | 'relay'

function normalizeLine(line: unknown): PlayLine {
  return line === 'relay' ? 'relay' : 'direct'
}

/** 查询当前用户的播放线路偏好（无记录时后端回 direct）。 */
export async function getPlayLine(): Promise<PlayLine> {
  const { line } = await api.get<never, { line?: string }>('/api/user/emby/play-line')
  return normalizeLine(line)
}

/** 设置播放线路偏好；非法值由后端 400 拒绝。 */
export async function setPlayLine(line: PlayLine): Promise<PlayLine> {
  const { line: saved } = await api.put<never, { line: string }>('/api/user/emby/play-line', { line })
  return normalizeLine(saved)
}
