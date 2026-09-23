<script setup lang="ts">
/**
 * 客户端策略（v2.26.0）
 *
 * 一句话回答「客户端这边到底允许做什么」：
 *
 * - **转码**：允不允许服务端转码、同时几路、码率上限（省 CPU / 省上行）；
 * - **客户端准入**：哪些 UA 不许进（老版本、盗版客户端），或反过来只允许白名单；
 * - **下载与设备**：是否允许下载、每人几台设备、超限是拒绝还是自动踢最久未用的
 *   （这一组原来在「系统设置」里，属于「客户端能做什么」，搬到这里）。
 *
 * 策略落在 SystemConfig 里，EM 与 EA 共用同一个库 → 面板上改完，出流的 EA 立刻生效。
 * 判定口径：**管理员不受限**（排障时不能被自己的策略挡住）；所有开关缺省 = 与升级前一致。
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  AlertTriangle, Download, Gauge, RefreshCw, Save, ShieldBan, Smartphone, Tv,
} from 'lucide-vue-next'
import { fetchPlaybackPolicy, updatePlaybackPolicy } from '@/api/admin'
// 下载与设备风控落在经济设置里（同一批 SystemConfig 键），这里只是换个更顺手的入口
import { fetchEconomySettings, updateEconomySettings } from '@/api/economy'
import type { PlaybackPolicy, PlaybackRuntime } from '@/types'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
// 这两组策略都由服务端限定为超级管理员（见 backend/admin_roles.py 的前缀规则），
// 所以只有一个口径：不是 super 就只读
const isSuper = computed(() => auth.admin?.is_super !== false)

const loading = ref(false)
const savingPolicy = ref(false)
const savingOps = ref(false)

const policy = ref<PlaybackPolicy>({
  transcode_enabled: true,
  max_concurrent_transcodes: 0,
  max_bitrate_kbps: 0,
  blocked_agents: '',
  allowed_agents: '',
})
const runtime = ref<PlaybackRuntime | null>(null)

/** 下载与设备风控（与「系统设置」共用同一批键，这里只是换个更顺手的入口） */
const ops = ref({ allow_download: 'true', device_limit_per_user: '0', device_limit_auto_evict: 'false' })

const PLAYBACK_NODE_LABEL: Record<string, string> = {
  ea: '分离部署的 EA 节点',
  external: '已有 Emby 服',
  panel: '面板自己（一体化）',
}

async function load() {
  loading.value = true
  try {
    const [p, s] = await Promise.all([
      fetchPlaybackPolicy(),
      fetchEconomySettings().catch(() => ({ settings: {} as Record<string, string> })),
    ])
    policy.value = p.policy
    runtime.value = p.runtime
    ops.value = {
      allow_download: s.settings.allow_download ?? '',
      device_limit_per_user: s.settings.device_limit_per_user ?? '',
      device_limit_auto_evict: s.settings.device_limit_auto_evict ?? '',
    }
  } catch {
    /* 拦截器已提示 */
  } finally {
    loading.value = false
  }
}

onMounted(load)

async function savePolicy() {
  savingPolicy.value = true
  try {
    const res = await updatePlaybackPolicy(policy.value)
    policy.value = res.policy
    ElMessage.success('播放策略已保存（出流的节点下次判定即生效）')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '保存失败')
  } finally {
    savingPolicy.value = false
  }
}

async function saveOps() {
  savingOps.value = true
  try {
    await updateEconomySettings({ ...ops.value })
    ElMessage.success('下载与设备策略已保存')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '保存失败')
  } finally {
    savingOps.value = false
  }
}

const blockedCount = computed(
  () => (policy.value.blocked_agents || '').split(/[,，\n]/).filter((v) => v.trim()).length,
)
const idleSeconds = computed(() => Math.round(runtime.value?.idle_timeout_seconds ?? 0))
</script>

