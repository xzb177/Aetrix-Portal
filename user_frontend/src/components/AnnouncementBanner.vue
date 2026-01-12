<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { announcementApi } from '@/api'
import { Bell, X, ChevronLeft, ChevronRight, AlertTriangle, Info, Megaphone } from 'lucide-vue-next'

// 公告数据结构
interface Announcement {
  id: number
  title: string
  content?: string
  type: 'urgent' | 'activity' | 'system'
  is_active: boolean
  created_at: string
}

// 状态
const announcements = ref<Announcement[]>([])
const currentIndex = ref(0)
const isVisible = ref(true)
const isPaused = ref(false)
const containerRef = ref<HTMLElement>()
const slidePosition = ref(0)
const prevIndex = ref(0)

// 滑动方向（用于动画）
const slideDirection = computed(() => {
  if (prevIndex.value < currentIndex.value) {
    // 处理循环情况
    if (prevIndex.value === announcements.value.length - 1 && currentIndex.value === 0) {
      return 'right'
    }
    return 'left'
  } else {
    // 处理循环情况
    if (currentIndex.value === announcements.value.length - 1 && prevIndex.value === 0) {
      return 'left'
    }
    return 'right'
  }
})

// 自动轮播定时器
let autoPlayTimer: number | null = null
const AUTO_PLAY_INTERVAL = 5000 // 5秒切换

// 当前显示的公告
const currentAnnouncement = computed(() => {
  if (announcements.value.length === 0) return null
  return announcements.value[currentIndex.value]
})

// 是否有多个公告
const hasMultiple = computed(() => announcements.value.length > 1)

// 获取公告类型配置
const getTypeConfig = (type: string) => {
  const configs = {
    urgent: {
      label: '紧急',
      icon: AlertTriangle,
      gradient: 'linear-gradient(135deg, rgba(239, 68, 68, 0.95) 0%, rgba(220, 38, 38, 0.95) 100%)',
      textColor: '#ffffff',
      bgColor: 'rgba(239, 68, 68, 0.15)',
    },
    activity: {
      label: '活动',
      icon: Megaphone,
      gradient: 'linear-gradient(135deg, rgba(168, 85, 247, 0.95) 0%, rgba(139, 92, 246, 0.95) 100%)',
      textColor: '#ffffff',
      bgColor: 'rgba(168, 85, 247, 0.15)',
    },
    system: {
      label: '通知',
      icon: Info,
      gradient: 'linear-gradient(135deg, rgba(59, 130, 246, 0.95) 0%, rgba(37, 99, 235, 0.95) 100%)',
      textColor: '#ffffff',
      bgColor: 'rgba(59, 130, 246, 0.15)',
    },
  }
  return configs[type as keyof typeof configs] || configs.system
}

// 当前公告类型配置
const currentTypeConfig = computed(() => {
  if (!currentAnnouncement.value) return getTypeConfig('system')
  return getTypeConfig(currentAnnouncement.value.type)
})

// 获取公告列表
const fetchAnnouncements = async () => {
  try {
    const res = await announcementApi.getAnnouncements({ limit: 5 })
    // 只显示激活的公告
    announcements.value = (res.data || []).filter((a: Announcement) => a.is_active)
  } catch (error) {
    announcements.value = []
  }
}

// 切换到下一个公告
const next = () => {
  if (announcements.value.length <= 1) return
  prevIndex.value = currentIndex.value
  currentIndex.value = (currentIndex.value + 1) % announcements.value.length
}

// 切换到上一个公告
const prev = () => {
  if (announcements.value.length <= 1) return
  prevIndex.value = currentIndex.value
  currentIndex.value = currentIndex.value - 1 < 0
    ? announcements.value.length - 1
    : currentIndex.value - 1
}

// 跳转到指定公告
const goTo = (index: number) => {
  if (index === currentIndex.value) return
  prevIndex.value = currentIndex.value
  currentIndex.value = index
}

// 开始自动轮播
const startAutoPlay = () => {
  if (!hasMultiple.value) return
  stopAutoPlay()
  autoPlayTimer = window.setInterval(() => {
    if (!isPaused.value) {
      next()
    }
  }, AUTO_PLAY_INTERVAL)
}

// 停止自动轮播
const stopAutoPlay = () => {
  if (autoPlayTimer) {
    clearInterval(autoPlayTimer)
    autoPlayTimer = null
  }
}

