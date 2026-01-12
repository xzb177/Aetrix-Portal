<script setup lang="ts">
import { ref, computed } from 'vue'
import { ChevronDown, ChevronUp, Copy, Check, Smartphone, Monitor, Tv, Apple, ExternalLink } from 'lucide-vue-next'
import { useToast } from '@/composables/useToast'

const toast = useToast()

type Platform = 'ios' | 'android' | 'tv'

const isExpanded = ref(false)
const activePlatform = ref<Platform>('ios')
const copiedField = ref<string | null>(null)

const platforms = [
  { id: 'ios' as Platform, name: 'iOS', icon: Apple },
  { id: 'android' as Platform, name: 'Android', icon: Smartphone },
  { id: 'tv' as Platform, name: '电视/盒子', icon: Tv },
]

// 模拟数据 - 实际使用时应该从 props 传入或从 store 获取
const serverInfo = ref({
  serverUrl: 'https://emby.example.com',
  username: 'user123',
  password: 'pass123',
})

const guideSteps = computed(() => {
  const steps = {
    ios: [
      {
        title: '下载 Emby 客户端',
        description: '在 App Store 搜索 "Emby" 并下载官方应用',
        highlight: false,
      },
      {
        title: '打开应用选择"连接至服务器"',
        description: '启动 Emby 应用，点击"添加服务器"',
        highlight: false,
      },
      {
        title: '输入服务器地址',
        description: '在服务器地址栏输入以下地址',
        code: serverInfo.value.serverUrl,
        highlight: true,
      },
      {
        title: '输入账号信息',
        description: '使用以下账号登录',
        code: `账号: ${serverInfo.value.username}\n密码: ${serverInfo.value.password}`,
        highlight: true,
      },
    ],
    android: [
      {
        title: '下载 Emby 客户端',
        description: '在 Google Play 或应用商店搜索 "Emby" 下载',
        highlight: false,
      },
      {
        title: '安装并打开应用',
        description: '启动 Emby 应用，选择"连接至服务器"',
        highlight: false,
      },
      {
        title: '输入服务器地址',
        description: '在服务器地址栏输入以下地址',
        code: serverInfo.value.serverUrl,
        highlight: true,
      },
      {
        title: '输入账号信息',
        description: '使用以下账号登录',
        code: `账号: ${serverInfo.value.username}\n密码: ${serverInfo.value.password}`,
        highlight: true,
      },
    ],
    tv: [
      {
        title: '在电视上安装 Emby',
        description: '在电视应用商店搜索 "Emby for TV" 下载安装',
        highlight: false,
      },
      {
        title: '启动应用选择手动连接',
        description: '使用遥控器导航至"连接至服务器"，选择手动输入',
        highlight: false,
      },
      {
        title: '输入服务器地址',
        description: '使用遥控器在服务器地址栏输入以下地址',
        code: serverInfo.value.serverUrl,
        highlight: true,
      },
      {
        title: '输入账号信息',
        description: '使用遥控器输入以下账号密码',
        code: `账号: ${serverInfo.value.username}\n密码: ${serverInfo.value.password}`,
        highlight: true,
      },
    ],
  }
  return steps[activePlatform.value]
})

async function copyToClipboard(text: string, field: string) {
  try {
    await navigator.clipboard.writeText(text)
    copiedField.value = field
    toast.success('复制成功')
    setTimeout(() => {
      copiedField.value = null
    }, 2000)
  } catch (err) {
    toast.error('复制失败，请手动复制')
  }
}

function toggleExpanded() {
  isExpanded.value = !isExpanded.value
}

function selectPlatform(platform: Platform) {
  activePlatform.value = platform
}

// 快捷复制全部
function copyAll() {
  const allInfo = `服务器地址: ${serverInfo.value.serverUrl}
账号: ${serverInfo.value.username}
密码: ${serverInfo.value.password}`
  copyToClipboard(allInfo, 'all')
}
</script>

