<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ArrowLeft, Crown, Zap, Sword, Clock, Calendar, Image, Award } from 'lucide-vue-next'
import { getUserDetail, toggleVIP } from '@/api/user'
import type { UserDetail } from '@/types/user'

const router = useRouter()
const route = useRoute()

const loading = ref(false)
const user = ref<UserDetail | null>(null)
const toastMessage = ref('')
const showToast = ref(false)

const showToastMessage = (message: string) => {
  toastMessage.value = message
  showToast.value = true
  setTimeout(() => {
    showToast.value = false
  }, 3000)
}

const loadUserDetail = async () => {
  const userId = Number(route.params.id)
  loading.value = true
  try {
    user.value = await getUserDetail(userId)
  } catch (error) {
    console.error('加载用户详情失败:', error)
    showToastMessage('加载用户详情失败')
    setTimeout(() => router.back(), 1500)
  } finally {
    loading.value = false
  }
}

const handleToggleVIP = async () => {
  if (!user.value) return
  try {
    await toggleVIP(user.value.tg_id)
    showToastMessage('VIP 状态已切换')
    loadUserDetail()
  } catch (error) {
    console.error('切换 VIP 失败:', error)
    showToastMessage('操作失败，请稍后重试')
  }
}

const formatMinutes = (minutes: number) => {
  if (minutes < 60) return `${minutes}分钟`
  return `${(minutes / 60).toFixed(1)}小时`
}

const formatDate = (dateStr: string | null) => {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleDateString('zh-CN')
}

const formatDateTime = (dateStr: string | null) => {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleString('zh-CN')
}

onMounted(() => {
  loadUserDetail()
})
</script>

