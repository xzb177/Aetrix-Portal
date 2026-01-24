<script setup lang="ts">
import { computed } from 'vue'

interface Badge {
  id: number
  code: string
  name: string
  name_en: string
  description: string
  icon: string
  color: string
  rarity: 'common' | 'rare' | 'epic' | 'legendary'
  category: string
  unlocked: boolean
  progress: number
  max_progress: number
  unlocked_at?: string
}

interface Props {
  badge: Badge
  size?: 'sm' | 'md' | 'lg'
  showProgress?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  size: 'md',
  showProgress: true
})

const emit = defineEmits<{
  click: [badge: Badge]
}>()

// 稀有度配置
const rarityConfig = {
  common: { color: '#9E9E9E', bg: 'rgba(158, 158, 158, 0.1)', label: '普通' },
  rare: { color: '#2196F3', bg: 'rgba(33, 150, 243, 0.1)', label: '稀有' },
  epic: { color: '#9C27B0', bg: 'rgba(156, 39, 176, 0.1)', label: '史诗' },
  legendary: { color: '#FFD700', bg: 'rgba(255, 215, 0, 0.15)', label: '传说' }
}

// 进度百分比
const progressPercent = computed(() => {
  if (props.badge.max_progress <= 0) return 0
  return Math.min(100, (props.badge.progress / props.badge.max_progress) * 100)
})

// 尺寸配置
const sizeConfig = {
  sm: { icon: '24px', container: '48px', fontSize: '10px' },
  md: { icon: '36px', container: '64px', fontSize: '12px' },
  lg: { icon: '48px', container: '80px', fontSize: '14px' }
}

const currentSize = computed(() => sizeConfig[props.size])

// 点击徽章
const handleClick = () => {
  emit('click', props.badge)
}
</script>

<template>
  <div
    class="badge-item"
    :class="[
      `badge-${size}`,
      `badge-${badge.rarity}`,
      { 'badge-unlocked': badge.unlocked, 'badge-locked': !badge.unlocked }
    ]"
    @click="handleClick"
  >
    <!-- 徽章图标 -->
    <div class="badge-icon" :style="{ width: currentSize.container, height: currentSize.container }">
      <span class="badge-emoji">{{ badge.unlocked ? badge.icon : '🔒' }}</span>
      <!-- 稀有度光晕 -->
      <div v-if="badge.unlocked && badge.rarity !== 'common'" class="badge-glow" :style="{ backgroundColor: badge.color }"></div>
    </div>

    <!-- 徽章信息 -->
    <div v-if="size !== 'sm'" class="badge-info">
      <span class="badge-name">{{ badge.name }}</span>
      <span class="badge-rarity" :style="{ color: rarityConfig[badge.rarity].color }">
        {{ rarityConfig[badge.rarity].label }}
      </span>
    </div>

    <!-- 进度条 -->
    <div v-if="showProgress && !badge.unlocked && size !== 'sm'" class="badge-progress">
      <div class="progress-bar">
        <div class="progress-fill" :style="{ width: progressPercent + '%', backgroundColor: badge.color }"></div>
      </div>
      <span class="progress-text">{{ badge.progress }}/{{ badge.max_progress }}</span>
    </div>
  </div>
</template>

<style scoped>
.badge-item {
  display: inline-flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem;
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.3s ease;
  position: relative;
  overflow: hidden;
}

.badge-item.badge-sm {
  flex-direction: row;
  gap: 0.375rem;
  padding: 0.375rem 0.5rem;
}

.badge-unlocked {
  background: rgba(103, 58, 183, 0.08);
}

.badge-locked {
  background: rgba(255, 255, 255, 0.03);
  opacity: 0.6;
}

.badge-item:hover {
  transform: translateY(-2px);
}

.badge-unlocked:hover {
  background: rgba(103, 58, 183, 0.15);
  box-shadow: 0 4px 20px rgba(103, 58, 183, 0.2);
}

.badge-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  position: relative;
  background: rgba(255, 255, 255, 0.05);
}

.badge-emoji {
  font-size: v-bind('currentSize.icon');
  line-height: 1;
  z-index: 1;
}

.badge-glow {
  position: absolute;
  inset: -4px;
  border-radius: 50%;
  opacity: 0.3;
  filter: blur(8px);
  animation: pulse 2s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 0.2; transform: scale(1); }
  50% { opacity: 0.4; transform: scale(1.05); }
}

/* 稀有度特殊效果 */
.badge-legendary .badge-glow {
  animation: legendary-pulse 3s ease-in-out infinite;
}

@keyframes legendary-pulse {
  0%, 100% { opacity: 0.3; }
  50% { opacity: 0.6; }
}

.badge-info {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.125rem;
}

.badge-name {
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--text-primary, rgba(255, 255, 255, 0.92));
}

.badge-rarity {
  font-size: v-bind('currentSize.fontSize');
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.badge-progress {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  width: 100%;
  max-width: 80px;
}

.progress-bar {
  height: 4px;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 2px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  border-radius: 2px;
  transition: width 0.5s ease;
}

.progress-text {
  font-size: 0.625rem;
  color: var(--text-muted, rgba(255, 255, 255, 0.5));
  text-align: center;
}

/* SM 尺寸特殊样式 */
.badge-sm .badge-info {
  flex-direction: row;
  gap: 0.375rem;
}

.badge-sm .badge-name {
  font-size: 0.625rem;
}
</style>
