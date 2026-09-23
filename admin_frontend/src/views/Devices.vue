<script setup lang="ts">
/**
 * 设备风控（v2.6.0）
 *
 * 用户第三方客户端（Infuse / Forward / SenPlayer 等）登录即登记设备。
 * 这里做跨用户审查：查设备、封禁（同时吊销令牌）与移除（踢下线）。
 */
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { RefreshCw, Ban, CircleCheck, LogOut, Search } from 'lucide-vue-next'
import { fetchDeviceStats, fetchDevices, removeDevice, setDeviceBlocked } from '@/api/admin'
import type { DeviceRow, DeviceStats } from '@/types'
import DataTable from '@/components/DataTable.vue'
import type { DataColumn } from '@/components/DataTable.vue'

/** 手机卡片：用户为标题，设备/客户端/IP/首次/最近活跃做键值行 */
const columns: DataColumn[] = [
  { key: 'username', label: '用户', width: 150, mobile: 'title' },
  { key: 'name', label: '设备', minWidth: 170 },
  { key: 'client', label: '客户端', width: 150 },
  { key: 'ip', label: 'IP', width: 130 },
  { key: 'first_seen_at', label: '首次', width: 150, mobile: 'hide' },
  { key: 'last_seen_at', label: '最近活跃', width: 130 },
  { key: 'is_blocked', label: '状态', width: 90 },
  // 封禁 / 移除收进详情弹窗：行里只留一个入口，也顺便把设备 ID / 版本 / 首末次时间看全
  { key: 'actions', label: '操作', width: 100, fixed: 'right', align: 'right' },
]

const devices = ref<DeviceRow[]>([])
const stats = ref<DeviceStats | null>(null)
const loading = ref(false)
const total = ref(0)
const filters = ref({ keyword: '', only_blocked: false })

async function load() {
  loading.value = true
  try {
    const [list, stat] = await Promise.all([
      fetchDevices({
        keyword: filters.value.keyword || undefined,
        only_blocked: filters.value.only_blocked || undefined,
        limit: 300,
      }),
      fetchDeviceStats(),
    ])
    devices.value = list.devices
    total.value = list.total
    stats.value = stat
  } finally {
    loading.value = false
  }
}

onMounted(load)

// ==================== 设备详情弹窗（v2.29.0） ====================
// 以前封禁 / 移除是行里两个按钮，点下去只有一句确认框，看不到设备 ID、客户端版本、
// 首末次时间；现在一行一个「详情」按钮，处置动作也在弹窗里完成（理由说明就在按钮旁）。
const detail = ref({ visible: false, row: null as DeviceRow | null })

function openDetail(row: DeviceRow) {
  detail.value = { visible: true, row }
}

/** 动作做完刷新列表，并把弹窗里的行换成最新快照（状态徽标就地变化） */
async function afterAction(row: DeviceRow) {
  await load()
  const fresh = devices.value.find(
    (d) => d.device_id === row.device_id && d.user_id === row.user_id,
  )
  if (fresh) {
    detail.value.row = fresh
  } else {
    // 被移除了：弹窗没有可描述的对象，关掉并说明
    detail.value.visible = false
    ElMessage.info('设备已移除，客户端需重新登录')
  }
}

async function toggleBlock(row: DeviceRow) {
  const action = row.is_blocked ? '解封' : '封禁'
  try {
    await ElMessageBox.confirm(
      row.is_blocked
        ? `确认解封 ${row.username} 的设备「${row.name || row.device_id}」？`
        : `封禁后该设备已签发的令牌会被吊销，且无法再次登录。确认封禁 ${row.username} 的设备「${row.name || row.device_id}」？`,
      `${action}设备`,
      { type: 'warning' },
    )
  } catch {
    return
  }
  const res = await setDeviceBlocked(row.user_id, row.device_id, !row.is_blocked)
  ElMessage.success(res.message)
  await afterAction(row)
}

async function kick(row: DeviceRow) {
  try {
    await ElMessageBox.confirm(
      `移除后该设备令牌立即失效，客户端需重新登录。确认移除 ${row.username} 的设备？`,
      '移除设备',
      { type: 'warning' },
    )
  } catch {
    return
  }
  const res = await removeDevice(row.user_id, row.device_id)
  ElMessage.success(res.message)
  await afterAction(row)
}

function fmt(s: string | null): string {
  if (!s) return '—'
  return s.slice(0, 16).replace('T', ' ')
}

