<script setup lang="ts">
/**
 * 元数据来源 —— 条目这一层的元数据从哪来、怎么纠偏、补全跑得怎么样
 *
 * 迁移说明（Phase 6）：这三块以前塞在「媒体库」页的「元数据与刮削」卡片里，和「按库配置」
 * 混在一起。但它们回答的是**条目级**的问题（这一条的图/简介/IMDb 哪来的、补全队列到哪了），
 * 与「这个库扫什么目录、按什么策略刮」不是同一层。位置迁到这里，逻辑与文案原样搬迁。
 *
 * 这里仍然是**执行视角**：不新增任何状态、不改后端接口，三块功能与迁移前逐字一致
 * （接口、参数、提示文案、确认弹窗都没有动）。
 *
 * 按库的东西仍在「媒体库」页：TMDB API Keys、整库重刮、定时扫描、目录变更监听、
 * 云盘挂载入口。
 */
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { RefreshCw, RotateCw, Wand2 } from 'lucide-vue-next'
import {
  bindTmdb,
  fetchEnrichProgress,
  previewTmdb,
  rescrapeItem,
} from '@/api/admin'
import type { EnrichProgress, TmdbBindResult, TmdbPreview } from '@/api/admin'
import './MetadataSources.css'

// ==================== 条目元数据刷新 ====================

const rescrapeItemId = ref('')
const rescrapeItemLoading = ref(false)
const rescrapeItemNotes = ref<string[]>([])

/** 按条目 ID 重刮一条：有 NFO 就重读 NFO，再用 TMDB 补缺失的图 / IMDb / 别名 */
async function doRescrapeItem() {
  const id = Number(rescrapeItemId.value)
  if (!id) {
    ElMessage.warning('请填写条目 ID')
    return
  }
  rescrapeItemLoading.value = true
  try {
    const res = await rescrapeItem(id)
    const changed = Object.keys(res.summary.changed)
    rescrapeItemNotes.value = [
      `「${res.item.name}」：${res.summary.notes.join('；')}`,
      ...(changed.length ? [`变更字段：${changed.join('、')}`] : ['无字段变更']),
    ]
    ElMessage.success('已刷新')
  } finally {
    rescrapeItemLoading.value = false
  }
}

// ==================== 手动绑定 TMDB ====================
// TMDB 对中文剧集/综艺收录偏少，自动刮削搜不到的条目在这里手动指定 ID。
// 流程：填条目 ID → 填 TMDB ID → 预览确认是哪部片 → 绑定（或解绑）。
const bindItemId = ref('')
const bindTmdbId = ref('')
const bindPreview = ref<TmdbPreview | null>(null)
const bindPreviewLoading = ref(false)
const bindLoading = ref(false)
const bindNotes = ref<string[]>([])

async function doPreviewTmdb() {
  const id = Number(bindItemId.value)
  const tid = bindTmdbId.value.trim()
  if (!id) { ElMessage.warning('请填写条目 ID'); return }
  if (!tid) { ElMessage.warning('请填写 TMDB ID'); return }
  bindPreviewLoading.value = true
  bindPreview.value = null
  try {
    bindPreview.value = await previewTmdb(id, tid)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '预览失败')
  } finally {
    bindPreviewLoading.value = false
  }
}

async function doBindTmdb() {
  const id = Number(bindItemId.value)
  const tid = bindTmdbId.value.trim()
  if (!id) { ElMessage.warning('请填写条目 ID'); return }
  if (!tid) { ElMessage.warning('请填写 TMDB ID'); return }
  try {
    await ElMessageBox.confirm(
      bindPreview.value
        ? `把「${bindPreview.value.current_name}」绑定到 TMDB「${bindPreview.value.title}${bindPreview.value.year ? `（${bindPreview.value.year}）` : ''}」吗？`
        : `把条目 ${id} 绑定到 TMDB ID ${tid} 吗？（未预览，建议先点「预览」确认）`,
      '确认绑定',
      { type: 'warning' },
    )
  } catch { return }
  bindLoading.value = true
  try {
    const res: TmdbBindResult = await bindTmdb(id, tid, true)
    bindNotes.value = [`「${res.item.name}」：${res.notes.join('；')}`]
    bindPreview.value = null
    ElMessage.success('已绑定并补全元数据')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '绑定失败')
  } finally {
    bindLoading.value = false
  }
}

