<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { RouterLink } from 'vue-router'
import { useUserStore } from '@/stores/user'
import {
  Calendar,
  Gift,
  Flame,
  CheckCircle,
  ChevronRight,
  Sparkles,
  Trophy,
  Tv,
  Menu,
  X
} from 'lucide-vue-next'

const userStore = useUserStore()

// 移动端菜单
const mobileMenuOpen = ref(false)

// 签到状态
const checkInData = ref({
  totalDays: 0,
  streakDays: 0,
  todayChecked: false,
  todayReward: 10,
  history: [] as { date: string, reward: number }[]
})

const loading = ref(false)
const checkingIn = ref(false)

// 连续签到奖励
const streakRewards = [
  { days: 1, reward: 10, bonus: 0 },
  { days: 3, reward: 15, bonus: 5 },
  { days: 7, reward: 20, bonus: 10 },
  { days: 15, reward: 30, bonus: 20 },
  { days: 30, reward: 50, bonus: 50 },
]

// 签到
async function handleCheckIn() {
  if (checkingIn.value || checkInData.value.todayChecked) return

  checkingIn.value = true
  try {
    // TODO: 调用签到 API
    // const response = await checkinApi.checkIn()
    // checkInData.value = response.data

    // 模拟签到成功
    checkInData.value.todayChecked = true
    checkInData.value.totalDays += 1
    checkInData.value.streakDays += 1
    checkInData.value.history.push({
      date: new Date().toISOString().split('T')[0] || new Date().toISOString(),
      reward: checkInData.value.todayReward
    })
  } catch (error) {
    console.error('签到失败:', error)
  } finally {
    checkingIn.value = false
  }
}

// 获取签到信息
async function fetchCheckInData() {
  loading.value = true
  try {
    // TODO: 调用 API
    // const response = await checkinApi.getData()
    // checkInData.value = response.data
  } catch (error) {
    console.error('获取签到数据失败:', error)
  } finally {
    loading.value = false
  }
}

// 计算下一个奖励
const nextReward = computed(() => {
  const currentStreak = checkInData.value.streakDays
  const next = streakRewards.find(r => r.days > currentStreak)
  if (next) {
    return next
  }
  return null
})

onMounted(() => {
  fetchCheckInData()
})
</script>

