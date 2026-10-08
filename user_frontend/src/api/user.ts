/**
 * 用户端个人设置 API（门户后端 /api/user/*）。
 *
 * 2026-10 简化：播放只有中转一条路径，以下接口保留仅为兼容，
 * 新代码不要再调用。
 */
import api from '@/api'

/** 播放路径（已废弃）：只有 'relay' */
export type PlayLine = 'relay'

/** 查询播放路径（已废弃）：永远返回 relay */
export async function getPlayLine(): Promise<{ line: PlayLine; cdnEnabled: boolean; cacheEnabled: boolean }> {
  try {
    const res = await api.get<never, { cdn_enabled?: boolean; cache_enabled?: boolean }>(
      '/api/user/emby/play-line',
    )
    return {
      line: 'relay',
      cdnEnabled: res.cdn_enabled === true,
      cacheEnabled: res.cache_enabled === true,
    }
  } catch {
    return { line: 'relay', cdnEnabled: false, cacheEnabled: false }
  }
}

/** 设置播放路径（已废弃）：空操作，永远返回 relay */
export async function setPlayLine(_line: PlayLine): Promise<PlayLine> {
  return 'relay'
}