<template>
  <div class="guide-card">
    <!-- 卡片头部 -->
    <button @click="toggleExpanded" class="guide-header">
      <div class="header-left">
        <Monitor :size="20" class="header-icon" />
        <div class="header-content">
          <h3 class="header-title">Emby 连接指南</h3>
          <p class="header-desc">不知道怎么连接？查看详细教程</p>
        </div>
      </div>
      <ChevronDown :size="20" class="chevron" :class="{ 'chevron-up': isExpanded }" />
    </button>

    <!-- 卡片内容 -->
    <Transition name="expand">
      <div v-if="isExpanded" class="guide-content">
        <!-- 快捷复制全部 -->
        <button @click="copyAll" class="copy-all-btn">
          <Copy :size="16" />
          <span>一键复制全部信息</span>
        </button>

        <!-- 平台标签页 -->
        <div class="platform-tabs">
          <button
            v-for="platform in platforms"
            :key="platform.id"
            @click="selectPlatform(platform.id)"
            class="platform-tab"
            :class="{ 'platform-tab-active': activePlatform === platform.id }"
          >
            <component :is="platform.icon" :size="16" />
            <span>{{ platform.name }}</span>
          </button>
        </div>

        <!-- 步骤列表 -->
        <div class="steps-list">
          <div
            v-for="(step, index) in guideSteps"
            :key="index"
            class="step-item"
            :class="{ 'step-item-highlight': step.highlight }"
          >
            <div class="step-number">{{ index + 1 }}</div>
            <div class="step-content">
              <h4 class="step-title">{{ step.title }}</h4>
              <p class="step-desc">{{ step.description }}</p>

              <!-- 可复制代码块 -->
              <div v-if="step.code" class="step-code">
                <code class="code-text">{{ step.code }}</code>
                <button
                  @click="copyToClipboard(step.code, `step-${index}`)"
                  class="copy-btn"
                  :class="{ 'copy-btn-copied': copiedField === `step-${index}` }"
                >
                  <Check v-if="copiedField === `step-${index}`" :size="14" />
                  <Copy v-else :size="14" />
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- 底部链接 -->
        <div class="guide-footer">
          <a
            href="https://emby.media/help.html"
            target="_blank"
            rel="noopener"
            class="footer-link"
          >
            <span>查看 Emby 官方帮助文档</span>
            <ExternalLink :size="14" />
          </a>
          <span class="footer-divider">|</span>
          <a href="mailto:support@example.com" class="footer-link">
            联系客服
          </a>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.guide-card {
  background: var(--bg-elevated, #141414);
  border: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.08));
  border-radius: var(--radius-md, 10px);
  overflow: hidden;
  margin-bottom: 1rem;
}

/* 头部 */
.guide-header {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1rem;
  background: transparent;
  border: none;
  cursor: pointer;
  transition: background var(--duration-fast, 150ms) ease;
}

.guide-header:hover {
  background: rgba(255, 255, 255, 0.03);
}

