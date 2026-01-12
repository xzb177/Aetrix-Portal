<script setup lang="ts">
/**
 * 首页 - Apple TV 风格
 *
 * 设计原则：
 * - 唯一主 CTA：消除多入口冲突
 * - Header 右侧仅菜单图标
 * - 暗黑高级：深色渐变 + 轻微噪点质感
 * - 克制布局：一行三要点代替卡片
 * - 移动优先：safe-area + 100svh + 52px 触控
 */
import { RouterLink } from 'vue-router'
import { Play, Menu } from 'lucide-vue-next'
import { ref } from 'vue'
import BrandIcon from '@/components/BrandIcon.vue'

const mobileMenuOpen = ref(false)
</script>

<template>
  <div class="appletv-container">
    <!-- 背景质感层（噪点 + 光晕） -->
    <div class="appletv-bg"></div>

    <!-- Header：左侧 Logo，右侧仅菜单图标 -->
    <header class="appletv-header">
      <RouterLink to="/" class="header-logo">
        <BrandIcon :size="32" />
        <span class="logo-text">RoyalBot</span>
      </RouterLink>

      <!-- 右侧仅保留菜单图标 -->
      <button
        @click="mobileMenuOpen = !mobileMenuOpen"
        class="menu-btn"
        aria-label="菜单"
      >
        <Menu :size="22" />
      </button>
    </header>

    <!-- 移动端菜单（抽屉式） -->
    <Transition name="drawer">
      <div v-if="mobileMenuOpen" class="mobile-drawer" @click.self="mobileMenuOpen = false">
        <nav class="drawer-nav">
          <RouterLink to="/login" @click="mobileMenuOpen = false" class="drawer-link drawer-link-primary">
            登录 / 注册
          </RouterLink>
          <div class="drawer-divider"></div>
          <RouterLink to="/subscription" @click="mobileMenuOpen = false" class="drawer-link">
            套餐说明
          </RouterLink>
          <RouterLink to="/tickets" @click="mobileMenuOpen = false" class="drawer-link">
            联系客服
          </RouterLink>
        </nav>
      </div>
    </Transition>

    <!-- 主内容区 -->
    <main class="appletv-main">
      <!-- 品牌图标 -->
      <BrandIcon :size="40" />

      <!-- 标题 -->
      <h1 class="main-title">私享影院，静候开启</h1>

      <!-- 副标题 -->
      <p class="main-subtitle">领取账号 · 即刻观影</p>

      <!-- 唯一主 CTA -->
      <RouterLink to="/login" class="main-cta">
        <span>登录 / 注册</span>
      </RouterLink>

      <!-- 信任小字 -->
      <p class="trust-text">无自动续费 · 订单可查</p>

      <!-- 分割线 -->
      <div class="divider-line"></div>

      <!-- 一行三要点（非卡片） -->
      <div class="features-row">
        <div class="feature-item">
          <span class="feature-label">4K 超清</span>
        </div>
        <div class="feature-item">
          <span class="feature-label">多端同步</span>
        </div>
        <div class="feature-item">
          <span class="feature-label">即时开通</span>
        </div>
      </div>

      <!-- 分割线 -->
      <div class="divider-line"></div>

      <!-- 极弱次要入口 -->
      <div class="secondary-links">
        <RouterLink to="/subscription" class="weak-link">套餐说明</RouterLink>
        <span class="weak-divider">·</span>
        <RouterLink to="/tickets" class="weak-link">联系客服</RouterLink>
      </div>
    </main>
  </div>
</template>

<style scoped>
/* ==================== 容器与背景 ==================== */
.appletv-container {
  min-height: 100svh;
  min-height: 100dvh;
  position: relative;
  display: flex;
  flex-direction: column;
  padding-top: env(safe-area-inset-top, 0);
  padding-bottom: env(safe-area-inset-bottom, 0);
  overflow-x: hidden;
}

/* 背景层：深色渐变 + 噪点 + 微光晕 */
.appletv-bg {
  position: fixed;
  inset: 0;
  z-index: -1;
  background:
    /* 径向光晕（左上暗角） */
    radial-gradient(ellipse at 20% 0%, rgba(60, 60, 60, 0.15) 0%, transparent 60%),
    /* 径向光晕（右下微光） */
    radial-gradient(ellipse at 80% 100%, rgba(50, 50, 50, 0.1) 0%, transparent 50%),
    /* 主渐变：从深灰到近黑 */
    linear-gradient(180deg, #1a1a1a 0%, #0a0a0a 100%);
}

/* 噪点质感（用伪元素实现） */
.appletv-bg::before {
  content: '';
  position: absolute;
  inset: 0;
  /* SVG 噪点 data URI（极细噪点） */
  background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)'/%3E%3C/svg%3E");
  background-repeat: repeat;
  opacity: 0.03;
  pointer-events: none;
}

/* ==================== Header ==================== */
.appletv-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 1.25rem;
  /* 玻璃态，极弱 */
  background: rgba(10, 10, 10, 0.6);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  position: sticky;
  top: 0;
  z-index: 50;
}

/* Logo 区域 */
.header-logo {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  text-decoration: none;
}