<template>
  <div class="min-h-screen bg-gray-50">
    <!-- 导航栏 -->
    <nav class="sticky top-0 z-50 bg-white/80 backdrop-blur-md border-b border-gray-200">
      <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div class="flex items-center justify-between h-16">
          <RouterLink to="/" class="flex items-center gap-3">
            <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-emerald-500 to-purple-600 flex items-center justify-center">
              <Tv :size="24" class="text-white" />
            </div>
            <span class="text-lg font-bold text-gray-900">Aetrix</span>
          </RouterLink>

          <!-- 桌面端导航 -->
          <div class="hidden md:flex items-center gap-4">
            <RouterLink to="/dashboard" class="text-gray-600 hover:text-gray-900 font-medium">控制台</RouterLink>
            <RouterLink to="/checkin" class="px-4 py-2 bg-gradient-to-r from-emerald-500 to-purple-600 text-white rounded-full font-medium">签到</RouterLink>
          </div>

          <!-- 移动端菜单按钮 -->
          <button
            @click="mobileMenuOpen = !mobileMenuOpen"
            class="md:hidden p-2 rounded-lg hover:bg-gray-100 transition-colors"
          >
            <Menu v-if="!mobileMenuOpen" :size="24" class="text-gray-600" />
            <X v-else :size="24" class="text-gray-600" />
          </button>
        </div>

        <!-- 移动端菜单 -->
        <div
          v-if="mobileMenuOpen"
          class="md:hidden py-4 border-t border-gray-200"
        >
          <div class="flex flex-col gap-2">
            <RouterLink
              to="/dashboard"
              @click="mobileMenuOpen = false"
              class="flex items-center gap-2 px-4 py-3 rounded-xl text-gray-600 hover:bg-gray-100"
            >
              控制台
            </RouterLink>
            <RouterLink
              to="/checkin"
              @click="mobileMenuOpen = false"
              class="flex items-center gap-2 px-4 py-3 rounded-xl bg-gradient-to-r from-emerald-500 to-purple-600 text-white"
            >
              签到
            </RouterLink>
          </div>
        </div>
      </div>
    </nav>

    <div class="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-6 md:py-8">
      <!-- 返回导航 -->
      <div class="mb-4 md:mb-6">
        <RouterLink to="/dashboard" class="inline-flex items-center text-gray-600 hover:text-gray-900 text-sm">
          <ChevronRight :size="16" class="rotate-180" />
          返回控制台
        </RouterLink>
      </div>

      <!-- 主卡片 -->
      <div class="bg-white rounded-2xl md:rounded-3xl shadow-lg overflow-hidden">
        <!-- 头部 -->
        <div class="bg-gradient-to-r from-emerald-500 to-purple-600 p-6 md:p-8 text-white">
          <div class="flex items-center gap-2 md:gap-3 mb-2">
            <Calendar :size="24" class="md:w-8 md:h-8" />
            <h1 class="text-xl md:text-2xl font-bold">每日签到</h1>
          </div>
          <p class="text-white/80 text-sm md:text-base">坚持签到，累积奖励</p>
        </div>

        <div v-if="loading" class="p-8 md:p-12 text-center">
          <div class="inline-block w-6 h-6 md:w-8 md:h-8 border-3 md:border-4 border-emerald-500 border-t-transparent rounded-full animate-spin"></div>
          <p class="text-gray-500 mt-4 text-sm md:text-base">加载中...</p>
        </div>

        <div v-else class="p-4 md:p-8">
          <!-- 签到状态卡片 -->
          <div class="text-center mb-6 md:mb-8">
            <!-- 已签到 -->
            <div v-if="checkInData.todayChecked" class="py-6 md:py-8">
              <div class="w-16 h-16 md:w-24 md:h-24 mx-auto mb-3 md:mb-4 rounded-full bg-gradient-to-br from-emerald-400 to-emerald-500 flex items-center justify-center">
                <CheckCircle :size="32" class="md:w-12 md:h-12 text-white" />
              </div>
              <h2 class="text-xl md:text-2xl font-bold text-gray-900 mb-2">今日已签到</h2>
              <p class="text-gray-500 text-sm md:text-base">已连续签到 {{ checkInData.streakDays }} 天</p>
            </div>

            <!-- 未签到 -->
            <div v-else class="py-6 md:py-8">
              <div class="w-16 h-16 md:w-24 md:h-24 mx-auto mb-3 md:mb-4 rounded-full bg-gradient-to-br from-amber-400 to-orange-500 flex items-center justify-center animate-pulse">
                <Gift :size="32" class="md:w-12 md:h-12 text-white" />
              </div>
              <h2 class="text-xl md:text-2xl font-bold text-gray-900 mb-2">今日尚未签到</h2>
              <p class="text-gray-500 mb-4 md:mb-6 text-sm md:text-base">签到可获得 {{ checkInData.todayReward }} 余额</p>
              <button
                @click="handleCheckIn"
                :disabled="checkingIn"
                class="inline-flex items-center gap-2 px-6 md:px-8 py-3 md:py-4 bg-gradient-to-r from-emerald-500 to-purple-600 text-white rounded-full font-bold text-base md:text-lg hover:shadow-xl transition-all disabled:opacity-50 disabled:cursor-not-allowed hover:-translate-y-1 w-full md:w-auto"
              >
                <Sparkles :size="18" class="md:w-5" />
                {{ checkingIn ? '签到中...' : '立即签到' }}
              </button>
            </div>
          </div>

          <!-- 统计数据 -->
          <div class="grid grid-cols-3 gap-2 md:gap-4 mb-6 md:mb-8">
            <div class="text-center p-3 md:p-4 bg-gray-50 rounded-xl md:rounded-2xl">
              <p class="text-2xl md:text-3xl font-bold text-gradient">{{ checkInData.totalDays }}</p>
              <p class="text-gray-500 text-xs md:text-sm mt-1">累计签到</p>
            </div>
            <div class="text-center p-3 md:p-4 bg-gray-50 rounded-xl md:rounded-2xl">
              <p class="text-2xl md:text-3xl font-bold text-gradient">{{ checkInData.streakDays }}</p>
              <p class="text-gray-500 text-xs md:text-sm mt-1">连续签到</p>
            </div>
            <div class="text-center p-3 md:p-4 bg-gray-50 rounded-xl md:rounded-2xl">
              <p class="text-2xl md:text-3xl font-bold text-gradient">{{ checkInData.todayReward }}</p>
              <p class="text-gray-500 text-xs md:text-sm mt-1">今日奖励</p>
            </div>
          </div>

          <!-- 连续签到奖励 -->
          <div class="mb-6 md:mb-8">
            <h3 class="text-base md:text-lg font-bold text-gray-900 mb-3 md:mb-4 flex items-center gap-2">
              <Flame :size="18" class="md:w-5 text-orange-500" />
              连续签到奖励
            </h3>
            <div class="flex gap-2 md:gap-3 overflow-x-auto pb-2 -mx-4 px-4 md:mx-0 md:px-0">
              <div
                v-for="reward in streakRewards"
                :key="reward.days"
                class="flex-shrink-0 w-20 md:w-24 text-center p-3 md:p-4 rounded-xl md:rounded-2xl transition-all"
                :class="{
                  'bg-gradient-to-br from-emerald-500 to-teal-500 text-white': checkInData.streakDays >= reward.days,
                  'bg-gray-100': checkInData.streakDays < reward.days,
                  'ring-2 ring-emerald-500': checkInData.streakDays === reward.days
                }"
              >
                <p class="text-base md:text-lg font-bold">{{ reward.days }}天</p>
                <p class="text-xs md:text-sm opacity-80">{{ reward.reward }}余额</p>
                <p v-if="reward.bonus > 0" class="text-xs opacity-70">+{{ reward.bonus }}奖励</p>
              </div>
            </div>
          </div>

          <!-- 下一个奖励 -->
          <div v-if="nextReward && !checkInData.todayChecked" class="p-3 md:p-4 bg-gradient-to-r from-amber-50 to-orange-50 rounded-xl md:rounded-2xl mb-6 md:mb-8">
            <div class="flex items-center justify-between gap-3">
              <div class="flex items-center gap-2 md:gap-3">
                <div class="w-10 h-10 md:w-12 md:h-12 rounded-xl bg-gradient-to-br from-amber-400 to-orange-500 flex items-center justify-center flex-shrink-0">
                  <Trophy :size="20" class="md:w-6 text-white" />
                </div>
                <div class="min-w-0">
                  <p class="text-xs md:text-sm text-gray-600">下一个里程碑</p>
                  <p class="font-bold text-gray-900 text-sm md:text-base truncate">连续签到 {{ nextReward.days }} 天</p>
                </div>
              </div>
              <div class="text-right flex-shrink-0">
                <p class="text-xs md:text-sm text-gray-600">可获</p>
                <p class="font-bold text-emerald-600 text-sm md:text-base">{{ nextReward.reward + nextReward.bonus }} 余额</p>
              </div>
            </div>
          </div>

          <!-- 签到记录 -->
          <div v-if="checkInData.history.length > 0">
            <h3 class="text-base md:text-lg font-bold text-gray-900 mb-3 md:mb-4">最近签到记录</h3>
            <div class="space-y-2">
              <div
                v-for="(record, index) in checkInData.history.slice(0, 7)"
                :key="index"
                class="flex items-center justify-between p-2.5 md:p-3 bg-gray-50 rounded-xl"
              >
                <div class="flex items-center gap-2 md:gap-3 min-w-0">
                  <CheckCircle :size="16" class="md:w-5 text-emerald-500 flex-shrink-0" />
                  <span class="text-gray-700 text-xs md:text-sm truncate">{{ record.date }}</span>
                </div>
                <span class="font-bold text-emerald-600 text-xs md:text-sm flex-shrink-0">+{{ record.reward }} 余额</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.text-gradient {
  background: linear-gradient(135deg, #10b981 0%, #8b5cf6 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}
</style>
