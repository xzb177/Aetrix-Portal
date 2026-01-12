<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { RefreshCw, TrendingUp, Clock, Users, Film, Award } from 'lucide-vue-next'
import { http } from '@/utils/request'

interface WatchStats {
  total_users: number
  users_with_emby: number
  total_watch_minutes: number
  avg_watch_minutes: number
  daily_active_users: number
  weekly_active_users: number
  top_watchers: Array<{
    tg_id: number
    emby_account: string | null
    total_watch_minutes: number
    total_watch_hours: number
  }>
}

const loading = ref(false)
const stats = ref<WatchStats | null>(null)

const loadStats = async () => {
  loading.value = true
  try {
    stats.value = await http.get<WatchStats>('/emby/stats')
  } catch (error) {
    console.error('加载 Emby 统计失败:', error)
  } finally {
    loading.value = false
  }
}

const formatMinutes = (minutes: number) => {
  if (minutes < 60) return `${minutes}分钟`
  return `${(minutes / 60).toFixed(1)}小时`
}

const getRankColor = (index: number) => {
  const colors = ['text-amber-400', 'text-gray-400', 'text-amber-600']
  return colors[index] || 'text-gray-500'
}

const getRankBg = (index: number) => {
  const bgs = ['bg-amber-400/20', 'bg-gray-400/20', 'bg-amber-600/20']
  return bgs[index] || 'bg-gray-500/20'
}

onMounted(() => {
  loadStats()
})
</script>

<template>
  <div class="emby-page">
    <!-- 刷新按钮 -->
    <div class="page-actions">
      <button class="btn-secondary btn-icon" @click="loadStats" :disabled="loading">
        <RefreshCw :size="18" :class="{ 'animate-spin': loading }" />
        刷新数据
      </button>
    </div>

    <!-- 加载状态 -->
    <div v-if="loading" class="stats-grid">
      <div v-for="i in 4" :key="i" class="stats-card shimmer">
        <div class="shimmer-icon"></div>
        <div class="shimmer-line shimmer-line-lg"></div>
        <div class="shimmer-line shimmer-line-sm"></div>
      </div>
    </div>

    <!-- 统计数据 -->
    <template v-else-if="stats">
      <!-- 统计卡片 -->
      <div class="stats-grid">
        <!-- 总用户数 -->
        <div class="stats-card">
          <div class="stats-icon stats-icon-blue">
            <Users :size="22" />
          </div>
          <div class="stats-content">
            <p class="stats-label">总用户数</p>
            <p class="stats-value">{{ stats.total_users.toLocaleString() }}</p>
            <div class="stats-extra">
              <span class="stats-text">已绑定: {{ stats.users_with_emby }}</span>
            </div>
          </div>
        </div>

        <!-- 总观影时长 -->
        <div class="stats-card">
          <div class="stats-icon stats-icon-purple">
            <Clock :size="22" />
          </div>
          <div class="stats-content">
            <p class="stats-label">总观影时长</p>
            <p class="stats-value">{{ (stats.total_watch_minutes / 60).toFixed(0) }}</p>
            <div class="stats-extra">
              <span class="stats-text">小时</span>
            </div>
          </div>
        </div>

        <!-- 平均观影 -->
        <div class="stats-card">
          <div class="stats-icon stats-icon-emerald">
            <Film :size="22" />
          </div>
          <div class="stats-content">
            <p class="stats-label">平均观影</p>
            <p class="stats-value">{{ stats.avg_watch_minutes }}</p>
            <div class="stats-extra">
              <span class="stats-text">分钟/人</span>
            </div>
          </div>
        </div>

        <!-- 日活/周活 -->
        <div class="stats-card">
          <div class="stats-icon stats-icon-amber">
            <TrendingUp :size="22" />
          </div>
          <div class="stats-content">
            <p class="stats-label">日活用户</p>
            <p class="stats-value">{{ stats.daily_active_users }}</p>
            <div class="stats-extra">
              <span class="stats-text">周活: {{ stats.weekly_active_users }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 观影排行榜 -->
      <div class="card table-card">
        <div class="table-header">
          <div class="flex items-center gap-2">
            <Award :size="18" class="text-amber-400" />
            <span class="font-semibold text-white">观影时长排行 Top 10</span>
          </div>
        </div>
        <div class="table-wrapper">
          <table>
            <thead>
              <tr>
                <th class="w-20">排名</th>
                <th class="table-hide-mobile">用户ID</th>
                <th>Emby账号</th>
                <th>观影时长</th>
                <th>观影小时</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(user, index) in stats.top_watchers" :key="user.tg_id">
                <td>
                  <span :class="['rank-badge', getRankBg(index), getRankColor(index)]">
                    {{ index + 1 }}
                  </span>
                </td>
                <td class="table-hide-mobile user-id">{{ user.tg_id }}</td>
                <td class="user-emby">{{ user.emby_account || '-' }}</td>
                <td class="user-time">{{ formatMinutes(user.total_watch_minutes) }}</td>
                <td class="user-hours">{{ user.total_watch_hours }} 小时</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
/* ==================== Page Layout ==================== */
.emby-page {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}





.btn-icon {
  gap: 0.5rem;
}

/* ==================== Stats Grid ==================== */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 1.5rem;
}

@media (max-width: 1024px) {
  .stats-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 640px) {
  .stats-grid {
    grid-template-columns: 1fr;
  }
}

/* ==================== Shimmer Loading ==================== */
.shimmer {
  position: relative;
  overflow: hidden;
}

.shimmer::before {
  content: '';
  position: absolute;
  top: 0;
  left: -100%;
  width: 100%;
  height: 100%;
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.03), transparent);
  animation: shimmer 1.5s infinite;
}

@keyframes shimmer {
  0% {
    left: -100%;
  }
  100% {
    left: 100%;
  }
}

.shimmer-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.05);
  margin-bottom: 1rem;
}

.shimmer-line {
  height: 12px;
  background: rgba(255, 255, 255, 0.05);
  border-radius: 4px;
  margin-bottom: 0.5rem;
}

.shimmer-line-lg {
  width: 60%;
}

.shimmer-line-sm {
  width: 30%;
}

/* ==================== Table Card ==================== */
.table-card {
  overflow: hidden;
}

.table-wrapper {
  overflow-x: auto;
}

table {
  width: 100%;
  border-collapse: collapse;
}

thead th {
  padding: 1rem 1rem;
  text-align: left;
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  border-bottom: 1px solid var(--border-color);
  background: rgba(255, 255, 255, 0.02);
  white-space: nowrap;
}

tbody tr {
  border-bottom: 1px solid var(--border-color);
  transition: background 0.15s ease;
}

tbody tr:last-child {
  border-bottom: none;
}

tbody tr:hover {
  background: rgba(255, 255, 255, 0.03);
}

tbody td {
  padding: 1rem;
  font-size: 0.875rem;
  color: var(--text-primary);
}

.user-id {
  font-weight: 500;
  color: var(--brand-primary);
}

.user-emby {
  color: var(--text-primary);
}

.user-time {
  color: var(--text-secondary);
}

.user-hours {
  color: var(--text-primary);
}

/* ==================== Rank Badge ==================== */
.rank-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  font-size: 0.875rem;
  font-weight: 600;
}

/* ==================== Mobile Responsive ==================== */
@media (max-width: 640px) {
</style>