.logo-text {
  font-size: 0.875rem;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.95);
  letter-spacing: -0.01em;
}

/* 菜单按钮（右侧唯一元素） */
.menu-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border: none;
  background: transparent;
  color: rgba(255, 255, 255, 0.7);
  cursor: pointer;
  border-radius: 8px;
  transition: all 0.15s ease;
  /* 触控区域足够大 */
  min-width: 44px;
  min-height: 44px;
}

.menu-btn:active {
  background: rgba(255, 255, 255, 0.1);
  color: rgba(255, 255, 255, 0.9);
  transform: scale(0.95);
}

/* ==================== 主内容区 ==================== */
.appletv-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 2rem 1.25rem 1.5rem;
  text-align: center;
}

/* 主标题 */
.main-title {
  font-size: 1.375rem;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.95);
  margin: 0 0 0.75rem;
  letter-spacing: -0.02em;
  line-height: 1.3;
}

/* 副标题 */
.main-subtitle {
  font-size: 0.875rem;
  color: rgba(255, 255, 255, 0.5);
  margin: 0 0 2rem;
  font-weight: 400;
  letter-spacing: 0.01em;
}

/* 唯一主 CTA（玻璃质感，非亮渐变） */
.main-cta {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  max-width: 280px;
  height: 52px;
  /* 玻璃态，低饱和 */
  background: rgba(255, 255, 255, 0.12);
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 12px;
  color: rgba(255, 255, 255, 0.95);
  font-size: 1rem;
  font-weight: 500;
  text-decoration: none;
  letter-spacing: 0.02em;
  transition: all 0.2s ease;
  /* 触控高度 */
  min-height: 52px;
}

.main-cta:active {
  background: rgba(255, 255, 255, 0.18);
  border-color: rgba(255, 255, 255, 0.3);
  transform: scale(0.98);
}

/* 信任小字 */
.trust-text {
  font-size: 0.75rem;
  color: rgba(255, 255, 255, 0.35);
  margin-top: 1rem;
  letter-spacing: 0.02em;
}

/* 分割线（极细） */
.divider-line {
  width: 100%;
  max-width: 200px;
  height: 1px;
  background: linear-gradient(
    90deg,
    transparent 0%,
    rgba(255, 255, 255, 0.1) 50%,
    transparent 100%
  );
  margin: 1.5rem 0;
}

/* 一行三要点（非卡片） */
.features-row {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 1.5rem;
  width: 100%;
}

.feature-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.375rem;
}

.feature-item::before {
  content: '';
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.15);
}

.feature-label {
  font-size: 0.75rem;
  color: rgba(255, 255, 255, 0.5);
  font-weight: 400;
}

/* 极弱次要入口 */
.secondary-links {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.75rem;
  margin-top: 0.5rem;
}

.weak-link {
  font-size: 0.813rem;
  color: rgba(255, 255, 255, 0.35);
  text-decoration: none;
  transition: color 0.15s ease;
}

.weak-link:active {
  color: rgba(255, 255, 255, 0.5);
}

.weak-divider {
  color: rgba(255, 255, 255, 0.15);
  font-size: 0.75rem;
}

/* ==================== 移动端抽屉菜单 ==================== */
.mobile-drawer {
  position: fixed;
  inset: 0;
  z-index: 100;
  background: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(4px);
}

.drawer-nav {
  position: absolute;
  right: 0;
  top: 0;
  bottom: 0;
  width: 260px;
  background: rgba(20, 20, 20, 0.95);
  backdrop-filter: blur(30px);
  border-left: 1px solid rgba(255, 255, 255, 0.1);
  padding: 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.drawer-link {
  display: flex;
  align-items: center;
  padding: 0.875rem 1rem;
  font-size: 0.938rem;
  font-weight: 500;
  color: rgba(255, 255, 255, 0.8);
  text-decoration: none;
  border-radius: 10px;
  transition: background 0.15s ease;
  min-height: 48px;
}

.drawer-link:active {
  background: rgba(255, 255, 255, 0.08);
}

.drawer-link-primary {
  background: rgba(255, 255, 255, 0.1);
  color: rgba(255, 255, 255, 0.95);
}

.drawer-link-primary:active {
  background: rgba(255, 255, 255, 0.15);
}

.drawer-divider {
  height: 1px;
  background: rgba(255, 255, 255, 0.1);
  margin: 0.5rem 0;
}

/* 抽屉动画 */
.drawer-enter-active,
.drawer-leave-active {
  transition: all 0.25s ease;
}

.drawer-enter-from,
.drawer-leave-to {
  opacity: 0;
}

.drawer-enter-from .drawer-nav,
.drawer-leave-to .drawer-nav {
  transform: translateX(100%);
}

/* ==================== 暗色模式适配 ==================== */
@media (prefers-color-scheme: dark) {
  /* 默认就是暗色，无需额外处理 */
}

/* ==================== 大屏幕适配 ==================== */
@media (min-width: 640px) {
  .appletv-main {
    padding: 3rem 2rem 2rem;
  }

  .main-title {
    font-size: 1.625rem;
  }

  .main-subtitle {
    font-size: 0.938rem;
  }

  .features-row {
    gap: 2.5rem;
  }
}
</style>
