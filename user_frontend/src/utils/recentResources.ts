/**
 * 首页「本周入库」：把追新日历的条目（电影 / 剧集 / 单集）收成「资源」——一部剧或一部电影一张卡。
 *
 * 规则（2026-10-09 需求）：
 * - **只出资源，不出单集**：单集按所属剧（SeriesId）归并；同一部剧多集只留最新的一张；
 *   剧集本体（Series）与它的单集也归成同一张；
 * - 片名只写剧名 / 电影名：不出现「第 N 集」/ SxxExx；
 * - 每张卡给出**有序的图片候选**：单集先取**剧**的 Primary，再退到单集自己的 Primary
 *   （服务端会按 集 → 季 → 剧 回退）、单集 Thumb；电影 / 剧取自己的 Primary → Thumb。
 *   全部失败才落到排版占位卡（模板里按 onerror 逐个往后试）。
 *
 * 纯函数、不碰网络与图片地址拼接，方便单测；入参必须已按「新 → 旧」排好序。
 */

export type ImageKind = 'Primary' | 'Thumb'

export interface RecentSourceItem {
  Id: string
  Name?: string | null
  Type?: string | null
  SeriesId?: string | null
  SeriesName?: string | null
  ProductionYear?: number | null
  ProviderIds?: Record<string, string> | null
  /** 单集的集号（Emby IndexNumber），用于统计"更新至 N 集" */
  IndexNumber?: number | null
}

export interface PosterCandidate {
  itemId: string
  kind: ImageKind
}

export interface RecentResource {
  /** 归并键：s:<SeriesId> / n:<剧名> / m:<条目 Id> */
  key: string
  /** 剧名或电影名（不含集号） */
  title: string
  year: string
  /** 'Series' | 'Movie'：单集归并后按剧算 */
  type: 'Series' | 'Movie'
  /** 用于深链的 TMDB id（只有 Series / Movie 本体才可信） */
  tmdbId: string
  /** 按优先级排好的图片候选，至少一项 */
  posters: PosterCandidate[]
  /** 归并的单集数（>1 时卡片标题显示"更新至 N 集"） */
  episodeCount: number
  /** 归并单集中最大的集号（用于"更新至 N 集"） */
  maxEpisode: number | null
}

/** 集号后缀：S01E58 / S01 / E58 / 第58集 / 第 58 话 / EP58 / - 58 */
// 英文集号前面必须有分隔符，免得把 Sense8 这类片名尾巴当成集号
const EPISODE_SUFFIX = [
  /[\s._-]+S\d{1,2}\s*E\d{1,4}$/i,
  /[\s._-]+S\d{1,2}$/i,
  /[\s._-]+EP?\s*\d{1,4}$/i,
  /\s*第\s*\d{1,4}\s*[集话話期]$/,
  /\s+-\s+\d{1,4}$/,
]

/** 去掉标题末尾的集号（剧名缺失时用单集名兜底，不能把「第 N 集」带出来） */
export function stripEpisodeSuffix(name: string): string {
  let out = (name || '').trim()
  for (let i = 0; i < 3; i++) {
    const before = out
    for (const re of EPISODE_SUFFIX) out = out.replace(re, '').trim()
    if (out === before) break
  }
  return out || (name || '').trim()
}

function tmdbOf(item: RecentSourceItem): string {
  const raw = (item.ProviderIds?.Tmdb ?? '').toString().trim()
  return /^\d+$/.test(raw) ? raw : ''
}

export function groupRecentResources(items: RecentSourceItem[], limit = 12): RecentResource[] {
  const out: RecentResource[] = []
  const byKey = new Map<string, RecentResource>()

  for (const item of items) {
    if (!item?.Id) continue
    const type = item.Type || ''
    if (type === 'Season') continue

    let key: string
    let res: RecentResource
    if (type === 'Episode') {
      const seriesName = (item.SeriesName || '').trim()
      const title = seriesName || stripEpisodeSuffix(item.Name || '')
      key = item.SeriesId ? `s:${item.SeriesId}` : `n:${title}`
      const posters: PosterCandidate[] = []
      if (item.SeriesId) posters.push({ itemId: String(item.SeriesId), kind: 'Primary' })
      posters.push({ itemId: item.Id, kind: 'Primary' }, { itemId: item.Id, kind: 'Thumb' })
      const epNum = typeof item.IndexNumber === 'number' ? item.IndexNumber : null
      res = { key, title, year: '', type: 'Series', tmdbId: '', posters, episodeCount: 1, maxEpisode: epNum }
    } else if (type === 'Series') {
      key = `s:${item.Id}`
      res = {
        key,
        title: (item.Name || '').trim(),
        year: item.ProductionYear ? String(item.ProductionYear) : '',
        type: 'Series',
        tmdbId: tmdbOf(item),
        posters: [{ itemId: item.Id, kind: 'Primary' }, { itemId: item.Id, kind: 'Thumb' }],
        episodeCount: 0,
        maxEpisode: null,
      }
    } else {
      key = `m:${item.Id}`
      res = {
        key,
        title: (item.Name || '').trim(),
        year: item.ProductionYear ? String(item.ProductionYear) : '',
        type: 'Movie',
        tmdbId: tmdbOf(item),
        posters: [{ itemId: item.Id, kind: 'Primary' }, { itemId: item.Id, kind: 'Thumb' }],
        episodeCount: 0,
        maxEpisode: null,
      }
    }

    const existing = byKey.get(key)
    if (existing) {
      // 已有更新的一条：剧集本体晚到时补上它的年份 / TMDB id / 海报（剧自己的图最可靠）
      if (type === 'Series') {
        if (!existing.year) existing.year = res.year
        if (!existing.tmdbId) existing.tmdbId = res.tmdbId
        if (!existing.posters.some((p) => p.itemId === item.Id && p.kind === 'Primary')) {
          existing.posters.unshift({ itemId: item.Id, kind: 'Primary' })
        }
      }
      // 单集归并：累计集数，记录最大集号（用于"更新至 N 集"）
      if (type === 'Episode') {
        existing.episodeCount += 1
        if (res.maxEpisode != null && (existing.maxEpisode == null || res.maxEpisode > existing.maxEpisode)) {
          existing.maxEpisode = res.maxEpisode
        }
      }
      continue
    }
    if (out.length >= limit) continue
    // 同名不同 SeriesId 的两条（剧名缺失兜底那条与有 SeriesId 的那条）：按名字再并一次
    const sameTitle = res.type === 'Series' && out.find((r) => r.type === 'Series' && r.title === res.title)
    if (sameTitle) {
      byKey.set(key, sameTitle)
      for (const p of res.posters) {
        if (!sameTitle.posters.some((q) => q.itemId === p.itemId && q.kind === p.kind)) sameTitle.posters.push(p)
      }
      continue
    }
    byKey.set(key, res)
    out.push(res)
  }
  return out
}
