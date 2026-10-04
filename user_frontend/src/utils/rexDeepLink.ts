/**
 * Rex 播放器 deep link（追新日历点击用）
 *
 * Rex 的两条协议：
 * - `rex://tmdb?id=<TMDB_ID>&type=<movie|tv>` —— 精确跳到某部作品
 * - `rex://search?q=<剧名>` —— 走 Rex 自己的全局搜索
 *
 * ## 为什么把这条单独拆出来
 * 「优先用 tmdb，没有才 search」看着是一行 `||`，但**剧集条目是最容易出错的一类**：
 * TMDB 里剧集（tv series）的 id 和单集（episode）的 id 是**两套编号**，而
 * `rex://tmdb?type=tv` 只认剧集的 id。把单集的 id 填进去不会报错，只会「点了没反应」
 * ——这是那种用户不会来报障、只会觉得「这网站有点毛病」的坑。
 * 所以规则写成：**只有电影 / 剧集本体才走 tmdb，单集一律按剧名搜索**。
 *
 * （补全链路本来也只给 series / movie 写 `tmdb_id`，见 enrich_worker；
 * 但规则不能依赖「碰巧为空」，NFO 里有 tmdb 标签的条目照样可能带上单集 id。）
 */

/** 追新日历能出现的条目类型（与后端 CALENDAR_ITEM_TYPES 一致；不含 season） */
type ItemLike = {
  Name?: string | null
  Type?: string | null
  SeriesName?: string | null
  ProviderIds?: Record<string, string> | null
}

/** 取 TMDB id；空对象 / 空串 / 非数字都当没有 */
function tmdbId(item: ItemLike): string {
  const raw = (item.ProviderIds?.Tmdb ?? '').toString().trim()
  return /^\d+$/.test(raw) ? raw : ''
}

/**
 * 生成点击跳转用的 href。
 *
 * - 电影 / 剧集且有 TMDB id → `rex://tmdb?id=&type=`
 * - 其余（剧集条目、或没刮削出 TMDB id）→ `rex://search?q=`
 */
export function rexDeepLink(item: ItemLike): string {
  const kind = (item.Type ?? '').toString()
  const id = tmdbId(item)
  if (id) {
    if (kind === 'Movie') return `rex://tmdb?id=${id}&type=movie`
    // 只有 Series 才轮到 type=tv；Episode 的 TMDB id 是单集 id，填进去必然打不开
    if (kind === 'Series') return `rex://tmdb?id=${id}&type=tv`
  }
  // 剧集条目按**剧名**搜（SeriesName），搜单集标题用户还得自己在结果里翻
  const name = (kind === 'Episode' ? item.SeriesName || item.Name : item.Name) ?? ''
  return `rex://search?q=${encodeURIComponent(name)}`
}