<template>
  <div class="admin-page">
    <div class="admin-page-header">
      <div>
        <h1 class="admin-page-title">客户端策略</h1>
        <p class="admin-page-subtitle">
          转码、清晰度与客户端准入：改完对面板与出流的节点同时生效（管理员不受这些策略限制）
        </p>
      </div>
      <div class="admin-page-actions">
        <el-button :loading="loading" @click="load"><RefreshCw :size="15" /></el-button>
      </div>
    </div>

    <el-alert v-if="!isSuper" type="warning" :closable="false" show-icon class="warn">
      <template #title>保存需要超级管理员角色</template>
      <template #default>你可以查看当前策略，但保存会被服务端拒绝。</template>
    </el-alert>

    <!-- 运行态：改上限之前先知道现在跑到什么程度 -->
    <section v-if="runtime" class="admin-card runtime-card">
      <div class="card-header">
        <h2><Gauge :size="15" /> 运行态<span class="range-hint">本进程</span></h2>
        <span class="hint">分离部署时转码跑在 EA 上，这里的数字是面板本机的</span>
      </div>
      <div class="runtime-grid">
        <div class="rt-item">
          <b :class="{ warn: runtime.active_transcodes > 0 }">{{ runtime.active_transcodes }}</b>
          <em>正在转码</em>
        </div>
        <div class="rt-item">
          <b>{{ policy.max_concurrent_transcodes || runtime.capacity }}</b>
          <em>{{ policy.max_concurrent_transcodes ? '策略上限' : '内置上限' }}</em>
        </div>
        <div class="rt-item">
          <b>{{ idleSeconds }}s</b>
          <em>闲置回收</em>
        </div>
        <div class="rt-item">
          <b :class="{ warn: !runtime.ffmpeg_available }">{{ runtime.ffmpeg_available ? '可用' : '未安装' }}</b>
          <em>ffmpeg</em>
        </div>
        <div class="rt-item">
          <b>{{ PLAYBACK_NODE_LABEL[runtime.playback_node] || runtime.playback_node }}</b>
          <em>当前出流</em>
        </div>
      </div>
      <p class="runtime-foot">
        内置上限 {{ runtime.capacity }} 路（来自 <code>EMBY_MAX_TRANSCODES</code> 或 CPU 核数）；
        超上限时只拒绝**新的**转码请求，不会中断正在看的人。
      </p>
    </section>

    <!-- 转码与清晰度 -->
    <section class="admin-card">
      <div class="card-header">
        <h2><Tv :size="15" /> 转码与清晰度</h2>
        <el-button type="primary" :loading="savingPolicy" :disabled="!isSuper" @click="savePolicy">
          <Save :size="14" style="margin-right: 4px" />保存
        </el-button>
      </div>

      <div class="field-row">
        <div class="field-main">
          <label>允许服务端转码</label>
          <p class="field-hint">
            关闭后只放直连 / 直接播放：省 CPU 与上行，但客户端兼容性会变差
            （网页端播放器遇到不支持的编码会播不了）。
          </p>
        </div>
        <el-switch v-model="policy.transcode_enabled" :disabled="!isSuper" />
      </div>

      <div class="field-row">
        <div class="field-main">
          <label>并发转码上限</label>
          <p class="field-hint">
            0 = 用进程内置上限（默认按 CPU 核数）。设成具体值后，满了会**拒绝新的转码请求**
            并提示稍后再试，而不是把整台机器的 CPU 打满、所有人一起卡。
          </p>
        </div>
        <el-input-number
          v-model="policy.max_concurrent_transcodes"
          :min="0" :max="200"
          :disabled="!isSuper"
        />
      </div>

      <div class="field-row">
        <div class="field-main">
          <label>码率上限</label>
          <p class="field-hint">
            单位 kbps，0 = 不限。客户端就算要 40Mbps 也只按上限给，且直连判定会跟着收紧
            （超过上限的条目改走转码），适合上行有限的部署。
          </p>
        </div>
        <el-input-number
          v-model="policy.max_bitrate_kbps"
          :min="0" :max="200000" :step="1000"
          :disabled="!isSuper"
        />
      </div>
    </section>

    <!-- 客户端准入 -->
    <section class="admin-card">
      <div class="card-header">
        <h2><ShieldBan :size="15" /> 客户端准入</h2>
        <span class="badge-hint">{{ blockedCount }} 条黑名单规则</span>
      </div>

      <div class="field-row column">
        <label>客户端黑名单（UA 子串，逗号分隔）</label>
        <el-input
          v-model="policy.blocked_agents"
          type="textarea"
          :rows="2"
          :disabled="!isSuper"
          placeholder="例如：Old-TV, Emby/2.0, 盗版播放器"
        />
        <p class="field-hint">
          按子串匹配（不区分大小写）：命中就拒绝，连播放信息都拿不到。
          <b>管理员不受限</b>，排障时不会被自己的规则挡住。
        </p>
      </div>

      <div class="field-row column">
        <label>客户端白名单（填了就只放行列表内的客户端）</label>
        <el-input
          v-model="policy.allowed_agents"
          type="textarea"
          :rows="2"
          :disabled="!isSuper"
          placeholder="例如：Emby, Infuse, SenPlayer（留空 = 不限制）"
        />
        <p class="field-hint">
          白名单优先于黑名单；开启后无法识别 UA 的请求（脚本 / 未知客户端）也会被拒。
        </p>
      </div>

      <div class="save-row">
        <el-button type="primary" :loading="savingPolicy" :disabled="!isSuper" @click="savePolicy">
          <Save :size="14" style="margin-right: 4px" />保存客户端准入
        </el-button>
      </div>
    </section>

    <!-- 下载与设备（原来在系统设置里） -->
    <section class="admin-card">
      <div class="card-header">
        <h2><Download :size="15" /> 下载与设备</h2>
        <el-button :loading="savingOps" :disabled="!isSuper" @click="saveOps">
          <Save :size="14" style="margin-right: 4px" />保存
        </el-button>
      </div>

      <div class="field-row">
        <div class="field-main">
          <label>允许下载</label>
          <p class="field-hint">
            关闭后客户端下载（含 <code>/Items/{id}/File</code>）一并拦截，管理员不受限。
          </p>
        </div>
        <el-switch
          :model-value="ops.allow_download === 'true'"
          :disabled="!isSuper"
          @update:model-value="(v: boolean) => (ops.allow_download = v ? 'true' : 'false')"
        />
      </div>

      <div class="field-row">
        <div class="field-main">
          <label>设备上限（台 / 人）</label>
          <p class="field-hint">0 或不填表示不限；只统计近 30 天活跃设备。</p>
        </div>
        <el-input v-model="ops.device_limit_per_user" class="num-input" :disabled="!isSuper" />
      </div>

      <div class="field-row">
        <div class="field-main">
          <label>超限自动踢人</label>
          <p class="field-hint">
            开启则自动移除最久未使用的设备；关闭则直接拒绝新设备登录。
          </p>
        </div>
        <el-switch
          :model-value="ops.device_limit_auto_evict === 'true'"
          :disabled="!isSuper"
          @update:model-value="(v: boolean) => (ops.device_limit_auto_evict = v ? 'true' : 'false')"
        />
      </div>

      <p class="runtime-foot">
        <Smartphone :size="13" /> 逐台设备与登录日志在「设备与安全 / 登录日志」；这里的策略只决定
        「多一台设备时怎么处理」。
      </p>
    </section>

    <el-alert type="info" :closable="false" show-icon class="warn">
      <template #title>为什么这些策略在这里，而系统设置在别处</template>
      <template #default>
        这里只放「客户端能做什么」（转码、清晰度、准入、下载与设备）；
        「站点怎么运营」（注册、支付、付费墙、邀请返利）仍然在系统设置里。
      </template>
    </el-alert>

    <p v-if="!isSuper" class="readonly-foot">
      <AlertTriangle :size="13" />
      当前账号不是超级管理员：这一页可以查看，保存会被服务端拒绝（这些策略会改变所有人的播放体验）。
    </p>
  </div>
