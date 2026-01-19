<template>
  <div class="theme-customizer">
    <div class="theme-customizer__trigger" @click="isOpen = !isOpen">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="12" cy="12" r="3"/>
        <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>
      </svg>
    </div>

    <Transition name="theme-customizer-panel">
      <div v-if="isOpen" class="theme-customizer__panel">
        <div class="theme-customizer__header">
          <h3 class="theme-customizer__title">主题设置</h3>
          <button class="theme-customizer__close" @click="isOpen = false">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="18" y1="6" x2="6" y2="18"/>
              <line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
          </button>
        </div>

        <div class="theme-customizer__body">
          <!-- 预设主题 -->
          <div class="theme-customizer__section">
            <label class="theme-customizer__label">预设主题</label>
            <div class="theme-presets">
              <button
                v-for="preset in presets"
                :key="preset.name"
                :class="['theme-preset', { 'theme-preset--active': currentPreset === preset.name }]"
                @click="applyPreset(preset)"
              >
                <span
                  class="theme-preset__color"
                  :style="{ background: preset.color }"
                />
                <span class="theme-preset__name">{{ preset.label }}</span>
              </button>
            </div>
          </div>

          <!-- 自定义颜色 -->
          <div class="theme-customizer__section">
            <label class="theme-customizer__label">自定义品牌色</label>
            <div class="color-picker">
              <input
                type="color"
                v-model="customColor"
                @input="updateCustomColor"
                class="color-picker__input"
              />
              <span class="color-picker__value">{{ customColor }}</span>
            </div>
          </div>

          <!-- 主题模式 -->
          <div class="theme-customizer__section">
            <label class="theme-customizer__label">外观模式</label>
            <div class="theme-modes">
              <button
                :class="['theme-mode', { 'theme-mode--active': resolvedTheme === 'light' }]"
                @click="setThemeMode('light')"
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <circle cx="12" cy="12" r="5"/>
                  <line x1="12" y1="1" x2="12" y2="3"/>
                  <line x1="12" y1="21" x2="12" y2="23"/>
                  <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/>
                  <line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/>
                  <line x1="1" y1="12" x2="3" y2="12"/>
                  <line x1="21" y1="12" x2="23" y2="12"/>
                  <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/>
                  <line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>
                </svg>
                <span>浅色</span>
              </button>
              <button
                :class="['theme-mode', { 'theme-mode--active': resolvedTheme === 'dark' }]"
                @click="setThemeMode('dark')"
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
                </svg>
                <span>深色</span>
              </button>
              <button
                :class="['theme-mode', { 'theme-mode--active': theme === 'auto' }]"
                @click="setThemeMode('auto')"
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
                  <line x1="9" y1="9" x2="9" y2="9"/>
                  <line x1="15" y1="9" x2="15" y2="9"/>
                  <line x1="9" y1="15" x2="15" y2="15"/>
                </svg>
                <span>跟随系统</span>
              </button>
            </div>
          </div>

          <!-- 重置按钮 -->
          <button class="theme-customizer__reset" @click="resetTheme">
            重置为默认
          </button>
        </div>
      </div>
    </Transition>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useThemeSingleton } from '@/composables/useTheme'

interface ThemePreset {
  name: string
  label: string
  color: string
  primary: string
  hover: string
}

const { theme, resolvedTheme, setTheme } = useThemeSingleton()

const isOpen = ref(false)
const customColor = ref('#10b981')
const currentPreset = ref('default')

const presets: ThemePreset[] = [
  { name: 'default', label: '默认绿', color: '#10b981', primary: '#10b981', hover: '#059669' },
  { name: 'blue', label: '天空蓝', color: '#3b82f6', primary: '#3b82f6', hover: '#2563eb' },
  { name: 'purple', label: '罗兰紫', color: '#8b5cf6', primary: '#8b5cf6', hover: '#7c3aed' },
  { name: 'rose', label: '玫瑰红', color: '#f43f5e', primary: '#f43f5e', hover: '#e11d48' },
  { name: 'orange', label: '落日橙', color: '#f97316', primary: '#f97316', hover: '#ea580c' },
  { name: 'teal', label: '青绿色', color: '#14b8a6', primary: '#14b8a6', hover: '#0d9488' },
]

const applyPreset = (preset: ThemePreset) => {
  currentPreset.value = preset.name
  customColor.value = preset.color
  updateCSSVariables(preset.primary, preset.hover)
  saveCustomTheme(preset.primary, preset.hover)
}

const updateCustomColor = () => {
  const primary = customColor.value
  // 生成较深的悬停色
  const hover = adjustBrightness(primary, -15)
  updateCSSVariables(primary, hover)
  saveCustomTheme(primary, hover)
  currentPreset.value = 'custom'
}

const updateCSSVariables = (primary: string, hover: string) => {
  const root = document.documentElement
  root.style.setProperty('--brand-primary', primary)
  root.style.setProperty('--brand-primary-hover', hover)
  root.style.setProperty('--brand-primary-light', hexToRgba(primary, 0.15))
  root.style.setProperty('--brand-primary-lighter', hexToRgba(primary, 0.08))
  root.style.setProperty('--color-focus-ring', primary)
}

const setThemeMode = (mode: 'light' | 'dark' | 'auto') => {
  setTheme(mode)
}

const resetTheme = () => {
  const defaultPreset = presets[0]
  applyPreset(defaultPreset)
  setTheme('auto')
}

// 保存到 localStorage
const saveCustomTheme = (primary: string, hover: string) => {
  try {
    localStorage.setItem('royalbot-custom-theme', JSON.stringify({ primary, hover, preset: currentPreset.value }))
  } catch {
    // ignore
  }
}

