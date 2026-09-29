<script setup lang="ts">
/**
 * 可折叠的说明面板（v2.32.0）
 *
 * 「角色说明 / 支持的来源类型 / 服务端护栏」这类整块解释文字以前是常驻版面的：
 * 打开页面第一眼看到的全是说明，真正要用的清单（管理员列表、挂载列表）被挤到屏幕外，
 * 手机上一次滑动都到不了头。收成一行标题后默认什么都不占，需要时点开。
 *
 * 展开状态按 `storage-key` 记在 localStorage（与左侧导航分组折叠同一个思路）：
 * 看过一次的人下次进来还是开着的，不会被重新收回去。
 *
 * 用法：标题与一句话摘要由调用方给，内容放默认插槽（自带卡片外观，直接当 section 用）。
 *
 * 卡片盒子在这里自己画（令牌与 .admin-card 同源），而不是给根节点加 `.admin-card`：
 * 那层全局规则的 padding 只在 `.admin-layout .admin-content` 下才生效、而且更具体，
 * 想用负外边距把标题行铺满卡片就会在窄屏（padding 变小）时溢出。自己定 padding，
 * 标题行才能整行可点、悬停底色也不越出圆角。
 */
import { onMounted, ref, type Component } from 'vue'
import { ChevronDown } from 'lucide-vue-next'

const props = withDefaults(defineProps<{
  /** 标题（收起时也一直显示，要有信息量） */
  title: string
  /** 收起时跟在标题后的一句话：不点开也知道里面讲什么 */
  summary?: string
  /** 标题图标（lucide 组件） */
  icon?: Component
  /** 记住展开状态的键；不传则只在本次会话内有效 */
  storageKey?: string
}>(), { summary: '', storageKey: '' })

const STORAGE_PREFIX = 'admin.notice.'
const open = ref(false)

function lsKey(): string {
  return props.storageKey ? `${STORAGE_PREFIX}${props.storageKey}` : ''
}

onMounted(() => {
  const key = lsKey()
  if (!key) return
  try {
    // 只认显式的 '1'：没记过（含本地存储不可用）就保持收起
    open.value = localStorage.getItem(key) === '1'
  } catch {
    /* 隐私模式 / 禁用了本地存储：保持默认收起即可 */
  }
})

function toggle() {
  open.value = !open.value
  const key = lsKey()
  if (!key) return
  try {
    localStorage.setItem(key, open.value ? '1' : '0')
  } catch {
    /* 记不住就算了，不影响展开 */
  }
}
</script>

<template>
  <section class="notice-panel">
    <button type="button" class="notice-head" :aria-expanded="open" @click="toggle">
      <span class="notice-title">
        <component :is="icon" v-if="icon" :size="15" />
        {{ title }}
      </span>
      <span v-if="summary" class="notice-summary">{{ summary }}</span>
      <ChevronDown :size="15" class="notice-caret" :class="{ open }" />
    </button>
    <el-collapse-transition>
      <div v-show="open" class="notice-body">
        <slot />
      </div>
    </el-collapse-transition>
  </section>
</template>

<style scoped>
/* 与 .admin-card 同一套令牌，但内边距由自己定（标题行要整行可点，见文件头注释） */
.notice-panel {
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
  overflow: hidden;
}

.notice-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
  min-height: var(--touch-target-min);
  margin: 0;
  padding: var(--space-3) var(--space-4);
  border: 0;
  background: none;
  cursor: pointer;
  text-align: left;
  color: var(--text-primary);
  font-size: var(--font-size-md);
  font-weight: var(--font-weight-semibold);
  line-height: var(--line-height-normal);
  transition: background var(--transition-fast);
}

.notice-head:hover { background: var(--bg-hover); }

.notice-title {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
}

.notice-summary {
  color: var(--text-muted);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-normal);
}

.notice-caret {
  margin-left: auto;
  flex-shrink: 0;
  color: var(--text-muted);
  transition: transform var(--transition-fast);
}

.notice-caret.open { transform: rotate(180deg); }

.notice-head:focus-visible { outline: 2px solid var(--border-focus); outline-offset: -2px; }
.notice-head:hover .notice-title,
.notice-head:focus-visible .notice-title { color: var(--primary); }

.notice-body { padding: 0 var(--space-4) var(--space-4); }

/* 断点与 styles/responsive.css 的卡片节奏对齐（否则旁边卡片变小圆角，这里还是个大的） */
@media (max-width: 1024px) {
  .notice-panel { border-radius: var(--radius-md); }
  .notice-head { padding: var(--space-3) var(--space-3); }
  .notice-body { padding: 0 var(--space-3) var(--space-3); }
}

@media (max-width: 640px) {
  /* 手机一行放不下「标题 + 摘要 + 箭头」：摘要换行，别把标题挤断 */
  .notice-head { flex-wrap: wrap; }
  .notice-summary { flex: 1 1 100%; }
}
</style>
