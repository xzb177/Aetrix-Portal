<script setup lang="ts">
/**
 * StatCard - 统计卡片组件
 *
 * 用于展示关键指标数据，包含图标、数值、标签和趋势。
 *
 * @props
 * - icon: 图标组件
 * - value: 数值（支持带单位的字符串）
 * - label: 标签文字
 * - trend: 趋势文字（如 '+12%'）
 * - trendUp: 趋势是否向上（绿色为正，红色为负）
 * - color: 主题颜色 ('success' | 'warning' | 'danger' | 'info')
 */

interface Props {
  icon?: string
  value: string | number
  label: string
  trend?: string
  trendUp?: boolean
  color?: 'success' | 'warning' | 'danger' | 'info'
}

const props = withDefaults(defineProps<Props>(), {
  color: 'success',
  trendUp: true
})
</script>

<template>
  <div class="ui-stat-card">
    <div v-if="icon" class="ui-stat-card__icon" :class="`ui-stat-card__icon--${color}`">
      <img v-if="icon" :src="icon" alt="" class="ui-stat-card__icon-img">
    </div>
    <div class="ui-stat-card__content">
      <div class="ui-stat-card__value">{{ value }}</div>
      <div class="ui-stat-card__label">{{ label }}</div>
    </div>
    <div v-if="trend" class="ui-stat-card__trend" :class="{ 'ui-stat-card__trend--up': trendUp }">
      {{ trend }}
    </div>
  </div>
</template>

<style scoped>
.ui-stat-card {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  background: var(--card-bg);
  border: 1px solid var(--card-border);
  border-radius: var(--radius-lg);
  padding: var(--space-md);
  box-shadow: var(--card-shadow);
  transition: background-color var(--duration-fast) var(--ease-out);
}

.ui-stat-card:active {
  background: var(--card-bg-hover);
}

/* 图标容器 */
.ui-stat-card__icon {
  width: 40px;
  height: 40px;
  border-radius: var(--radius-sm);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.ui-stat-card__icon--success { background: var(--color-success-bg); }
.ui-stat-card__icon--warning { background: var(--color-warning-bg); }
.ui-stat-card__icon--danger { background: var(--color-danger-bg); }
.ui-stat-card__icon--info { background: var(--color-info-bg); }

.ui-stat-card__icon-img {
  width: 24px;
  height: 24px;
}

/* 内容区域 */
.ui-stat-card__content {
  flex: 1;
  min-width: 0;
}

.ui-stat-card__value {
  font-size: 24px;
  font-weight: 600;
  line-height: 1.2;
  color: var(--text-title-color);
}

.ui-stat-card__label {
  font-size: var(--text-caption-size);
  font-weight: var(--text-caption-weight);
  line-height: var(--text-caption-line);
  color: var(--text-caption-color);
  margin-top: 2px;
}

/* 趋势 */
.ui-stat-card__trend {
  font-size: var(--text-caption-size);
  font-weight: 500;
  color: var(--color-danger);
  flex-shrink: 0;
}

.ui-stat-card__trend--up {
  color: var(--color-success);
}
</style>