// 从 localStorage 读取
const loadCustomTheme = () => {
  try {
    const saved = localStorage.getItem('royalbot-custom-theme')
    if (saved) {
      const { primary, hover, preset } = JSON.parse(saved)
      if (primary && hover) {
        updateCSSVariables(primary, hover)
        customColor.value = primary
        currentPreset.value = preset || 'custom'
      }
    }
  } catch {
    // ignore
  }
}

// 工具函数
const hexToRgba = (hex: string, alpha: number): string => {
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

const adjustBrightness = (hex: string, percent: number): string => {
  const num = parseInt(hex.replace('#', ''), 16)
  const amt = Math.round(2.55 * percent)
  const R = (num >> 16) + amt
  const G = (num >> 8 & 0x00FF) + amt
  const B = (num & 0x0000FF) + amt
  return '#' + (
    0x1000000 +
    (R < 255 ? (R < 1 ? 0 : R) : 255) * 0x10000 +
    (G < 255 ? (G < 1 ? 0 : G) : 255) * 0x100 +
    (B < 255 ? (B < 1 ? 0 : B) : 255)
  ).toString(16).slice(1)
}

// 初始化
loadCustomTheme()
</script>

<style scoped>
.theme-customizer {
  position: fixed;
  bottom: 2rem;
  right: 2rem;
  z-index: var(--z-fixed);
}

.theme-customizer__trigger {
  width: 48px;
  height: 48px;
  background: var(--brand-primary);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  cursor: pointer;
  box-shadow: var(--shadow-lg);
  transition: all 0.3s ease;
}

.theme-customizer__trigger:hover {
  transform: scale(1.1);
  box-shadow: var(--shadow-xl);
}

.theme-customizer__trigger svg {
  width: 24px;
  height: 24px;
}

.theme-customizer__panel {
  position: absolute;
  bottom: calc(100% + 1rem);
  right: 0;
  width: 280px;
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-xl);
  overflow: hidden;
}

.theme-customizer__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1rem 1.25rem;
  border-bottom: 1px solid var(--divider-color);
}

.theme-customizer__title {
  font-size: 0.9375rem;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.theme-customizer__close {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: none;
  border-radius: var(--radius-sm);
  color: var(--text-tertiary);
  cursor: pointer;
  transition: all 0.2s ease;
}

.theme-customizer__close:hover {
  background: var(--bg-elevated-hover);
  color: var(--text-primary);
}

.theme-customizer__close svg {
  width: 16px;
  height: 16px;
}

.theme-customizer__body {
  padding: 1rem;
}

.theme-customizer__section {
  margin-bottom: 1.25rem;
}

.theme-customizer__section:last-child {
  margin-bottom: 0;
}

.theme-customizer__label {
  display: block;
  font-size: 0.75rem;
  font-weight: 500;
  color: var(--text-secondary);
  margin-bottom: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.theme-presets {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.theme-preset {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0.75rem;
  background: var(--bg-elevated);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all 0.2s ease;
}

.theme-preset:hover {
  border-color: var(--border-strong);
}

.theme-preset--active {
  border-color: var(--brand-primary);
  background: var(--brand-primary-lighter);
}

.theme-preset__color {
  width: 16px;
  height: 16px;
  border-radius: 4px;
}

.theme-preset__name {
  font-size: 0.75rem;
  color: var(--text-primary);
}

.color-picker {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.5rem 0.75rem;
  background: var(--bg-elevated);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
}

.color-picker__input {
  width: 32px;
  height: 32px;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  padding: 0;
  background: transparent;
}

.color-picker__input::-webkit-color-swatch-wrapper {
  padding: 0;
}

.color-picker__input::-webkit-color-swatch {
  border: 1px solid var(--border-default);
  border-radius: 4px;
}

.color-picker__value {
  font-size: 0.8125rem;
  color: var(--text-primary);
  font-family: monospace;
}

.theme-modes {
  display: flex;
  gap: 0.5rem;
}

.theme-mode {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.375rem;
  padding: 0.75rem 0.5rem;
  background: var(--bg-elevated);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all 0.2s ease;
}

.theme-mode:hover {
  border-color: var(--border-strong);
}

.theme-mode--active {
  border-color: var(--brand-primary);
  background: var(--brand-primary-lighter);
  color: var(--brand-primary);
}

.theme-mode svg {
  width: 20px;
  height: 20px;
}

.theme-mode span {
  font-size: 0.6875rem;
  color: var(--text-secondary);
}

.theme-mode--active span {
  color: var(--brand-primary);
}

.theme-customizer__reset {
  width: 100%;
  padding: 0.625rem;
  background: transparent;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  color: var(--text-secondary);
  font-size: 0.8125rem;
  cursor: pointer;
  transition: all 0.2s ease;
}

.theme-customizer__reset:hover {
  background: var(--bg-elevated);
  color: var(--text-primary);
}

/* 面板动画 */
.theme-customizer-panel-enter-active,
.theme-customizer-panel-leave-active {
  transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}

.theme-customizer-panel-enter-from {
  opacity: 0;
  transform: translateY(10px) scale(0.95);
}

.theme-customizer-panel-leave-to {
  opacity: 0;
  transform: translateY(10px) scale(0.95);
}

/* 响应式 */
@media (max-width: 640px) {
  .theme-customizer {
    bottom: 1rem;
    right: 1rem;
  }

  .theme-customizer__panel {
    width: calc(100vw - 2rem);
    right: -1rem;
    bottom: calc(100% + 0.5rem);
  }
}
</style>
