<script setup lang="ts">
/**
 * 正在播放 —— 我的播放会话（设备 / 客户端 / IP / 进度 / 结束播放）
 *
 * 从「观看记录」页抽出来：这块讲的是**控制**（哪台设备在放、能不能停），
 * 不是「我看过什么」。所以它现在挂在个人中心（控制面板），观看记录只留历史。
 *
 * 数据源：GET /api/user/emby/sessions（读本地会话表，不触发扫描）。
 * 组件自己加载，挂到哪页都能用。
 */
import { ref, onMounted } from 'vue'
import { RouterLink } from 'vue-router'
import { CircleStop, MonitorSmartphone, Wifi } from 'lucide-vue-next'
import { embyApi, type MyPlaybackSession } from '@/api'
import { useToast } from '@/composables/useToast'

const toast = useToast()

const sessions = ref<MyPlaybackSession[]>([])
const loading = ref(true)
const stopping = ref<string | null>(null)

function typeLabel(t?: string | null) {
  return ({ Movie: '电影', Series: '剧集', Episode: '剧集' } as Record<string, string>)[t || ''] || '影片'
}

function fmtTime(iso?: string | null) {
  if (!iso) return '—'
  const date = new Date(iso)
  const diff = Date.now() - date.getTime()
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  return `${Math.floor(hours / 24)} 天前`
}

async function load() {
  loading.value = true
  try {
    const res = await embyApi.getSessions()
    sessions.value = res.sessions || []
  } catch {
    sessions.value = []
  } finally {
    loading.value = false
  }
}

async function stopSession(session: MyPlaybackSession) {
  stopping.value = session.session_key
  try {
    await embyApi.stopSession(session.session_key)
    toast.success(`已结束「${session.device || '未知设备'}」上的播放`)
    sessions.value = sessions.value.filter((s) => s.session_key !== session.session_key)
  } catch (err: any) {
    const detail = err?.response?.data?.detail
    toast.error(typeof detail === 'string' ? detail : '结束播放失败')
  } finally {
    stopping.value = null
  }
}

defineExpose({ reload: load })

onMounted(load)
</script>

<template>
  <div class="sessions">
    <div v-if="loading" class="skeleton-list">
      <div class="au-skeleton skel-row" />
      <div class="au-skeleton skel-row" />
    </div>

    <div v-else-if="sessions.length === 0" class="au-empty session-empty">
      <MonitorSmartphone :size="26" />
      <p>当前没有正在播放的会话</p>
      <p class="empty-sub">在任意设备上开始播放后，会在这里显示并可远程结束</p>
    </div>

    <div v-else class="session-list">
      <div v-for="s in sessions" :key="s.session_key" class="session-row">
        <div class="session-icon">
          <MonitorSmartphone :size="17" />
        </div>

        <div class="session-main">
          <div class="session-title">
            <RouterLink class="session-name" :to="`/media/${s.item_id}`">{{ s.item }}</RouterLink>
            <span class="au-badge au-badge-cyan">{{ typeLabel(s.item_type) }}</span>
            <span v-if="s.is_paused" class="au-badge au-badge-amber">已暂停</span>
          </div>
          <div class="session-meta">
            <span>{{ s.device || '未知设备' }}</span>
            <span v-if="s.client" class="meta-sep">·</span>
            <span v-if="s.client">{{ s.client }}</span>
            <span v-if="s.play_method" class="meta-sep">·</span>
            <span v-if="s.play_method" class="method">{{ s.play_method === 'Transcode' ? '转码' : '直连' }}</span>
            <span v-if="s.remote_addr" class="meta-sep">·</span>
            <span v-if="s.remote_addr" class="addr"><Wifi :size="11" />{{ s.remote_addr }}</span>
          </div>
          <div class="session-progress">
            <div class="bar"><div class="bar-fill" :style="{ width: s.progress + '%' }" /></div>
            <span class="bar-text">{{ s.progress }}% · {{ fmtTime(s.updated_at) }}</span>
          </div>
        </div>

        <button
          class="au-btn au-btn-danger au-btn-sm stop-btn"
          :disabled="stopping === s.session_key"
          @click="stopSession(s)"
        >
          <CircleStop :size="13" />
          {{ stopping === s.session_key ? '结束中' : '结束' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.session-list { display: flex; flex-direction: column; gap: 0.5rem; }

.session-row {
  display: flex;
  align-items: center;
  gap: 0.875rem;
  padding: 0.75rem 0.875rem;
  border-radius: var(--au-r-md);
  background: var(--au-surface-2);
  border: 1px solid var(--au-border);
}

.session-icon {
  width: 34px;
  height: 34px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--au-r-sm);
  background: var(--au-primary-soft);
  color: var(--au-primary);
}

.session-main { flex: 1; min-width: 0; }

.session-title {
  display: flex;
  align-items: center;
  gap: 0.4375rem;
  flex-wrap: wrap;
}

.session-name {
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--au-text);
  text-decoration: none;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}

.session-name:hover { color: var(--au-primary); }

.session-meta {
  display: flex;
  align-items: center;
  gap: 0.3125rem;
  margin-top: 0.1875rem;
  font-size: 0.75rem;
  color: var(--au-text-3);
  flex-wrap: wrap;
}

.session-meta .addr { display: inline-flex; align-items: center; gap: 0.1875rem; }
.session-meta .method { color: var(--au-violet); }
.meta-sep { opacity: 0.5; }

.session-progress {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-top: 0.375rem;
}

.bar {
  flex: 1;
  max-width: 260px;
  height: 4px;
  border-radius: 2px;
  background: var(--au-border-strong);
  overflow: hidden;
}

.bar-fill { height: 100%; background: var(--au-gradient); }
.bar-text { font-size: 0.6875rem; color: var(--au-text-4); white-space: nowrap; }

.stop-btn { flex-shrink: 0; }

.session-empty { padding: 1.25rem 0 0.5rem; }
.session-empty .empty-sub { font-size: 0.75rem; margin-top: 0.25rem; }

.skeleton-list { display: flex; flex-direction: column; gap: 0.5rem; }
.skel-row { height: 64px; border-radius: var(--au-r-md); }

@media (max-width: 560px) {
  .session-row { flex-wrap: wrap; }
  .stop-btn { width: 100%; justify-content: center; }
}
</style>
