<script setup lang="ts">
/**
 * 移动端底部导航坞 — 首页 / 媒体库 / 签到（中心凸起）/ 钱包 / 我的
 * ≥900px 隐藏（桌面端由顶部分组导航接管）。
 */
import { RouterLink, useRoute } from 'vue-router'
import { Clapperboard, Film, CalendarCheck, Wallet, User } from 'lucide-vue-next'

const route = useRoute()

const tabs = [
  { name: '首页', path: '/', icon: Clapperboard, featured: false },
  { name: '媒体库', path: '/media', icon: Film, featured: false },
  { name: '签到', path: '/checkin', icon: CalendarCheck, featured: true },
  { name: '钱包', path: '/wallet', icon: Wallet, featured: false },
  { name: '我的', path: '/profile', icon: User, featured: false },
]

function isActive(path: string) {
  if (path === '/') return route.path === '/'
  return route.path.startsWith(path)
}
</script>

<template>
  <nav class="app-dock" aria-label="底部导航">
    <RouterLink
      v-for="t in tabs"
      :key="t.path"
      :to="t.path"
      class="dock-tab"
      :class="{ active: isActive(t.path) }"
    >
      <span class="dock-icon" :class="{ 'featured-disc': t.featured }">
        <component :is="t.icon" :size="t.featured ? 18 : 20" />
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
  background: rgba(7, 11, 18, 0.92);
  backdrop-filter: blur(18px);
  -webkit-backdrop-filter: blur(18px);
  border-top: 1px solid var(--au-border);
}

.dock-tab {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-end;
  gap: 2px;
  min-width: 0;
  padding-top: 2px;
  text-decoration: none;
  color: var(--au-text-4);
  transition: color var(--au-fast) var(--au-ease);
  -webkit-tap-highlight-color: transparent;
}

.dock-tab.active { color: var(--au-primary); }
.dock-tab:not(.active):hover { color: var(--au-text-2); }

.dock-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
}

/* 中心「签到」凸起圆盘 */
.featured-disc {
  width: 40px;
  height: 40px;
  margin-top: -18px;
  border-radius: 50%;
  background: var(--au-gradient);
  color: #05141c;
  box-shadow: 0 6px 18px var(--au-primary-glow);
  border: 3px solid var(--au-bg);
}

.dock-tab.active .featured-disc {
  box-shadow: 0 6px 24px var(--au-primary-glow);
  transform: scale(1.05);
  transition: transform var(--au-fast) var(--au-ease);
}

.dock-label {
  font-size: 0.625rem;
  font-weight: 600;
  letter-spacing: 0.02em;
}

@media (max-width: 900px) {
  .app-dock { display: flex; }
}
</style>