async function doUnbindTmdb() {
  const id = Number(bindItemId.value)
  if (!id) { ElMessage.warning('请填写条目 ID'); return }
  try {
    await ElMessageBox.confirm(
      `解绑条目 ${id} 的 TMDB ID？解绑后会重新排入补全队列。`,
      '确认解绑',
      { type: 'warning' },
    )
  } catch { return }
  bindLoading.value = true
  try {
    const res: TmdbBindResult = await bindTmdb(id, '', true)
    bindNotes.value = [`「${res.item.name}」：${res.notes.join('；')}`]
    bindPreview.value = null
    ElMessage.success('已解绑')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '解绑失败')
  } finally {
    bindLoading.value = false
  }
}

// ==================== 补全进度 ====================

const enrichProgress = ref<EnrichProgress | null>(null)
const enrichProgressLoading = ref(false)

/**
 * 阶段用时分解（v2.42.9）：按**累计耗时**降序——排最上面的就是最费时的那一段。
 * 状态计数只说「还有多少」，这一段回答「每条卡在哪」，是后面几批刮削优化的验收窗口。
 */
const enrichStageRows = computed(() => {
  const stages = enrichProgress.value?.stages || {}
  return Object.entries(stages)
    .map(([name, s]) => ({
      name,
      label: s.label || name,
      count: s.count || 0,
      avgMs: s.avg_ms || 0,
      totalMs: s.ms || 0,
    }))
    .filter((r) => r.count > 0)
    .sort((a, b) => b.totalMs - a.totalMs)
})

/** 速率窗口（秒 → 分钟，用于显示文案「近 N 分钟」） */
const enrichWindowMin = computed(() =>
  Math.max(1, Math.round((enrichProgress.value?.throughput?.window_sec ?? 300) / 60)))

/** 距上一次成功的时长：done/分钟 为 0 时，它区分「真的慢」与「卡住了 / 没在跑」 */
const enrichIdleHint = computed(() => {
  const idle = enrichProgress.value?.throughput?.idle_sec
  if (idle == null) return '本进程还没成功补全过'
  if (idle < 60) return `最近一次成功 ${idle} 秒前`
  return `最近一次成功 ${Math.round(idle / 60)} 分钟前`
})

async function loadEnrichProgress() {
  enrichProgressLoading.value = true
  try {
    enrichProgress.value = await fetchEnrichProgress()
  } catch {
    enrichProgress.value = null // 出错不挡页面其它内容
  } finally {
    enrichProgressLoading.value = false
  }
}

onMounted(() => {
  loadEnrichProgress().catch(() => undefined)
})
</script>

