<script setup lang="ts">
/**
 * AppBar - 应用顶部导航栏组件
 *
 * 固定在页面顶部的导航栏，高度 56px，支持返回按钮、标题和右侧操作。
 *
 * @props
 * - title: 标题文字
 * - showBack: 是否显示返回按钮
 * - transparent: 是否透明背景
 */

interface Props {
  title?: string
  showBack?: boolean
  transparent?: boolean
}

defineProps<Props>()

const emit = defineEmits<{
  back: []
}>()

const handleBack = () => {
  emit('back')
}
</script>

<template>
  <header class="ui-appbar" :class="{ 'ui-appbar--transparent': transparent }">
    <div class="ui-appbar__content">
      <!-- 左侧：返回按钮 -->
      <button
        v-if="showBack"
        class="ui-appbar__back"
        @click="handleBack"
      >
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
          <path d="M15 18L9 12L15 6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </button>

      <!-- 中间：标题 -->
      <h1 class="ui-appbar__title">
        <slot name="title">{{ title }}</slot>
      </h1>

      <!-- 右侧：操作按钮 -->
      <div v-if="$slots.action" class="ui-appbar__action">
        <slot name="action" />
      </div>
    </div>
  </header>
</template>

<style scoped>
.ui-appbar {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  height: var(--appbar-height);
  background: var(--appbar-bg);
  backdrop-filter: var(--appbar-backdrop);
  -webkit-backdrop-filter: var(--appbar-backdrop);
  border-bottom: 1px solid var(--appbar-border);
  z-index: var(--z-appbar);
}

.ui-appbar--transparent {
  background: transparent;
  border-bottom-color: transparent;
}

.ui-appbar__content {
  display: flex;
  align-items: center;
  height: 100%;
  padding: 0 var(--space-md);
  max-width: 600px;
  margin: 0 auto;
}

.ui-appbar__back {
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: transparent;
  color: var(--text-body-color);
  cursor: pointer;
  border-radius: var(--radius-sm);
  flex-shrink: 0;
  margin-right: var(--space-xs);
}

.ui-appbar__back:active {
  background: rgba(255, 255, 255, 0.1);
}

.ui-appbar__title {
  flex: 1;
  font-size: var(--text-subtitle-size);
  font-weight: 600;
  line-height: 1.3;
  color: var(--text-title-color);
  margin: 0;
  text-align: center;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding: 0 8px;
}

.ui-appbar__action {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  margin-left: auto;
}
</style>