</template>

<style scoped>
.warn { margin-top: 14px; }
.hint, .badge-hint { font-size: var(--font-size-xs); color: var(--text-muted); }
.range-hint { font-size: var(--font-size-xs); color: var(--text-muted); font-weight: 400; }

.runtime-card { margin-bottom: 14px; }
.runtime-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
  gap: 12px;
}
.rt-item { display: flex; flex-direction: column; gap: 2px; }
.rt-item b {
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
}
.rt-item b.warn { color: var(--warning); }
.rt-item em { font-style: normal; font-size: var(--font-size-xs); color: var(--text-muted); }
.runtime-foot {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 14px 0 0;
  font-size: var(--font-size-xs);
  color: var(--text-muted);
  flex-wrap: wrap;
}

.admin-card + .admin-card { margin-top: 14px; }

.field-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 0;
  border-bottom: 1px solid var(--border-subtle);
}
.field-row:last-of-type { border-bottom: none; }
.field-row.column { flex-direction: column; align-items: stretch; gap: 8px; }
.field-main { min-width: 0; }
.field-row label { font-size: var(--font-size-sm); font-weight: var(--font-weight-medium); color: var(--text-primary); }
.field-hint { margin: 4px 0 0; font-size: var(--font-size-xs); color: var(--text-muted); line-height: 1.6; }
.num-input { width: 120px; }
.save-row { display: flex; justify-content: flex-end; padding-top: 4px; }
code {
  padding: 1px 5px;
  border-radius: var(--radius-sm);
  background: var(--bg-glass);
  font-size: 11.5px;
}
.readonly-foot {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 12px 0 0;
  font-size: var(--font-size-xs);
  color: var(--warning);
}
</style>