<template>
  <div class="admin-page">
    <div class="admin-page-header">
      <div>
        <h1 class="admin-page-title">元数据来源</h1>
        <p class="admin-page-desc">
          条目这一层的元数据从哪来、错了怎么纠、补全队列跑到哪一步。
          按库的扫描与刮削策略仍在「媒体库」页。
        </p>
      </div>
      <div class="toolbar">
        <RouterLink to="/emby"><el-button size="small">去媒体库页</el-button></RouterLink>
        <el-button size="small" :loading="enrichProgressLoading" @click="loadEnrichProgress">
          <RefreshCw :size="14" style="margin-right: 4px" />刷新进度
        </el-button>
      </div>
    </div>

    <div class="ms-grid">
      <!-- 1. 条目元数据刷新 -->
      <div class="admin-card ms-card">
        <div class="card-header">
          <h2><RotateCw :size="16" style="margin-right: 6px" />条目元数据刷新</h2>
        </div>
        <p class="ms-hint">
          按条目 ID 立即重刮一条：有 NFO 就重读 NFO（文字以 NFO 为准），
          再用 TMDB 补缺失的图片 / IMDb / 别名。电影 / 剧集优先，季 / 集按 NFO 能力处理。
        </p>
        <div class="ms-actions">
          <el-input v-model="rescrapeItemId" placeholder="条目 ID" style="width: 160px" clearable />
          <el-button size="small" :loading="rescrapeItemLoading" @click="doRescrapeItem">
            刷新元数据
          </el-button>
        </div>
        <div v-if="rescrapeItemNotes.length" class="ms-results">
          <div v-for="(n, i) in rescrapeItemNotes" :key="i" class="ms-result">{{ n }}</div>
        </div>
      </div>

      <!-- 2. 手动绑定 TMDB -->
      <div class="admin-card ms-card">
        <div class="card-header">
          <h2><Wand2 :size="16" style="margin-right: 6px" />手动绑定 TMDB</h2>
        </div>
        <p class="ms-hint">
          TMDB 对中文剧集 / 综艺收录偏少，自动刮削搜不到的条目在这里手动指定 TMDB ID。
          先「预览」确认是哪部片，再「绑定」；绑定后自动补全缺失的图 / 简介 / IMDb / 别名。
        </p>
        <div class="ms-actions">
          <el-input v-model="bindItemId" placeholder="条目 ID" style="width: 140px" clearable />
          <el-input v-model="bindTmdbId" placeholder="TMDB ID（数字）" style="width: 160px" clearable />
          <el-button size="small" :loading="bindPreviewLoading" @click="doPreviewTmdb">
            预览
          </el-button>
        </div>
        <div v-if="bindPreview" class="ms-results">
          <div class="ms-result">
            <span class="mini-badge" :class="bindPreview.matches_current ? 'ok' : 'warn'">
              {{ bindPreview.matches_current ? '片名一致' : '片名不一致，请核对' }}
            </span>
            <span>TMDB：{{ bindPreview.title }}<span v-if="bindPreview.year">（{{ bindPreview.year }}）</span></span>
            <span class="ms-hint">当前条目：{{ bindPreview.current_name }}（TMDB {{ bindPreview.current_tmdb_id ?? '未绑定' }}）</span>
          </div>
        </div>
        <div class="ms-actions">
          <el-button type="primary" size="small" :loading="bindLoading" @click="doBindTmdb">
            绑定
          </el-button>
          <el-button size="small" :loading="bindLoading" @click="doUnbindTmdb">
            解绑
          </el-button>
        </div>
        <div v-if="bindNotes.length" class="ms-results">
          <div v-for="(n, i) in bindNotes" :key="i" class="ms-result">{{ n }}</div>
        </div>
      </div>

      <!-- 3. 补全进度 -->
      <div class="admin-card ms-card ms-card-wide">
        <div class="card-header">
          <h2><RefreshCw :size="16" style="margin-right: 6px" />补全进度</h2>
        </div>
        <p class="ms-hint">
          后台补全 worker（enrich）的工作进度：待处理 / 进行中 / 已完成 / 失败 / 重试中。
        </p>
        <div v-if="enrichProgressLoading && !enrichProgress" class="ms-hint">加载中…</div>
        <div v-else-if="!enrichProgress" class="ms-hint">暂无数据</div>
        <div v-else>
          <div class="ms-facts">
            <span class="fact">待处理 {{ enrichProgress.enrich.pending }}</span>
            <span class="fact">进行中 {{ enrichProgress.enrich.enriching }}</span>
            <span class="fact ok">已完成 {{ enrichProgress.enrich.done }}</span>
            <span class="fact" :class="{ danger: enrichProgress.enrich.failed > 0 }">
              失败 {{ enrichProgress.enrich.failed }}
            </span>
            <span class="fact">重试中 {{ enrichProgress.enrich.retrying }}</span>
          </div>
          <!-- v2.42.9：阶段用时分解 + 近 5 分钟完成速率。只报「进程内计数」——
               分母是本次进程运行时长，重启会归零，所以标签写清「本进程」。 -->
          <div v-if="enrichStageRows.length" class="ms-facts">
            <span
              v-for="row in enrichStageRows"
              :key="row.name"
              class="fact"
              :title="`${row.label}：${row.count} 次，累计 ${row.totalMs} ms`"
            >
              {{ row.label }} {{ row.avgMs }}ms
            </span>
          </div>
          <p v-if="enrichProgress.throughput" class="ms-hint ms-block">
            本进程近 {{ enrichWindowMin }} 分钟：
            完成 {{ enrichProgress.throughput.done_per_min }} 条/分钟
            （累计 {{ enrichProgress.throughput.done_total }}）· {{ enrichIdleHint }}
          </p>
          <p class="ms-hint ms-block">
            Worker {{ enrichProgress.workers }} 线程 · {{ enrichProgress.enabled ? '运行中' : '已停用' }}
            <el-button size="small" text :loading="enrichProgressLoading" @click="loadEnrichProgress">
              刷新
            </el-button>
          </p>
        </div>
      </div>
    </div>
  </div>
</template>
