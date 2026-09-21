<script setup lang="ts">
/**
 * 底部导航坞 — 移动端（≤900px）的主导航
 *
 * 与桌面顶栏共用 primaryNav（src/config/navigation.ts）：条目、顺序、图标完全一致，
 * 所以小屏用户看到的不是「另一套导航」，是同一个导航换成了拇指够得着的形态。
 * 中心凸起的「签到」圆盘已去掉：那是 App 的营销位，放在导航条里既抢主色，
 * 又让 5 个入口的主次变得莫名其妙。
 */
import { RouterLink, useRoute } from 'vue-router'
import { primaryNav } from '@/config/navigation'

const route = useRoute()

function isActive(path: string) {
  if (path === '/') return route.path === '/'
  return route.path.startsWith(path)
}
</script>

<template>
  <nav class="app-dock" aria-label="主导航">
    <RouterLink
      v-for="t in primaryNav"
      :key="t.path"
      :to="t.path"
      class="dock-tab"
      :class="{ active: isActive(t.path) }"
    >
      <span class="dock-icon">
        <component :is="t.icon" :size="19" />
      </span>
      <span class="dock-label">{{ t.name }}</span>
    </RouterLink>
  </nav>
</template>

<style scoped>
.app-dock {
  display: none;
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 55;
  padding: 6px 8px calc(6px + env(safe-area-inset-bottom, 0px));
  background: var(--au-overlay);
  backdrop-filter: blur(18px);
  -webkit-backdrop-filter: blur(18px);
  border-top: 1px solid var(--au-border);
}

.dock-tab {
  flex: 1 1 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  min-width: 0;
  padding: 3px 0 1px;
  text-decoration: none;
  color: var(--au-text-4);
  transition: color var(--au-fast) var(--au-ease);
  -webkit-tap-highlight-color: transparent;
}

.dock-tab.active { color: var(--au-primary); }
.dock-tab:not(.active):hover { color: var(--au-text-2); }

/* 选中态用一枚贴着图标的胶囊，和顶栏导航的激活样式同一套语言 */
.dock-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 46px;
  height: 27px;
  border-radius: var(--au-r-full);
  transition: background-color var(--au-fast) var(--au-ease);
}

.dock-tab.active .dock-icon { background: var(--au-primary-soft); }

.dock-label {
  font-size: 0.625rem;
  font-weight: 600;
  letter-spacing: 0.02em;
  white-space: nowrap;
}

@media (max-width: 900px) {
  .app-dock { display: flex; }
}
</style>
