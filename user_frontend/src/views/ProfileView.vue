<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { userApi, subscriptionApi } from '@/api'
import ProfileHeader from '@/components/profile/ProfileHeader.vue'
import EmbyCard from '@/components/profile/EmbyCard.vue'
import QuickGrid from '@/components/profile/QuickGrid.vue'
import SettingsList from '@/components/profile/SettingsList.vue'
import { useToast } from '@/composables/useToast'
import { useAuthSheet } from '@/composables/useAuthSheet'

const router = useRouter()
const userStore = useUserStore()
const toast = useToast()
const { openAuthSheet } = useAuthSheet()

const profile = ref<any>(null)
const loading = ref(true)
const embyAccounts = ref<any[]>([])
const claimingAccount = ref(false)
const vipExpiry = ref<string | undefined>(undefined)

const isLoggedIn = computed(() => userStore.isLoggedIn)
const isVIP = computed(() => userStore.isVIP)

onMounted(async () => {
  if (!isLoggedIn.value) {
    openAuthSheet()
    return
  }
  await Promise.all([fetchProfile(), fetchEmbyAccounts(), fetchSubscription()])
})

async function fetchProfile() {
  try {
    const res = await userApi.getProfile()
    profile.value = res.data || res
  } catch (error) {
    console.error('Failed to fetch profile:', error)
    // 如果 API 失败，尝试从 store 获取用户信息
    if (userStore.user) {
      profile.value = userStore.user
    }
  }
}

async function fetchEmbyAccounts() {
  try {
    const res = await fetch('/api/user/emby/servers', {
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('access_token')}`
      }
    })
    if (res.ok) {
      const data = await res.json()
      embyAccounts.value = data
    }
  } catch (error) {
    console.error('Failed to fetch Emby accounts:', error)
  } finally {
    loading.value = false
  }
}

async function fetchSubscription() {
  try {
    const res = await subscriptionApi.getMySubscription()
    if (res.data && res.data.expires_at) {
      vipExpiry.value = res.data.expires_at
      // 更新 store 中的 VIP 状态
      if (!userStore.isVIP) {
        userStore.updateUser({ is_vip: true })
      }
    }
  } catch (error) {
    // 没有订阅或订阅已过期是正常情况
    vipExpiry.value = undefined
  }
}

async function handleClaimAccount() {
  if (claimingAccount.value) return

  claimingAccount.value = true
  try {
    const res = await fetch('/api/user/emby/claim', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        'Content-Type': 'application/json'
      }
    })

    if (res.ok) {
      const data = await res.json()
      toast.success('账号领取成功')
      await fetchEmbyAccounts()
    } else {
      const error = await res.json()
      toast.error(error.detail || '领取失败，请稍后重试')
    }
  } catch (error) {
    console.error('Failed to claim account:', error)
    toast.error('网络异常，请稍后重试')
  } finally {
    claimingAccount.value = false
  }
}

function handleCopy(text: string, type: string) {
  toast.success('已复制到剪贴板')
}

function handleLogout() {
  userStore.logout()
  router.push('/')
}

const settingsItems = computed(() => {
  if (!profile.value) return []

  return [
    {
      label: '用户 ID',
      value: `#${profile.value.id}`,
      copyable: true,
      copyValue: String(profile.value.id)
    },
    {
      label: '注册时间',
      value: formatDate(profile.value.registered_date),
      copyable: false
    }
  ]
})

function formatDate(dateStr?: string) {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  })
}
</script>

<template>
  <div class="profile-page">
    <div class="profile-container">
      <!-- Loading Skeleton -->
      <div v-if="loading" class="profile-content">
        <ProfileHeader :profile="null" :loading="true" />
        <EmbyCard :is-VIP="false" :emby-accounts="[]" :loading="true" />
        <QuickGrid />
        <SettingsList :items="[]" />
      </div>

      <!-- Profile Content -->
      <div v-else class="profile-content">
        <!-- 顶部概览条 -->
        <ProfileHeader
          :profile="profile || userStore.user"
          :is-VIP="isVIP"
          :vip-expiry="vipExpiry"
        />

        <!-- Emby 账号主卡（三态） -->
        <EmbyCard
          :is-VIP="isVIP"
          :emby-accounts="embyAccounts"
          :vip-expiry="vipExpiry"
          @claim-account="handleClaimAccount"
          @copy="handleCopy"
        />

        <!-- 快捷入口宫格 -->
        <QuickGrid />

        <!-- 账号信息设置列表 -->
        <SettingsList
          :items="settingsItems"
          @logout="handleLogout"
          @copy="handleCopy"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
.profile-page {
  min-height: 100vh;
  background: var(--bg-primary);
  padding: 0;
}

.profile-container {
  max-width: 600px;
  margin: 0 auto;
}

.profile-content {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  padding: 0.75rem 1rem 2rem;
}

/* 确保页面背景是纯黑，更符合 Apple TV+ 风格 */
:deep(.bg-card) {
  background: var(--bg-card);
}
</style>
