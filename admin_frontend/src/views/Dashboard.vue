<script setup lang="ts">
/** 数据概览：系统统计 + 自建 Emby 实时数据 + 播放统计 */
import { onMounted, ref } from 'vue'
import { Film, MessageSquareDashed, Play, Radio, Ticket, Users } from 'lucide-vue-next'
import { fetchOverview, fetchPlaybackStats } from '@/api/admin'
import type { OverviewStats, PlaybackStats } from '@/types'

const overview = ref<OverviewStats | null>(null)
const playback = ref<PlaybackStats | null>(null)
const loading = ref(true)

onMounted(async () => {
  try {
    const [o, p] = await Promise.all([fetchOverview(), fetchPlaybackStats()])
    overview.value = o
    playback.value = p
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="admin-page">
    <div v-if="loading" class="page-loading">加载中…</div>

    <template v-else-if="overview">
      <!-- 系统统计 -->
      <div class="stat-grid">
        <div class="stat-tile">
          <div class="stat-label"><Users :size="13" /> 总用户 / 活跃</div>
          <div class="stat-value">
            {{ overview.users.total }}<span class="stat-sub"> / {{ overview.users.active }}</span>
          </div>
        </div>
        <div class="stat-tile">
          <div class="stat-label"><Film :size="13" /> 媒体条目</div>
          <div class="stat-value stat-accent">{{ overview.emby.total_items }}</div>
        </div>
        <div class="stat-tile">
          <div class="stat-label"><Radio :size="13" /> 在线会话</div>
          <div class="stat-value" :class="{ 'stat-accent': overview.emby.active_sessions > 0 }">
            {{ overview.emby.active_sessions }}
          </div>
        </div>
        <div class="stat-tile">
          <div class="stat-label"><Ticket :size="13" /> 待处理工单</div>
          <div class="stat-value">{{ overview.tickets.open }}</div>
        </div>
        <div class="stat-tile">
          <div class="stat-label"><MessageSquareDashed :size="13" /> 待审求片</div>
          <div class="stat-value">{{ overview.media_seeks.pending }}</div>
        </div>
      </div>

      <!-- 播放统计 -->
      <div class="stats-two-col" v-if="playback">
        <div class="admin-card">
          <div class="card-header">
            <h2><Play :size="15" /> 今日播放</h2>
          </div>
          <div class="today-stats">
            <div class="today-item">
              <div class="today-num">{{ playback.today.plays }}</div>
              <div class="today-cap">播放次数</div>
            </div>
            <div class="today-item">
              <div class="today-num">{{ playback.today.users }}</div>
              <div class="today-cap">观看用户</div>
            </div>
          </div>

          <div class="card-header" style="margin-top: 18px">
            <h2>用户播放排行 <span class="range-hint">近 7 天</span></h2>
          </div>
          <div v-if="playback.user_ranking.length === 0" class="empty-hint">暂无播放数据</div>
          <div v-for="(u, i) in playback.user_ranking" :key="u.username" class="rank-row">
            <span class="rank-index">{{ i + 1 }}</span>
            <span class="rank-name">{{ u.username }}</span>
            <span class="rank-value">{{ u.plays }} 次</span>
          </div>
        </div>

        <div class="admin-card">
          <div class="card-header">
            <h2>热门内容 <span class="range-hint">近 7 天</span></h2>
          </div>
          <div v-if="playback.item_ranking.length === 0" class="empty-hint">暂无播放数据</div>
          <div v-for="(it, i) in playback.item_ranking" :key="it.name" class="rank-row">
            <span class="rank-index">{{ i + 1 }}</span>
            <span class="rank-name">
              {{ it.name }}
              <span class="rank-type">{{ it.type === 'episode' ? '剧集' : it.type === 'movie' ? '电影' : it.type }}</span>
            </span>
            <span class="rank-value">{{ it.plays }} 次</span>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.page-loading { text-align: center; color: var(--color-text-secondary, #a3a3a3); padding: 60px 0; }
.stat-sub { font-size: 16px; color: var(--color-text-secondary, #a3a3a3); font-weight: 500; }
.stat-label { display: flex; align-items: center; gap: 6px; }

.stats-two-col {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 14px;
}

.card-header h2 {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  margin: 0 0 12px;
}

.range-hint { font-size: 11px; color: var(--color-text-muted, #737373); font-weight: 400; }

.today-stats { display: flex; gap: 24px; }
.today-num { font-size: 26px; font-weight: 700; color: #10b981; }
.today-cap { font-size: 12px; color: var(--color-text-secondary, #a3a3a3); }

.rank-name { flex: 1; font-size: 13px; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rank-type { font-size: 11px; color: var(--color-text-muted, #737373); margin-left: 6px; }
.rank-value { font-size: 12px; color: var(--color-text-secondary, #a3a3a3); }
.empty-hint { font-size: 13px; color: var(--color-text-muted, #737373); padding: 12px 0; }
</style>
