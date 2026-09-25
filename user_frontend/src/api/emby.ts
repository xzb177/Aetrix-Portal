/**
 * Emby 协议 API 客户端
 *
 * 直接复用后端内置的 Emby 兼容协议端点（/emby/*）：
 * - 浏览：Views / Items / Resume / Latest / NextUp / Favorites
 * - 详情：Items/{id} / Shows/{id}/Seasons / Shows/{id}/Episodes
 * - 互动：Rating（收藏）/ PlayedItems（已看）/ PlaybackInfo
 * - 播放：直连 stream（Range）/ HLS 转码（hls.js）
 *
 * 鉴权：全部携带门户 JWT（后端 /emby/* 已支持 JWT 回退）。
 * 复用 api/index.ts 的 axios 实例：自动附 Authorization 头 + 401 自动刷新。
 */
import api from '@/api'

// ==================== 类型 ====================

export interface EmbyUserData {
  PlaybackPositionTicks: number
  PlayCount: number
  Played: boolean
  IsFavorite: boolean
  LastPlayedDate?: string | null
  /** 剧集未看集数（后端批量计算，电影/单集不看这个值） */
  UnplayedItemCount?: number | null
}

export interface EmbyItem {
  Id: string
  Name: string
  Type: 'Movie' | 'Series' | 'Season' | 'Episode' | string
  IsFolder: boolean
  ChildCount?: number | null
  ProductionYear?: number | null
  CommunityRating?: number | null
  OfficialRating?: string | null
  Overview?: string | null
  Genres?: string[]
  Tags?: string[]
  Studios?: string[]
  PremiereDate?: string | null
  DateCreated?: string | null
  SeriesId?: string | null
  SeriesName?: string | null
  SeasonId?: string | null
  ParentIndexNumber?: number | null
  IndexNumber?: number | null
  ImageTags?: Record<string, string>
  BackdropImageTags?: string[]
  UserData: EmbyUserData
  RunTimeTicks?: number | null
  /** 媒体库类型：movies / tvshows / mixed …（Views 接口返回） */
  CollectionType?: string | null
  MediaSources?: EmbyMediaSource[]
  /** 画质徽标用（后端 _item_dto 下发） */
  Width?: number | null
  Height?: number | null
  IsHD?: boolean
}

export interface EmbyMediaSource {
  Id: string
  Name?: string
  Container?: string | null
  Size?: number | null
  SupportsDirectPlay?: boolean
  SupportsDirectStream?: boolean
  SupportsTranscoding?: boolean
  DirectStreamUrl?: string
  TranscodingUrl?: string
  MediaStreams?: Array<{
    Index: number
    Type: string
    Codec?: string
    Language?: string
    DisplayTitle?: string
    IsExternal?: boolean
    IsTextSubtitleStream?: boolean
    IsDefault?: boolean
    /** 字幕轨的可直取地址（服务端已附 api_key） */
    DeliveryUrl?: string
  }>
  DefaultSubtitleStreamIndex?: number | null
}

export interface EmbyQuery {
  parentId?: string
  includeTypes?: string[]
  /** 按条目 Id 批量取（逗号分隔传给后端 Ids） */
  ids?: string[]
  searchTerm?: string
  genres?: string[]
  years?: number[]
  officialRatings?: string[]
  tags?: string[]
  /** 观看状态：IsFavorite / IsPlayed / IsUnplayed / IsResumable */
  filters?: string[]
  sortBy?: string
  sortOrder?: 'Ascending' | 'Descending'
  startIndex?: number
  limit?: number
  recursive?: boolean
}

/** 筛选菜单的可选值（后端 /Items/Filters 给出，取值来自全库） */
export interface EmbyFilters {
  Genres: string[]
  Tags: string[]
  OfficialRatings: string[]
  Years: number[]
}

// 1 tick = 100ns；1000 万 tick = 1 秒
export const TICKS_PER_SECOND = 10_000_000

