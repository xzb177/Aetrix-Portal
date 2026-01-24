<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import BadgeItem from './BadgeItem.vue'
import { badgesApi } from '@/api'

interface Badge {
  id: number
  code: string
  name: string
  name_en: string
  description: string
  icon: string
  color: string
  rarity: string
  category: string
  unlocked: boolean
  progress: number
  max_progress: number
  unlocked_at?: string
}

interface Props {
  size?: 'sm' | 'md' | 'lg'
  filter?: 'all' | 'unlocked' | 'locked'
  limit?: number
}

const props = withDefaults(defineProps<Props>(), {
  size: 'md',
  filter: 'all',
  limit: 0
})

const emit = defineEmits<{
  badgeClick: [badge: Badge]
}>()

const loading = ref(true)
const badges = ref<Badge[]>([])
const total = ref(0)
const unlocked = ref(0)

// 解锁百分比
const unlockedPercent = computed(() => {
  if (total.value === 0) return 0
  return Math.round((unlocked.value / total.value) * 100)
})

// 过滤后的徽章
const filteredBadges = computed(() => {
  let result = badges.value

  if (props.filter === 'unlocked') {
    result = result.filter(b => b.unlocked)
  } else if (props.filter === 'locked') {
    result = result.filter(b => !b.unlocked)
  }

  if (props.limit > 0) {
    result = result.slice(0, props.limit)
  }

  return result
})

// 加载徽章数据
const loadBadges = async () => {
  loading.value = true
  try {
    const response = await badgesApi.getBadges() as any
    badges.value = response.badges || []
    total.value = response.total || 0
    unlocked.value = response.unlocked || 0
  } catch (error) {
    console.error('加载徽章失败:', error)
    badges.value = []
  } finally {
    loading.value = false
  }
}

// 刷新徽章
const refresh = () => {
  loadBadges()
}

// 处理徽章点击
const handleBadgeClick = (badge: Badge) => {
  emit('badgeClick', badge)
}

// 暴露方法
defineExpose({
  refresh
})

onMounted(() => {
  loadBadges()
})
</script>

<template>
  <div class="badge-list">
    <!-- 统计信息 -->
    <div v-if="!limit" class="badge-stats">
      <div class="stat-item">
        <span class="stat-value">{{ unlocked }}</span>
        <span class="stat-label">已解锁</span>
      </div>
      <div class="stat-divider"></div>
      <div class="stat-item">
        <span class="stat-value">{{ total }}</span>
        <span class="stat-label">总计</span>
      </div>
      <div class="stat-divider"></div>
      <div class="stat-item">
        <span class="stat-value">{{ unlockedPercent }}%</span>
        <span class="stat-label">完成度</span>
      </div>
    </div>

    <!-- 徽章网格 -->
    <div v-if="loading" class="badge-loading">
      <div class="skeleton-badge" v-for="i in 6" :key="i"></div>
    </div>

    <div v-else-if="filteredBadges.length === 0" class="badge-empty">
      <p>{{ filter === 'locked' ? '暂无未解锁徽章' : '暂无徽章' }}</p>
    </div>

    <div v-else class="badge-grid">
      <BadgeItem
        v-for="badge in filteredBadges"
        :key="badge.id"
        :badge="badge"
        :size="size"
        @click="handleBadgeClick"
      />
    </div>
  </div>
</template>

<style scoped>
.badge-list {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.badge-stats {
  display: flex;
  align-items: center;
  justify-content: space-around;
  padding: 1rem;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 12px;
  border: 1px solid rgba(255, 255, 255, 0.08);
}

.stat-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.25rem;
}

.stat-value {
  font-size: 1.5rem;
  font-weight: 700;
  color: var(--text-primary, rgba(255, 255, 255, 0.92));
}

.stat-label {
  font-size: 0.75rem;
  color: var(--text-muted, rgba(255, 255, 255, 0.5));
}

.stat-divider {
  width: 1px;
  height: 24px;
  background: rgba(255, 255, 255, 0.1);
}

.badge-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
}

.badge-loading {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
}

.skeleton-badge {
  width: 80px;
  height: 100px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.05);
  animation: skeleton-pulse 1.5s ease-in-out infinite;
}

@keyframes skeleton-pulse {
  0%, 100% { opacity: 0.5; }
  50% { opacity: 0.8; }
}

.badge-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 2rem;
  color: var(--text-muted, rgba(255, 255, 255, 0.5));
  font-size: 0.875rem;
  background: rgba(255, 255, 255, 0.02);
  border-radius: 12px;
}
</style>