// 关闭公告横幅
const closeBanner = () => {
  isVisible.value = false
  // 记录关闭时间，24小时内不再显示
  localStorage.setItem('announcement_banner_closed', Date.now().toString())
}

// 检查是否应该显示横幅
const checkVisibility = () => {
  const closedTime = localStorage.getItem('announcement_banner_closed')
  if (closedTime) {
    const elapsed = Date.now() - parseInt(closedTime)
    const HOURS_24 = 24 * 60 * 60 * 1000
    if (elapsed < HOURS_24) {
      isVisible.value = false
      return
    }
  }
  // 检查是否有公告
  if (announcements.value.length === 0) {
    isVisible.value = false
  } else {
    isVisible.value = true
  }
}

// 鼠标悬停暂停
const onMouseEnter = () => {
  isPaused.value = true
}

const onMouseLeave = () => {
  isPaused.value = false
}

// 触摸滑动支持
let touchStartX = 0
let touchEndX = 0

const onTouchStart = (e: TouchEvent) => {
  touchStartX = e.changedTouches[0]?.screenX || 0
}

const onTouchEnd = (e: TouchEvent) => {
  touchEndX = e.changedTouches[0]?.screenX || 0
  handleSwipe()
}

const handleSwipe = () => {
  const threshold = 50
  const diff = touchStartX - touchEndX
  if (Math.abs(diff) > threshold) {
    if (diff > 0) {
      next() // 左滑，下一个
    } else {
      prev() // 右滑，上一个
    }
  }
}

// 监听公告列表变化
watch(announcements, () => {
  if (announcements.value.length > 0) {
    checkVisibility()
    if (isVisible.value) {
      startAutoPlay()
    }
  } else {
    isVisible.value = false
    stopAutoPlay()
  }
})

onMounted(async () => {
  await fetchAnnouncements()
  checkVisibility()
  if (isVisible.value && hasMultiple.value) {
    startAutoPlay()
  }
})

onUnmounted(() => {
  stopAutoPlay()
})
</script>

<template>
  <Transition name="banner">
    <div
      v-if="isVisible && currentAnnouncement"
      ref="containerRef"
      class="announcement-banner"
      :style="{ background: currentTypeConfig.gradient }"
      @mouseenter="onMouseEnter"
      @mouseleave="onMouseLeave"
      @touchstart="onTouchStart"
      @touchend="onTouchEnd"
    >
      <div class="banner-container">
        <!-- 左侧：类型图标和公告内容 -->
        <div class="banner-content">
          <div class="announcement-icon">
            <Bell :size="18" />
          </div>
          <div class="announcement-type" :style="{ background: currentTypeConfig.bgColor }">
            <component :is="currentTypeConfig.icon" :size="14" />
            <span>{{ currentTypeConfig.label }}</span>
          </div>
          <div class="announcement-slider">
            <Transition :name="`slide-${slideDirection}`" mode="out-in">
              <div :key="currentIndex" class="announcement-text-wrapper">
                <span class="announcement-text">{{ currentAnnouncement.title }}</span>
              </div>
            </Transition>
          </div>
        </div>

        <!-- 右侧：控制按钮 -->
        <div class="banner-controls">
          <!-- 轮播指示器 -->
          <div v-if="hasMultiple" class="banner-dots">
            <button
              v-for="(_, index) in announcements"
              :key="index"
              class="dot"
              :class="{ active: index === currentIndex }"
              @click="goTo(index)"
              :aria-label="`跳转到公告 ${index + 1}`"
            >
              <span class="dot-inner"></span>
            </button>
          </div>

          <!-- 导航箭头（桌面端） -->
          <div v-if="hasMultiple" class="banner-arrows">
            <button class="arrow-btn" @click="prev" aria-label="上一条">
              <ChevronLeft :size="16" />
            </button>
            <button class="arrow-btn" @click="next" aria-label="下一条">
              <ChevronRight :size="16" />
            </button>
          </div>

          <!-- 关闭按钮 -->
          <button class="close-btn" @click="closeBanner" aria-label="关闭公告">
            <X :size="16" />
          </button>
        </div>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
/* ==================== 公告横幅 ==================== */
.announcement-banner {
  position: fixed;
  top: 64px; /* 导航栏高度 */
  left: 0;
  right: 0;
  z-index: 999;
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
  transition: all 0.3s ease;
}