.guide-header:active {
  background: rgba(255, 255, 255, 0.05);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.header-icon {
  color: var(--brand-primary, #10b981);
  flex-shrink: 0;
}

.header-content {
  text-align: left;
}

.header-title {
  font-size: 0.9375rem;
  font-weight: 600;
  color: var(--text-primary, #fafafa);
  margin: 0;
  line-height: 1.4;
}

.header-desc {
  font-size: 0.75rem;
  color: var(--text-secondary, rgba(250, 250, 250, 0.6));
  margin: 0.125rem 0 0 0;
  line-height: 1.4;
}

.chevron {
  color: var(--text-tertiary, rgba(250, 250, 250, 0.4));
  transition: transform var(--duration-fast, 150ms) ease;
  flex-shrink: 0;
}

.chevron-up {
  transform: rotate(180deg);
}

/* 内容区域 */
.guide-content {
  border-top: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.08));
  padding: 1rem;
}

/* 快捷复制全部 */
.copy-all-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  width: 100%;
  padding: 0.75rem;
  margin-bottom: 1rem;
  background: rgba(16, 185, 129, 0.1);
  border: 1px solid rgba(16, 185, 129, 0.3);
  border-radius: var(--radius-sm, 6px);
  color: var(--brand-primary, #10b981);
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
  transition: all var(--duration-fast, 150ms) ease;
}

.copy-all-btn:hover {
  background: rgba(16, 185, 129, 0.15);
}

.copy-all-btn:active {
  transform: scale(0.98);
}

/* 平台标签 */
.platform-tabs {
  display: flex;
  gap: 0.5rem;
  margin-bottom: 1rem;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  scrollbar-width: none;
}

.platform-tabs::-webkit-scrollbar {
  display: none;
}

.platform-tab {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.5rem 0.875rem;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid var(--border-default, rgba(255, 255, 255, 0.12));
  border-radius: 20px;
  color: var(--text-secondary, rgba(250, 250, 250, 0.7));
  font-size: 0.8125rem;
  font-weight: 500;
  cursor: pointer;
  white-space: nowrap;
  transition: all var(--duration-fast, 150ms) ease;
}

.platform-tab:hover {
  background: rgba(255, 255, 255, 0.06);
}

.platform-tab-active {
  background: var(--brand-primary, #10b981);
  border-color: var(--brand-primary, #10b981);
  color: white;
}

/* 步骤列表 */
.steps-list {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.step-item {
  display: flex;
  gap: 0.75rem;
}

.step-item-highlight {
  background: rgba(16, 185, 129, 0.05);
  padding: 0.75rem;
  border-radius: var(--radius-sm, 6px);
  border: 1px dashed rgba(16, 185, 129, 0.2);
}

.step-number {
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--brand-primary, #10b981);
  color: white;
  border-radius: 50%;
  font-size: 0.75rem;
  font-weight: 600;
  flex-shrink: 0;
}

.step-content {
  flex: 1;
}

.step-title {
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--text-primary, #fafafa);
  margin: 0 0 0.25rem 0;
  line-height: 1.4;
}

.step-desc {
  font-size: 0.8125rem;
  color: var(--text-secondary, rgba(250, 250, 250, 0.6));
  margin: 0 0 0.5rem 0;
  line-height: 1.5;
}

/* 代码块 */
.step-code {
  position: relative;
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
  padding: 0.625rem;
  background: rgba(0, 0, 0, 0.4);
  border: 1px solid var(--border-default, rgba(255, 255, 255, 0.12));
  border-radius: var(--radius-sm, 6px);
}

.code-text {
  flex: 1;
  font-family: 'SF Mono', 'Monaco', 'Consolas', monospace;
  font-size: 0.75rem;
  color: var(--text-primary, #fafafa);
  white-space: pre-wrap;
  word-break: break-all;
  line-height: 1.5;
}

.copy-btn {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.06);
  border: none;
  border-radius: 4px;
  color: var(--text-secondary, rgba(250, 250, 250, 0.6));
  cursor: pointer;
  flex-shrink: 0;
  transition: all var(--duration-fast, 150ms) ease;
}

.copy-btn:hover {
  background: rgba(255, 255, 255, 0.1);
  color: var(--text-primary, #fafafa);
}

.copy-btn:active {
  transform: scale(0.92);
}

.copy-btn-copied {
  background: rgba(16, 185, 129, 0.2);
  color: var(--brand-primary, #10b981);
}

/* 底部 */
.guide-footer {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.75rem;
  margin-top: 1rem;
  padding-top: 1rem;
  border-top: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.08));
}

.footer-link {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  font-size: 0.8125rem;
  color: var(--text-secondary, rgba(250, 250, 250, 0.6));
  text-decoration: none;
  transition: color var(--duration-fast, 150ms) ease;
}

.footer-link:hover {
  color: var(--brand-primary, #10b981);
}

.footer-divider {
  color: var(--border-default, rgba(255, 255, 255, 0.2));
}

/* 展开动画 */
.expand-enter-active,
.expand-leave-active {
  transition: all 0.25s ease;
  overflow: hidden;
}

.expand-enter-from,
.expand-leave-to {
  max-height: 0;
  opacity: 0;
}

.expand-enter-to,
.expand-leave-from {
  max-height: 1000px;
  opacity: 1;
}

/* 移动端优化 */
@media (max-width: 640px) {
  .guide-header {
    padding: 0.875rem;
  }

  .header-title {
    font-size: 0.875rem;
  }

  .header-desc {
    font-size: 0.7rem;
  }

  .guide-content {
    padding: 0.875rem;
  }

  .platform-tab {
    padding: 0.4375rem 0.75rem;
    font-size: 0.75rem;
  }

  .step-item-highlight {
    padding: 0.625rem;
  }

  .code-text {
    font-size: 0.7rem;
  }

  .footer-link {
    font-size: 0.75rem;
  }
}

/* 按下态 */
@media (hover: none) {
  .copy-all-btn:active,
  .copy-btn:active,
  .platform-tab:active {
    transform: scale(0.96);
    opacity: 0.9;
  }

  .footer-link:active {
    opacity: 0.7;
  }
}
</style>
