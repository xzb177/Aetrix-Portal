<script setup lang="ts">
/**
 * 观影画像页面
 * 展示用户的观影偏好、类型分布、推荐
 */
import { ref, onMounted } from 'vue'
import { viewingApi } from '@/api/innovations'
import type { ViewingProfile } from '@/api/types'
import { BarChart3, Film, TrendingUp, AlertTriangle } from 'lucide-vue-next'

const profile = ref<ViewingProfile | null>(null)
const recommendations = ref<any[]>([])
const loading = ref(true)

async function loadData() {
  loading.value = true
  try {
    const [p, r] = await Promise.all([
      viewingApi.getProfile(),
      viewingApi.getRecommendations()
    ])
    profile.value = p as unknown as ViewingProfile
    recommendations.value = r as unknown as any[]
  } catch (e) {
    console.error('加载观影画像失败:', e)
  } finally {
    loading.value = false
  }
}

function getGenreColor(index: number): string {
  const colors = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6']
  return colors[index % colors.length]
}

onMounted(loadData)
</script>

<template>
  <div class="profile-page">
    <div class="page-header">
      <h1><BarChart3 :size="24" /> 观影画像</h1>
      <p class="subtitle">你的观影习惯分析</p>
    </div>

    <div v-if="loading" class="loading">加载中...</div>

    <div v-else-if="profile && !('error' in profile)" class="profile-content">
      <!-- 概览卡片 -->
      <div class="stats-row">
        <div class="stat-card">
          <Film :size="20" />
          <span class="value">{{ profile.total_items }}</span>
          <span class="label">观看内容</span>
        </div>
        <div class="stat-card">
          <TrendingUp :size="20" />
          <span class="value">{{ profile.favorite_genres?.length || 0 }}</span>
          <span class="label">偏好类型</span>
        </div>
        <div class="stat-card" :class="{ warning: profile.drop_off_rate > 30 }">
          <AlertTriangle :size="20" />
          <span class="value">{{ profile.drop_off_rate }}%</span>
          <span class="label">弃剧率</span>
        </div>
      </div>

      <!-- 偏好类型 -->
      <div class="section" v-if="profile.top_genres?.length">
        <h2>🎬 偏好类型</h2>
        <div class="genre-bars">
          <div v-for="(g, i) in profile.top_genres" :key="g.name" class="genre-bar">
            <span class="genre-name">{{ g.name }}</span>
            <div class="bar-track">
              <div
                class="bar-fill"
                :style="{
                  width: `${(g.count / (profile.top_genres[0]?.count || 1)) * 100}%`,
                  backgroundColor: getGenreColor(i)
                }"
              />
            </div>
            <span class="genre-count">{{ g.count }}</span>
          </div>
        </div>
      </div>

      <!-- 类型分布 -->
      <div class="section" v-if="profile.type_distribution">
        <h2>📊 内容类型分布</h2>
        <div class="type-grid">
          <div v-for="(count, type) in profile.type_distribution" :key="type" class="type-item">
            <span class="type-name">{{ type === 'Movie' ? '电影' : type === 'Series' ? '剧集' : type }}</span>
            <span class="type-count">{{ count }}</span>
          </div>
        </div>
      </div>

      <!-- 智能推荐 -->
      <div class="section" v-if="recommendations.length">
        <h2>💡 个性化建议</h2>
        <div class="rec-list">
          <div v-for="rec in recommendations" :key="rec.type" class="rec-item">
            <span class="rec-icon">{{ rec.type === 'genre_recommendation' ? '🎯' : '💭' }}</span>
            <div>
              <p class="rec-text">{{ rec.reason || rec.message }}</p>
              <p class="rec-priority" :class="rec.priority">{{ rec.priority === 'high' ? '强烈推荐' : '建议' }}</p>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div v-else class="empty">
      <p>暂无观影数据，多看几部片子就有了 🎬</p>
    </div>
  </div>
</template>

<style scoped>
.profile-page { padding: 1rem; max-width: 600px; margin: 0 auto; }
.page-header { margin-bottom: 1.5rem; }
.page-header h1 { display: flex; align-items: center; gap: 0.5rem; font-size: 1.5rem; }
.subtitle { color: #888; }
.stats-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.75rem; margin-bottom: 1.5rem; }
.stat-card {
  text-align: center; padding: 1rem; background: #f9fafb; border-radius: 12px;
  display: flex; flex-direction: column; align-items: center; gap: 0.25rem;
}
.stat-card.warning { background: #fef2f2; }
.stat-card .value { font-size: 1.5rem; font-weight: 700; }
.stat-card .label { font-size: 0.75rem; color: #888; }
.section { margin-bottom: 1.5rem; }
.section h2 { font-size: 1.1rem; margin-bottom: 0.75rem; }
.genre-bars { display: grid; gap: 0.5rem; }
.genre-bar { display: flex; align-items: center; gap: 0.5rem; }
.genre-name { width: 60px; font-size: 0.875rem; text-align: right; }
.bar-track { flex: 1; height: 20px; background: #f3f4f6; border-radius: 10px; overflow: hidden; }
.bar-fill { height: 100%; border-radius: 10px; transition: width 0.5s; }
.genre-count { width: 30px; font-size: 0.875rem; color: #666; }
.type-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 0.5rem; }
.type-item {
  display: flex; justify-content: space-between; padding: 0.5rem 0.75rem;
  background: #f9fafb; border-radius: 8px;
}
.type-name { color: #555; }
.type-count { font-weight: 600; }
.rec-list { display: grid; gap: 0.75rem; }
.rec-item { display: flex; gap: 0.75rem; padding: 0.75rem; background: #f0f9ff; border-radius: 10px; }
.rec-icon { font-size: 1.25rem; }
.rec-text { font-size: 0.875rem; }
.rec-priority { font-size: 0.75rem; margin-top: 0.25rem; }
.rec-priority.high { color: #ef4444; }
.rec-priority.medium { color: #f59e0b; }
.empty, .loading { text-align: center; padding: 3rem; color: #888; }
</style>
