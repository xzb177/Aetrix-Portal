<script setup lang="ts">
/**
 * 底部导航坞（≤768px 专用）
 *
 * 借鉴纸片人控制台的移动端形态：拇指区常驻 Tab 栏——毛玻璃底 + 1px 顶边 +
 * 当前项品牌色软底胶囊高亮。条目与顶栏主导航完全同源（primaryNav），
 * 「一个语义只有一个入口」：≥769px 整个坞不渲染，顶栏仍是唯一导航；
 * ≤768px 顶栏退成单行（品牌 + 资产 pill + 账号），主导航交给这里。
 *
 * 登录页与播放页沿用 App.vue 的 showChrome 口径，同样不渲染。
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
  <nav class="app-dock" aria-label="底部导航">
    <RouterLink
      v-for="item in primaryNav"
      :key="item.path"
      :to="item.path"
      class="dock-item"
      :class="{ 'dock-item-active': isActive(item.path) }"
      :aria-current="isActive(item.path) ? 'page' : undefined"
    >
      <span class="dock-ic">
        <component :is="item.icon" :size="20" :stroke-width="isActive(item.path) ? 2.2 : 1.8" />
      </span>
      <span class="dock-label">{{ item.name }}</span>
    </RouterLink>
  </nav>
</template>

<style scoped>
.app-dock {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 50;
  display: none;
  align-items: stretch;
  justify-content: space-around;
  padding: 0 0.5rem env(safe-area-inset-bottom);
  background: var(--au-overlay-menu);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border-top: 1px solid var(--au-border);
}

.dock-item {
  flex: 1;
  max-width: 96px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  padding: 0.5rem 0 0.375rem;
  text-decoration: none;
  color: var(--au-text-3);
  transition: color var(--au-fast) var(--au-ease);
}

.dock-ic {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 26px;
  border-radius: var(--au-r-full);
  transition: background var(--au-fast) var(--au-ease);
}

.dock-label {
  font-size: 0.6875rem;
  font-weight: 600;
  letter-spacing: 0.02em;
}

.dock-item-active { color: var(--au-primary); }
.dock-item-active .dock-ic { background: var(--au-primary-soft); }

@media (max-width: 768px) {
  .app-dock { display: flex; }
}
</style>