export function ticksToSeconds(ticks?: number | null): number {
  return Math.round((ticks || 0) / TICKS_PER_SECOND)
}

export function secondsToTicks(seconds: number): number {
  return Math.round(seconds * TICKS_PER_SECOND)
}

export function formatDuration(seconds: number): string {
  if (!seconds || seconds <= 0) return '--'
  const h = Math.floor(seconds / 3600)
  const m = Math.round((seconds % 3600) / 60)
  return h > 0 ? `${h}小时${m}分钟` : `${m}分钟`
}

// ==================== 端点封装 ====================

const USER_ITEMS = '/emby/Users/me/Items'

export const embyApi = {
  /** 媒体库列表（Views） */
  async getViews(): Promise<EmbyItem[]> {
    const res = await api.get<never, { Items: EmbyItem[] }>('/emby/Users/me/Views')
    return res?.Items || []
  },

  /** 通用条目查询（浏览/搜索/筛选/分页） */
  async getItems(q: EmbyQuery = {}): Promise<{ Items: EmbyItem[]; TotalRecordCount: number }> {
    const params: Record<string, string | number> = {
      StartIndex: q.startIndex ?? 0,
      Limit: q.limit ?? 30,
      SortBy: q.sortBy || 'SortName',
      SortOrder: q.sortOrder || 'Ascending',
    }
    if (q.parentId) params.ParentId = q.parentId
    if (q.recursive !== false) params.Recursive = 'true'
    if (q.includeTypes?.length) params.IncludeItemTypes = q.includeTypes.join(',')
    if (q.ids?.length) params.Ids = q.ids.join(',')
    if (q.searchTerm) params.SearchTerm = q.searchTerm
    if (q.genres?.length) params.Genres = q.genres.join('|')
    if (q.years?.length) params.Years = q.years.join(',')
    if (q.officialRatings?.length) params.OfficialRatings = q.officialRatings.join(',')
    if (q.tags?.length) params.Tags = q.tags.join('|')
    if (q.filters?.length) params.Filters = q.filters.join(',')
    return api.get<never, { Items: EmbyItem[]; TotalRecordCount: number }>(USER_ITEMS, { params })
  },

  /** 筛选菜单的可选值（分类 / 标签 / 分级 / 年份） */
  async getFilters(): Promise<EmbyFilters> {
    const res = await api.get<never, Partial<EmbyFilters>>('/emby/Items/Filters')
    return {
      Genres: res?.Genres || [],
      Tags: res?.Tags || [],
      OfficialRatings: res?.OfficialRatings || [],
      Years: res?.Years || [],
    }
  },

  /** 续看列表（有播放进度未看完） */
  async getResume(limit = 12): Promise<EmbyItem[]> {
    const res = await api.get<never, { Items: EmbyItem[] }>(`${USER_ITEMS}/Resume`, { params: { Limit: limit } })
    return res?.Items || []
  },

  /** 最新添加 */
  async getLatest(limit = 16): Promise<EmbyItem[]> {
    return api.get<never, EmbyItem[]>(`${USER_ITEMS}/Latest`, { params: { Limit: limit } })
  },

  /** 剧集 NextUp */
  async getNextUp(limit = 12): Promise<EmbyItem[]> {
    const res = await api.get<never, { Items: EmbyItem[] }>('/emby/Shows/NextUp', { params: { Limit: limit } })
    return res?.Items || []
  },

  /** 收藏列表 */
  async getFavorites(): Promise<EmbyItem[]> {
    const res = await api.get<never, { Items: EmbyItem[] }>('/emby/Users/me/FavoriteItems')
    return res?.Items || []
  },

  /** 条目详情（full，含 MediaSources） */
  async getItem(itemId: string): Promise<EmbyItem> {
    return api.get<never, EmbyItem>(`/emby/Items/${itemId}`)
  },

  /** 剧集的季列表 */
  async getSeasons(seriesId: string): Promise<EmbyItem[]> {
    const res = await api.get<never, { Items: EmbyItem[] }>(`/emby/Shows/${seriesId}/Seasons`)
    return res?.Items || []
  },

  /** 剧集/季的集列表 */
  async getEpisodes(seriesId: string, seasonId?: string): Promise<EmbyItem[]> {
    const res = await api.get<never, { Items: EmbyItem[] }>(`/emby/Shows/${seriesId}/Episodes`, {
      params: seasonId ? { SeasonId: seasonId } : {},
    })
    return res?.Items || []
  },

  /** 切换收藏 */
  async setFavorite(itemId: string, isFavorite: boolean): Promise<EmbyUserData> {
    return api.post<never, EmbyUserData>(`/emby/Users/me/Items/${itemId}/Rating`, { IsFavorite: isFavorite })
  },

  /** 标记已看 / 未看 */
  async setPlayed(itemId: string, played: boolean): Promise<EmbyUserData> {
    if (played) {
      return api.post<never, EmbyUserData>(`/emby/Users/me/PlayedItems/${itemId}`)
    }
    return api.delete<never, EmbyUserData>(`/emby/Users/me/PlayedItems/${itemId}`)
  },

  /** 播放信息（返回带 api_key 的直连 / HLS 地址） */
  async getPlaybackInfo(itemId: string): Promise<{ MediaSources: EmbyMediaSource[]; PlaySessionId: string }> {
    return api.post<never, { MediaSources: EmbyMediaSource[]; PlaySessionId: string }>(
      `/emby/Items/${itemId}/PlaybackInfo`,
      {},
    )
  },

  /** 播放开始上报 */
  reportPlaying(itemId: string, positionSeconds: number, playMethod: string): Promise<unknown> {
    return api.post('/emby/Sessions/Playing', {
      ItemId: itemId,
      PositionTicks: secondsToTicks(positionSeconds),
      PlayMethod: playMethod,
    })
  },

  /** 播放进度上报（节流调用） */
  reportProgress(itemId: string, positionSeconds: number, paused: boolean, playMethod: string): Promise<unknown> {
    return api.post('/emby/Sessions/Playing/Progress', {
      ItemId: itemId,
      PositionTicks: secondsToTicks(positionSeconds),
      IsPaused: paused,
      PlayMethod: playMethod,
    })
  },

  /** 播放停止上报 */
  reportStopped(itemId: string, positionSeconds: number, playMethod: string): Promise<unknown> {
    return api.post('/emby/Sessions/Playing/Stopped', {
      ItemId: itemId,
      PositionTicks: secondsToTicks(positionSeconds),
      PlayMethod: playMethod,
    })
  },
}

function positionTicks() {
  return 0
}

// ==================== 图片与播放地址工具 ====================

/** 海报地址：/emby/Items/{id}/Images/Primary（带 JWT，可直接给 <img> 使用） */
export function posterUrl(item: EmbyItem, maxWidth = 320): string {
  if (!item.ImageTags?.Primary) return ''
  const token = localStorage.getItem('access_token') || ''
  return `/emby/Items/${item.Id}/Images/Primary?maxWidth=${maxWidth}&api_key=${encodeURIComponent(token)}`
}

/** 背景图地址 */
export function backdropUrl(item: EmbyItem, maxWidth = 1280): string {
  if (!item.BackdropImageTags?.length) return ''
  const token = localStorage.getItem('access_token') || ''
  return `/emby/Items/${item.Id}/Images/Backdrop?maxWidth=${maxWidth}&api_key=${encodeURIComponent(token)}`
}

/** 进度条百分比 */
export function progressPercent(item: EmbyItem): number {
  const pos = item.UserData?.PlaybackPositionTicks || 0
  if (!pos || !item.RunTimeTicks) return 0
  return Math.min(100, Math.round((pos / item.RunTimeTicks) * 100))
}