.banner-container {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 1.5rem;
  max-width: 100%;
  margin: 0 auto;
}

/* 左侧内容区 */
.banner-content {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex: 1;
  min-width: 0;
}

.announcement-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  background: rgba(255, 255, 255, 0.2);
  border-radius: 8px;
  flex-shrink: 0;
}

.announcement-type {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.25rem 0.625rem;
  border-radius: 6px;
  font-size: 0.75rem;
  font-weight: 600;
  color: white;
  flex-shrink: 0;
  white-space: nowrap;
}

.announcement-slider {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  position: relative;
}

.announcement-text-wrapper {
  display: flex;
  align-items: center;
}

.announcement-text {
  color: white;
  font-size: 0.875rem;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  animation: fadeIn 0.3s ease;
}

@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateX(10px);
  }
  to {
    opacity: 1;
    transform: translateX(0);
  }
}

/* 右侧控制区 */
.banner-controls {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-shrink: 0;
}

/* 轮播指示器 */
.banner-dots {
  display: flex;
  align-items: center;
  gap: 0.375rem;
}

.dot {
  position: relative;
  width: 20px;
  height: 20px;
  padding: 0;
  border: none;
  background: transparent;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}

.dot-inner {
  width: 6px;
  height: 6px;
  background: rgba(255, 255, 255, 0.4);
  border-radius: 50%;
  transition: all 0.3s ease;
}

.dot.active .dot-inner,
.dot:hover .dot-inner {
  background: white;
  transform: scale(1.3);
}

/* 导航箭头 */
.banner-arrows {
  display: flex;
  align-items: center;
  gap: 0.25rem;
}

.arrow-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  padding: 0;
  border: none;
  background: rgba(255, 255, 255, 0.15);
  border-radius: 6px;
  color: white;
  cursor: pointer;
  transition: all 0.2s ease;
}

.arrow-btn:hover {
  background: rgba(255, 255, 255, 0.25);
}

.arrow-btn:active {
  transform: scale(0.95);
}

/* 关闭按钮 */
.close-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  padding: 0;
  border: none;
  background: rgba(255, 255, 255, 0.15);
  border-radius: 6px;
  color: white;
  cursor: pointer;
  transition: all 0.2s ease;
}

.close-btn:hover {
  background: rgba(255, 255, 255, 0.25);
  transform: rotate(90deg);
}

/* ==================== 过渡动画 ==================== */
.banner-enter-active,
.banner-leave-active {
  transition: all 0.3s ease;
}

.banner-enter-from {
  opacity: 0;
  transform: translateY(-100%);
}

.banner-leave-to {
  opacity: 0;
  transform: translateY(-100%);
}

/* 滑动过渡 */
.slide-left-enter-active,
.slide-left-leave-active,
.slide-right-enter-active,
.slide-right-leave-active {
  transition: all 0.3s ease;
}

.slide-left-enter-from {
  opacity: 0;
  transform: translateX(20px);
}

.slide-left-leave-to {
  opacity: 0;
  transform: translateX(-20px);
}

.slide-right-enter-from {
  opacity: 0;
  transform: translateX(-20px);
}

.slide-right-leave-to {
  opacity: 0;
  transform: translateX(20px);
}

/* ==================== 响应式 ==================== */
@media (max-width: 768px) {
  .announcement-banner {
    top: 56px; /* 移动端导航栏高度 */
  }

  .banner-container {
    padding: 0.625rem 1rem;
  }

  .announcement-icon {
    display: none; /* 移动端隐藏铃铛图标 */
  }

  .announcement-type {
    padding: 0.25rem 0.5rem;
    font-size: 0.7rem;
  }

  .announcement-text {
    font-size: 0.8125rem;
  }

  .banner-arrows {
    display: none; /* 移动端隐藏箭头，使用滑动 */
  }

  .banner-dots {
    gap: 0.25rem;
  }

  .dot {
    width: 16px;
    height: 16px;
  }

  .dot-inner {
    width: 5px;
    height: 5px;
  }

  .close-btn {
    width: 24px;
    height: 24px;
  }
}

@media (max-width: 480px) {
  .banner-controls {
    gap: 0.5rem;
  }

  .announcement-type span {
    display: none; /* 极小屏幕隐藏文字，只显示图标 */
  }
}
</style>