<template>
  <div class="space-y-6">
    <!-- 返回按钮和标题 -->
    <div class="flex items-center gap-4">
      <button class="p-2 rounded-lg hover:bg-gray-100 transition-colors" @click="router.back()">
        <ArrowLeft :size="20" class="text-gray-600" />
      </button>
      <div>
        <h1 class="text-2xl font-bold text-gray-900">用户详情</h1>
        <p class="text-sm text-gray-500 mt-1">查看用户详细信息</p>
      </div>
    </div>

    <!-- 加载状态 -->
    <div v-if="loading" class="space-y-6">
      <div class="card p-6 animate-pulse">
        <div class="h-6 bg-gray-200 rounded w-1/4 mb-4"></div>
        <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div v-for="i in 4" :key="i" class="h-20 bg-gray-200 rounded"></div>
        </div>
      </div>
    </div>

    <!-- 用户详情 -->
    <template v-else-if="user">
      <!-- 基本信息 -->
      <div class="card p-6">
        <div class="flex items-center justify-between mb-6">
          <h2 class="text-lg font-semibold text-gray-900">基本信息</h2>
          <button
            :class="[
              'px-4 py-2 rounded-lg text-sm font-medium transition-colors',
              user.is_vip
                ? 'bg-amber-100 text-amber-700 hover:bg-amber-200'
                : 'bg-emerald-100 text-emerald-700 hover:bg-emerald-200'
            ]"
            @click="handleToggleVIP"
          >
            <Crown :size="16" class="inline mr-1" />
            {{ user.is_vip ? '取消VIP' : '开通VIP' }}
          </button>
        </div>
        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          <div class="space-y-1">
            <p class="text-xs text-gray-400 uppercase tracking-wide">用户ID</p>
            <p class="text-lg font-semibold text-gray-900">{{ user.tg_id }}</p>
          </div>
          <div class="space-y-1">
            <p class="text-xs text-gray-400 uppercase tracking-wide">Emby账号</p>
            <p class="text-lg font-semibold text-gray-900">{{ user.emby_account || '未绑定' }}</p>
          </div>
          <div class="space-y-1">
            <p class="text-xs text-gray-400 uppercase tracking-wide">VIP状态</p>
            <span :class="['tag', user.is_vip ? 'tag-warning' : 'tag-gray']">
              <Crown v-if="user.is_vip" :size="12" class="mr-1" />
              {{ user.is_vip ? 'VIP用户' : '普通用户' }}
            </span>
          </div>
          <div class="space-y-1">
            <p class="text-xs text-gray-400 uppercase tracking-wide">注册日期</p>
            <p class="text-lg font-semibold text-gray-900">{{ formatDate(user.registered_date) }}</p>
          </div>
        </div>
      </div>

      <!-- 魔力系统 -->
      <div class="card p-6">
        <div class="flex items-center gap-2 mb-6">
          <Zap :size="18" class="text-amber-500" />
          <span class="text-lg font-semibold text-gray-900">魔力系统</span>
        </div>
        <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div class="bg-gradient-to-br from-blue-50 to-blue-100 rounded-xl p-4 text-center">
            <p class="text-sm text-blue-600 mb-1">流动魔力</p>
            <p class="text-2xl font-bold text-blue-700">{{ user.points.toLocaleString() }}</p>
          </div>
          <div class="bg-gradient-to-br from-purple-50 to-purple-100 rounded-xl p-4 text-center">
            <p class="text-sm text-purple-600 mb-1">库藏魔力</p>
            <p class="text-2xl font-bold text-purple-700">{{ user.bank_points.toLocaleString() }}</p>
          </div>
          <div class="bg-gradient-to-br from-emerald-50 to-emerald-100 rounded-xl p-4 text-center">
            <p class="text-sm text-emerald-600 mb-1">累计获得</p>
            <p class="text-2xl font-bold text-emerald-700">{{ user.total_earned.toLocaleString() }}</p>
          </div>
          <div class="bg-gradient-to-br from-red-50 to-red-100 rounded-xl p-4 text-center">
            <p class="text-sm text-red-600 mb-1">累计消费</p>
            <p class="text-2xl font-bold text-red-700">{{ user.total_spent.toLocaleString() }}</p>
          </div>
        </div>
      </div>

      <!-- 战力系统 -->
      <div class="card p-6">
        <div class="flex items-center gap-2 mb-6">
          <Sword :size="18" class="text-gray-500" />
          <span class="text-lg font-semibold text-gray-900">战力系统</span>
        </div>
        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          <div class="space-y-1">
            <p class="text-xs text-gray-400 uppercase tracking-wide">当前战力</p>
            <p class="text-lg font-semibold text-gray-900">{{ user.attack.toLocaleString() }}</p>
          </div>
          <div class="space-y-1">
            <p class="text-xs text-gray-400 uppercase tracking-wide">装备武器</p>
            <p class="text-lg font-semibold text-gray-900">{{ user.weapon || '无' }}</p>
          </div>
          <div class="space-y-1">
            <p class="text-xs text-gray-400 uppercase tracking-wide">武器耐久</p>
            <p class="text-lg font-semibold text-gray-900">{{ user.weapon_durability }}/100</p>
          </div>
          <div class="space-y-1">
            <p class="text-xs text-gray-400 uppercase tracking-wide">突破等级</p>
            <p class="text-lg font-semibold text-gray-900">{{ user.breakthrough_level }}</p>
          </div>
        </div>
      </div>

      <!-- 观影数据 -->
      <div class="card p-6">
        <div class="flex items-center gap-2 mb-6">
          <Clock :size="18" class="text-gray-500" />
          <span class="text-lg font-semibold text-gray-900">观影数据</span>
        </div>
        <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div class="bg-gray-50 rounded-xl p-4 text-center">
            <p class="text-sm text-gray-500 mb-1">总观影时长</p>
            <p class="text-xl font-bold text-gray-900">{{ formatMinutes(user.total_watch_minutes) }}</p>
          </div>
          <div class="bg-gray-50 rounded-xl p-4 text-center">
            <p class="text-sm text-gray-500 mb-1">今日观影</p>
            <p class="text-xl font-bold text-gray-900">{{ user.daily_watch_minutes }}分钟</p>
          </div>
          <div class="bg-gray-50 rounded-xl p-4 text-center">
            <p class="text-sm text-gray-500 mb-1">连续打卡</p>
            <p class="text-xl font-bold text-gray-900">{{ user.watch_streak }}天</p>
          </div>
          <div class="bg-gray-50 rounded-xl p-4 text-center">
            <p class="text-sm text-gray-500 mb-1">最长打卡</p>
            <p class="text-xl font-bold text-gray-900">{{ user.max_watch_streak }}天</p>
          </div>
        </div>
      </div>

      <!-- 签到数据 -->
      <div class="card p-6">
        <div class="flex items-center gap-2 mb-6">
          <Calendar :size="18" class="text-gray-500" />
          <span class="text-lg font-semibold text-gray-900">签到数据</span>
        </div>
        <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div class="space-y-1">
            <p class="text-xs text-gray-400 uppercase tracking-wide">累计签到</p>
            <p class="text-lg font-semibold text-gray-900">{{ user.total_checkin_days }} 天</p>
          </div>
          <div class="space-y-1">
            <p class="text-xs text-gray-400 uppercase tracking-wide">连续签到</p>
            <p class="text-lg font-semibold text-gray-900">{{ user.consecutive_checkin }} 天</p>
          </div>
          <div class="space-y-1">
            <p class="text-xs text-gray-400 uppercase tracking-wide">上次签到</p>
            <p class="text-lg font-semibold text-gray-900">{{ formatDateTime(user.last_checkin_date) || '从未签到' }}</p>
          </div>
        </div>
      </div>

      <!-- 外观装备 -->
      <div class="card p-6">
        <div class="flex items-center gap-2 mb-6">
          <Image :size="18" class="text-gray-500" />
          <span class="text-lg font-semibold text-gray-900">外观装备</span>
        </div>
        <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div class="space-y-1">
            <p class="text-xs text-gray-400 uppercase tracking-wide">当前头像框</p>
            <p class="text-lg font-semibold text-gray-900">{{ user.equipped_frame || '无' }}</p>
          </div>
          <div class="space-y-1">
            <p class="text-xs text-gray-400 uppercase tracking-wide">当前称号</p>
            <span :class="['tag', 'tag-purple']">
              <Award :size="12" class="mr-1" />
              {{ user.equipped_title || '无' }}
            </span>
          </div>
        </div>
      </div>
    </template>

    <!-- Toast 提示 -->
    <Transition
      enter-active-class="transition-all duration-300"
      enter-from-class="opacity-0 translate-x-4"
      enter-to-class="opacity-100 translate-x-0"
      leave-active-class="transition-all duration-300"
      leave-from-class="opacity-100 translate-x-0"
      leave-to-class="opacity-0 translate-x-4"
    >
      <div v-if="showToast" class="toast toast-info">
        <span class="text-xl">ℹ</span>
        <span>{{ toastMessage }}</span>
      </div>
    </Transition>
  </div>
</template>
