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
import { computed, onMounted, reactive, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { KeyRound, PlugZap, RefreshCw, RotateCw, Wand2 } from 'lucide-vue-next'
import {
  addTmdbKey,
  bindTmdb,
  deleteTmdbKey,
  fetchEnrichProgress,
  fetchTmdbKeys,
  fetchTmdbMirror,
  previewTmdb,
  rescrapeItem,
  resetTmdbKeyCooldown,
  saveTmdbMirror,
  testTmdbKeys,
} from '@/api/admin'
import type { TmdbKeyPoolRow, TmdbKeysStatus, TmdbMirror, TmdbTestResult } from '@/api/admin'
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

// ==================== TMDB 密钥池与镜像（Phase 6a） ====================

const tmdbKeys = ref<TmdbKeysStatus | null>(null)
const tmdbKeysLoading = ref(false)
const newKey = ref('')
const keyAdding = ref(false)
const keyBusyIndex = ref<number | null>(null)
const keyTests = ref<TmdbTestResult[]>([])
const keyTesting = ref(false)
const mirror = ref<TmdbMirror | null>(null)
const mirrorForm = reactive({ api_base: '', image_base: '' })
const mirrorSaving = ref(false)

async function loadTmdbKeys() {
  tmdbKeysLoading.value = true
  try {
    tmdbKeys.value = await fetchTmdbKeys()
  } catch {
    tmdbKeys.value = null
  } finally {
    tmdbKeysLoading.value = false
  }
}

/** 密钥池每一行：序号 + 掩码 + 状态（冷却中的写出“还要 xx 秒”与原因） */
const keyRows = computed<TmdbKeyPoolRow[]>(() => tmdbKeys.value?.pool || [])

function keyStatus(row: TmdbKeyPoolRow): { text: string; cls: string } {
  if (row.cooling) return { text: `冷却中 · 还剩 ${row.cooldown_remaining}s`, cls: 'warn' }
  if (row.current) return { text: '正在使用', cls: 'ok' }
  return { text: '待命', cls: 'muted' }
}

/** 冷却原因 + 命中次数（悬停才看，避免表格过宽） */
function keyStatusTitle(row: TmdbKeyPoolRow): string {
  if (!row.reason) return ''
  return `${row.reason}（本进程命中 ${row.hits} 次）`
}

async function addKey() {
  const value = newKey.value.trim()
  if (!value) {
    ElMessage.warning('请填写 TMDB API Key')
    return
  }
  keyAdding.value = true
  try {
    const res = await addTmdbKey(value)
    newKey.value = ''
    if (res.effective) ElMessage.success(`已添加，密钥池现有 ${res.count} 把`)
    else ElMessage.warning(res.note || '已写入，但暂不生效')
    keyTests.value = []
    await loadTmdbKeys()
  } catch {
    /* 拦截器已提示（如 409：已经在池子里） */
  } finally {
    keyAdding.value = false
  }
}

async function removeKey(row: TmdbKeyPoolRow) {
  keyBusyIndex.value = row.index
  try {
    const res = await deleteTmdbKey(row.index)
    ElMessage.success(`已删除 ${res.removed}，还剩 ${res.count} 把`)
    keyTests.value = keyTests.value.filter((t) => t.index !== row.index)
    await loadTmdbKeys()
  } catch {
    /* 拦截器已提示 */
  } finally {
    keyBusyIndex.value = null
  }
}

/** 一键测试全部：测不通的那几把会被后端直接放进冷却 */
async function testAllKeys() {
  keyTesting.value = true
  try {
    const res = await testTmdbKeys()
    keyTests.value = res.results
    const okCount = res.results.filter((r) => r.ok).length
    if (!res.results.length) ElMessage.warning('密钥池是空的：先添加一把')
    else if (okCount === res.results.length) ElMessage.success(`${okCount} 把全部可用`)
    else ElMessage.warning(`${okCount}/${res.results.length} 把可用，其余已转入冷却`)
    await loadTmdbKeys()
  } catch {
    /* 拦截器已提示 */
  } finally {
    keyTesting.value = false
  }
}

async function resetCooldowns() {
  try {
    const res = await resetTmdbKeyCooldown()
    ElMessage.success(res.cleared ? `已清除 ${res.cleared} 把的冷却` : '当前没有密钥在冷却')
    await loadTmdbKeys()
  } catch {
    /* 拦截器已提示 */
  }
}

async function loadMirror() {
  try {
    mirror.value = await fetchTmdbMirror()
    mirrorForm.api_base = mirror.value.api_base
    mirrorForm.image_base = mirror.value.image_base
  } catch {
    mirror.value = null
  }
}

async function saveMirror() {
  mirrorSaving.value = true
  try {
    const res = await saveTmdbMirror({
      api_base: mirrorForm.api_base.trim(),
      image_base: mirrorForm.image_base.trim(),
    })
    ElMessage.success('已保存并生效（图片地址下一次刮削就用镜像）')
    mirrorForm.api_base = res.api_base
    mirrorForm.image_base = res.image_base
    await Promise.all([loadMirror(), loadTmdbKeys()])
  } catch {
    /* 拦截器已提示（400 会带上具体哪个地址不合法） */
  } finally {
    mirrorSaving.value = false
  }
}

/** 恢复官方地址：两个输入框清空后保存即可 */
function restoreDefaultMirror() {
  mirrorForm.api_base = ''
  mirrorForm.image_base = ''
}

onMounted(() => {
  loadEnrichProgress().catch(() => undefined)
  loadTmdbKeys().catch(() => undefined)
  loadMirror().catch(() => undefined)
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
      <!-- 0. TMDB 密钥池与镜像（Phase 6a）：多把轮换、逐把增删、失效/限流自动冷却 -->
      <div class="admin-card ms-card ms-card-wide">
        <div class="card-header">
          <h2><KeyRound :size="16" style="margin-right: 6px" />TMDB 密钥池与镜像</h2>
          <div class="ms-facts">
            <span v-if="tmdbKeys" class="fact">
              来源：{{ tmdbKeys.source === 'env' ? '环境变量' : tmdbKeys.source === 'db' ? '后台填写' : '未配置' }}
            </span>
            <span v-if="tmdbKeys" class="fact">共 {{ tmdbKeys.count }} 把</span>
            <span v-if="tmdbKeys?.keys_cooling" class="fact warn">
              冷却中 {{ tmdbKeys.keys_cooling }}
            </span>
            <span v-if="tmdbKeys" class="fact">实际 {{ tmdbKeys.rate ?? 0 }}/秒（上限 {{ tmdbKeys.rate_ceiling ?? 0 }}）</span>
          </div>
        </div>
        <p class="ms-hint">
          多把密钥轮着：一把被限流（429）或失效（401）会自动冷却并切到下一把，
          冷却时长走配置（当前 429 {{ mirror?.cooldown_sec ?? '—' }} 秒 / 401
          {{ mirror?.invalid_cooldown_sec ?? '—' }} 秒）。密钥原文不会出现在接口里，只显示后 4 位。
        </p>
        <el-alert
          v-if="tmdbKeys?.env_present"
          type="warning"
          :closable="false"
          show-icon
          class="ms-alert"
        >
          环境变量 <code>TMDB_API_KEYS</code> 里已经有密钥，它优先于后台填写的池子：
          下面添加的密钥会存下来但<strong>暂不生效</strong>。
        </el-alert>

        <div v-if="tmdbKeysLoading && !tmdbKeys" class="ms-hint">加载中…</div>
        <div v-else-if="!tmdbKeys" class="ms-hint">读取密钥池失败，稍后点「刷新」重试。</div>
        <div v-else-if="!keyRows.length" class="ms-hint">
          还没有密钥：刮削会静默跳过。在下面添一把，或去「媒体库」页的 TMDB API Keys 批量粘贴。
        </div>
        <table v-else class="ms-table">
          <thead>
            <tr><th>#</th><th>密钥</th><th>状态</th><th>操作</th></tr>
          </thead>
          <tbody>
            <tr v-for="row in keyRows" :key="row.index">
              <td class="muted">{{ row.index }}</td>
              <td class="mono">{{ row.masked }}</td>
              <td>
                <span class="mini-badge" :class="keyStatus(row).cls" :title="keyStatusTitle(row)">
                  {{ keyStatus(row).text }}
                </span>
                <div v-if="row.reason" class="ms-sub muted">{{ row.reason }}</div>
              </td>
              <td>
                <el-button
                  size="small"
                  text
                  type="danger"
                  :loading="keyBusyIndex === row.index"
                  @click="removeKey(row)"
                >删除</el-button>
              </td>
            </tr>
          </tbody>
        </table>

        <div class="ms-actions">
          <el-input
            v-model="newKey"
            placeholder="粘贴一把新的 TMDB API Key"
            style="width: 320px"
            clearable
          />
          <el-button size="small" type="primary" :loading="keyAdding" @click="addKey">添加</el-button>
          <el-button size="small" :loading="keyTesting" @click="testAllKeys">
            <PlugZap :size="14" style="margin-right: 4px" />测试全部
          </el-button>
          <el-button size="small" :disabled="!tmdbKeys?.keys_cooling" @click="resetCooldowns">
            清除冷却
          </el-button>
          <el-button size="small" text :loading="tmdbKeysLoading" @click="loadTmdbKeys">
            <RefreshCw :size="14" />
          </el-button>
        </div>
        <div v-if="keyTests.length" class="ms-results">
          <div v-for="t in keyTests" :key="t.index" class="ms-result">
            <span class="mini-badge" :class="t.ok ? 'ok' : 'danger'">{{ t.ok ? '可用' : '不可用' }}</span>
            <span class="mono">{{ t.masked }}</span>
            <span class="muted">{{ t.message }}</span>
          </div>
        </div>

        <div class="ms-sub">镜像 / 反代地址（境内直连不通时填）</div>
        <p class="ms-hint">
          API 与图片 CDN <strong>分开配</strong>：常见情况是图片走镜像、API 直连（或反过来）。
          留空 = 用官方地址。环境变量 <code>TMDB_API_BASE</code> / <code>TMDB_IMAGE_BASE</code> 优先。
        </p>
        <div class="ms-actions">
          <el-input v-model="mirrorForm.api_base" placeholder="API 地址，如 https://tmdb.example.com/3" style="width: 300px" />
          <el-input v-model="mirrorForm.image_base" placeholder="图片 CDN，如 https://img.example.com/t/p" style="width: 300px" />
          <el-button size="small" type="primary" :loading="mirrorSaving" @click="saveMirror">保存镜像</el-button>
          <el-button size="small" text @click="restoreDefaultMirror">清空（恢复官方）</el-button>
        </div>
        <p v-if="mirror" class="ms-hint">
          当前生效：API <code class="mono">{{ mirror.api_base }}</code>
          {{ mirror.api_base_from_env ? '（来自环境变量，后台保存不生效）' : '' }}
          ｜图片 <code class="mono">{{ mirror.image_base }}</code>
          {{ mirror.image_base_from_env ? '（来自环境变量）' : '' }}
        </p>
      </div>
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