function ago(s: string | null): string {
  if (!s) return '—'
  const diff = Date.now() - new Date(s).getTime()
  if (diff < 0) return '刚刚'
  const mins = Math.floor(diff / 60000)
  if (mins < 60) return `${mins} 分钟前`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours} 小时前`
  return `${Math.floor(hours / 24)} 天前`
}
</script>

<template>
  <div class="admin-page">
    <div class="admin-page-header">
      <div>
        <h1 class="admin-page-title">设备与安全</h1>
        <p class="admin-page-subtitle">
          第三方客户端登录设备审查 —— 封禁会同时吊销令牌，移除等于踢下线
        </p>
      </div>
      <div class="toolbar">
        <el-button @click="load"><RefreshCw :size="14" /></el-button>
      </div>
    </div>

    <div v-if="stats" class="stat-grid">
      <div class="stat-tile">
        <div class="stat-label">设备总数</div>
        <div class="stat-value">{{ stats.total }}</div>
        <div class="stat-hint">来自 {{ stats.users }} 位用户</div>
      </div>
      <div class="stat-tile">
        <div class="stat-label">近 {{ stats.active_days }} 天活跃</div>
        <div class="stat-value">{{ stats.active_30d }}</div>
        <div class="stat-hint">长期未活跃的设备不计入上限</div>
      </div>
      <div class="stat-tile" :class="{ 'is-danger': stats.blocked > 0 }">
        <div class="stat-label">已封禁</div>
        <div class="stat-value">{{ stats.blocked }}</div>
        <div class="stat-hint">封禁设备无法再次登录</div>
      </div>
      <div class="stat-tile">
        <div class="stat-label">每用户上限</div>
        <div class="stat-value">{{ stats.limit_per_user || '不限' }}</div>
        <div class="stat-hint">
          {{ stats.auto_evict ? '超限自动踢最久未用' : '超限直接拒绝新设备' }}
        </div>
      </div>
    </div>

    <div class="admin-card filter-bar">
      <el-input
        v-model="filters.keyword"
        placeholder="搜索用户名 / 设备 / 客户端 / IP"
        style="max-width: 280px"
        clearable
        @keyup.enter="load"
        @clear="load"
      >
        <template #prefix><Search :size="14" /></template>
      </el-input>
      <el-checkbox v-model="filters.only_blocked" @change="load">只看已封禁</el-checkbox>
      <el-button @click="load">查询</el-button>
      <span class="filter-count">共 {{ total }} 台</span>
    </div>

    <div class="admin-card">
      <DataTable :rows="devices" :columns="columns" :loading="loading" empty="暂无设备记录">
        <template #cell-username="{ row }">
          <span class="user-name">{{ row.username }}</span>
          <span v-if="!row.is_user_active" class="mini-badge danger">已禁用</span>
        </template>

        <template #cell-name="{ row }">
          <div class="dev-name">{{ row.name || '未命名设备' }}</div>
          <div class="dev-id">{{ row.device_id }}</div>
        </template>

        <template #cell-client="{ row }">
          <div>{{ row.client || '—' }}</div>
          <div class="dev-id">v{{ row.app_version || '-' }}</div>
        </template>

        <template #cell-ip="{ row }">
          <span class="mono">{{ row.ip || '—' }}</span>
        </template>

        <template #cell-first_seen_at="{ row }">{{ fmt(row.first_seen_at) }}</template>

        <template #cell-last_seen_at="{ row }">
          <span :class="{ muted: !row.is_online_recent }">{{ ago(row.last_seen_at) }}</span>
        </template>

        <template #cell-is_blocked="{ row }">
          <span class="mini-badge" :class="row.is_blocked ? 'danger' : 'ok'">
            {{ row.is_blocked ? '已封禁' : '正常' }}
          </span>
        </template>

        <template #cell-actions="{ row }">
          <!-- 一个入口：详情 + 封禁 / 解封 / 移除 都在弹窗里 -->
          <el-button size="small" plain @click="openDetail(row)">详情</el-button>
        </template>
      </DataTable>
    </div>

    <!-- 设备详情与处置（弹窗）：先把这台设备是什么说清楚，再动手 -->
    <el-dialog v-model="detail.visible" title="设备详情与处置" width="540px">
      <div v-if="detail.row" class="dev-detail">
        <div class="kv-list">
          <div class="kv-row"><span class="kv-key">所属用户</span>
            <span class="kv-value">
              {{ detail.row.username }}
              <span v-if="!detail.row.is_user_active" class="mini-badge danger">账号已禁用</span>
            </span>
          </div>
          <div class="kv-row"><span class="kv-key">设备</span>
            <span class="kv-value">{{ detail.row.name || '未命名设备' }}</span>
          </div>
          <div class="kv-row"><span class="kv-key">设备 ID</span>
            <span class="kv-value mono">{{ detail.row.device_id }}</span>
          </div>
          <div class="kv-row"><span class="kv-key">客户端</span>
            <span class="kv-value">{{ detail.row.client || '—' }}<span class="dev-ver">v{{ detail.row.app_version || '-' }}</span></span>
          </div>
          <div class="kv-row"><span class="kv-key">IP</span>
            <span class="kv-value mono">{{ detail.row.ip || '—' }}</span>
          </div>
          <div class="kv-row"><span class="kv-key">首次出现</span><span class="kv-value">{{ fmt(detail.row.first_seen_at) }}</span></div>
          <div class="kv-row"><span class="kv-key">最近活跃</span>
            <span class="kv-value">
              {{ fmt(detail.row.last_seen_at) }}
              <span class="dev-ago">{{ ago(detail.row.last_seen_at) }}</span>
            </span>
          </div>
          <div class="kv-row"><span class="kv-key">当前状态</span>
            <span class="kv-value">
              <span class="mini-badge" :class="detail.row.is_blocked ? 'danger' : 'ok'">
                {{ detail.row.is_blocked ? '已封禁' : '正常' }}
              </span>
            </span>
          </div>
        </div>

        <p class="dev-actions-hint">
          封禁会同时吊销该设备已签发的令牌，且它无法再次登录；移除等于踢下线，
          客户端需重新登录（两者都不影响用户的会员与订阅）。
        </p>
      </div>

      <template #footer>
        <div class="dev-footer">
          <el-button type="warning" plain @click="detail.row && kick(detail.row)">
            <LogOut :size="13" style="margin-right: 4px" />移除（踢下线）
          </el-button>
          <div class="dev-footer-right">
            <el-button @click="detail.visible = false">关闭</el-button>
            <el-button
              v-if="detail.row"
              :type="detail.row.is_blocked ? 'success' : 'danger'"
              @click="detail.row && toggleBlock(detail.row)"
            >
              <component
                :is="detail.row.is_blocked ? CircleCheck : Ban"
                :size="13"
                style="margin-right: 4px"
              />
              {{ detail.row.is_blocked ? '解封这台设备' : '封禁这台设备' }}
            </el-button>
          </div>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.toolbar { display: flex; gap: 8px; }

.stat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: 12px;
  margin-bottom: 14px;
}
.stat-card {
  background: var(--bg-card);
  border: 1px solid var(--border-color, #262626);
  border-radius: 12px;
  padding: 14px 16px;
}
.stat-card.danger { border-color: rgba(239, 68, 68, 0.45); }
.stat-label { font-size: 12px; color: var(--color-text-secondary, #a3a3a3); }
.stat-value { font-size: 22px; font-weight: 600; margin: 4px 0 2px; }
.stat-hint { font-size: 11px; color: var(--color-text-muted, #737373); }

.filter-bar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 14px; }
.filter-count { font-size: 12px; color: var(--color-text-muted, #737373); margin-left: auto; }

.dev-name { font-size: 13px; }
.dev-id {
  font-family: ui-monospace, monospace;
  font-size: 11px;
  color: var(--color-text-muted, #737373);
  word-break: break-all;
}
.mini-badge {
  display: inline-block;
  margin-left: 6px;
  padding: 1px 7px;
  border-radius: 999px;
  font-size: 11px;
  background: var(--border-color, #262626);
  color: var(--color-text-secondary, #a3a3a3);
}
.mini-badge.ok { background: rgba(34, 197, 94, 0.15); color: #4ade80; }
.mini-badge.danger { background: rgba(239, 68, 68, 0.15); color: #f87171; }
.muted { color: var(--color-text-muted, #737373); }

/* 「已封禁」那块统计立牌要能看出异常：类名写了却没定义过（对照页定义了同样的规则）*/
.stat-tile.is-danger { border-color: var(--danger-border); }

/* 设备详情弹窗：详情用全局 .kv-list，只补两处间距 */
.dev-detail { display: flex; flex-direction: column; gap: 12px; }
/* 弹窗里的键值行靠左：值与值之间会很长（设备 ID / 提示文案），右对齐读不动 */
.dev-detail .kv-row .kv-value { text-align: left; }
.dev-ver { margin-left: 6px; font-size: 11px; color: var(--color-text-muted, #737373); }
.dev-ago { margin-left: 6px; font-size: 11px; color: var(--color-text-muted, #737373); }
.dev-actions-hint {
  margin: 0;
  font-size: 12px;
  line-height: 1.7;
  color: var(--color-text-secondary, #a3a3a3);
  background: var(--bg-inset, rgba(255, 255, 255, 0.03));
  border-radius: 8px;
  padding: 10px 12px;
}
.dev-footer { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
.dev-footer-right { display: flex; gap: 8px; }
</style>
