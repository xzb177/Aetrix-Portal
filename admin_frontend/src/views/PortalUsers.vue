<script setup lang="ts">
import { ref, onMounted, computed, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import {
  RefreshCw,
  UserPlus,
  ChevronDown,
  Loader2,
  Users,
  UserCheck,
  Crown,
  MonitorPlay,
} from 'lucide-vue-next'
import {
  getPortalUsers,
  getPortalUserDetail,
  updatePortalUserStatus,
  deletePortalUser,
  getPortalUserStats,
  type PortalUser,
} from '@/api/portal'
import { TopBar, StatCard, SearchBar, PrimaryButton, IconButton, Chip } from '@/components/ui'
import FilterBar, { type FilterOptions } from '@/components/users/FilterBar.vue'
import UserCard, { type UserCardData } from '@/components/users/UserCard.vue'
import UserDetailSheet, { type UserDetail } from '@/components/users/UserDetailSheet.vue'
import UserListState from '@/components/users/UserListState.vue'

const router = useRouter()
const route = useRoute()

// 数据状态
const users = ref<PortalUser[]>([])
const stats = ref({
  total_users: 0,
  active_users: 0,
  vip_users: 0,
  emby_accounts: 0,
})

// 加载状态
const loading = ref(false)
const refreshing = ref(false)
const error = ref<string | null>(null)

// 筛选条件
const filters = ref<FilterOptions>({
  keyword: '',
  is_vip_only: false,
  status: 'all',
  time_range: 'all',
})

// 分页
const pagination = ref({
  skip: 0,
  limit: 20,
  hasMore: false,
})

// 用户详情
const selectedUser = ref<UserDetail | null>(null)
const detailLoading = ref(false)
const showDetail = ref(false)

// 列表状态
const listState = computed<'loading' | 'empty' | 'error' | 'data'>(() => {
  if (error.value) return 'error'
  if (loading.value) return 'loading'
  if (users.value.length === 0) {
    return filters.value.keyword || filters.value.is_vip_only ? 'empty' : 'empty'
  }
  return 'data'
})

// 统计卡片数据
const statCards = computed(() => [
  {
    id: 'total',
    label: '总用户',
    value: stats.value.total_users,
    icon: Users,
    color: 'primary' as const,
  },
  {
    id: 'active',
    label: '活跃',
    value: stats.value.active_users,
    icon: UserCheck,
    color: 'success' as const,
  },
  {
    id: 'vip',
    label: 'VIP',
    value: stats.value.vip_users,
    icon: Crown,
    color: 'warning' as const,
  },
  {
    id: 'emby',
    label: 'Emby',
    value: stats.value.emby_accounts,
    icon: MonitorPlay,
    color: 'info' as const,
  },
])

// 转换用户数据为卡片数据
const cardUsers = computed<UserCardData[]>(() => {
  return users.value.map((user: any): UserCardData => ({
    id: user.id,
    username: user.username,
    email: user.email,
    telegram_id: user.telegram_id,
    is_active: user.is_active,
    is_vip: user.is_vip,
    is_staff: user.is_staff,
    current_plan: user.current_plan,
    emby_account_count: user.emby_account_count,
    created_at: user.created_at,
    vip_expires_at: user.vip_expires_at,
  }))
})

// 加载用户列表
const loadUsers = async (showRefreshLoading = false) => {
  if (showRefreshLoading) {
    refreshing.value = true
  } else {
    loading.value = true
  }
  error.value = null

  try {
    const res = await getPortalUsers({
      search: filters.value.keyword || undefined,
      is_vip_only: filters.value.is_vip_only,
      is_active: filters.value.status === 'active' ? true : filters.value.status === 'inactive' ? false : undefined,
      skip: pagination.value.skip,
      limit: pagination.value.limit,
    })
    users.value = res
    pagination.value.hasMore = res.length >= pagination.value.limit
  } catch (err: any) {
    console.error('加载用户列表失败:', err)
    error.value = err.message || '加载失败，请稍后重试'
  } finally {
    loading.value = false
    refreshing.value = false
  }
}

// 加载统计数据
const loadStats = async () => {
  try {
    const res = await getPortalUserStats()
    stats.value = res
  } catch (err) {
    console.error('加载统计数据失败:', err)
  }
}

// 筛选搜索
const handleSearch = (newFilters: FilterOptions) => {
  filters.value = newFilters
  pagination.value.skip = 0
  loadUsers()
}

// 重置筛选
const handleReset = () => {
  filters.value = {
    keyword: '',
    is_vip_only: false,
    status: 'all',
    time_range: 'all',
  }
  pagination.value.skip = 0
  loadUsers()
}

// 刷新
const handleRefresh = () => {
  loadStats()
  loadUsers(true)
}

// 查看详情
const handleViewDetail = async (user: UserCardData) => {
  selectedUser.value = null
  showDetail.value = true
  detailLoading.value = true

  try {
    const res = await getPortalUserDetail(user.id)
    selectedUser.value = res
  } catch (err) {
    console.error('加载用户详情失败:', err)
    showDetail.value = false
  } finally {
    detailLoading.value = false
  }
}

// 切换用户状态
const handleToggleStatus = async (user: UserCardData, type: 'active' | 'staff') => {
  const key = type === 'active' ? 'is_active' : 'is_staff'
  const newValue = !user[key]

  try {
    await updatePortalUserStatus(user.id, { [key]: newValue })
    // 更新本地数据
    const targetUser = users.value.find((u: any) => u.id === user.id)
    if (targetUser) {
      targetUser[key] = newValue
    }
    // 如果是详情页操作，也更新详情数据
    if (selectedUser.value && selectedUser.value.id === user.id) {
      (selectedUser.value as any)[key] = newValue
    }
    loadStats()
  } catch (err) {
    console.error('更新用户状态失败:', err)
    throw err
  }
}

// 从详情页切换状态（包装函数）
const handleDetailToggleStatus = async (type: 'active' | 'staff') => {
  if (!selectedUser.value) return
  const user: UserCardData = {
    id: selectedUser.value.id,
    username: selectedUser.value.username,
    is_active: selectedUser.value.is_active,
    is_staff: selectedUser.value.is_staff,
    is_vip: selectedUser.value.is_vip,
    email: selectedUser.value.email,
    telegram_id: selectedUser.value.telegram_id,
    created_at: selectedUser.value.created_at,
  }
  await handleToggleStatus(user, type)
}

// 删除用户
const handleDelete = async (user: UserCardData) => {
  try {
    await deletePortalUser(user.id)
    showDetail.value = false
    loadUsers()
    loadStats()
  } catch (err) {
    console.error('删除用户失败:', err)
    throw err
  }
}

// 从详情页删除（包装函数）
const handleDetailDelete = async () => {
  if (!selectedUser.value) return
  await handleDelete({
    id: selectedUser.value.id,
    username: selectedUser.value.username,
    is_active: selectedUser.value.is_active,
    is_staff: selectedUser.value.is_staff,
    is_vip: selectedUser.value.is_vip,
    email: selectedUser.value.email,
    telegram_id: selectedUser.value.telegram_id,
    created_at: selectedUser.value.created_at,
  })
}

// 关闭详情
const handleCloseDetail = () => {
  showDetail.value = false
  selectedUser.value = null
}

// 加载更多
const loadMore = () => {
  if (pagination.value.hasMore && !refreshing.value) {
    pagination.value.skip += pagination.value.limit
    // 这里可以实现追加加载逻辑
    loadUsers(true)
  }
}

// 从 URL 读取初始筛选条件
onMounted(() => {
  const urlFilter = route.query.filter as string
  if (urlFilter === 'vip') {
    filters.value.is_vip_only = true
  } else if (urlFilter === 'expiring') {
    filters.value.status = 'active'
    // 可以添加更多特定筛选逻辑
  }

  loadUsers()
  loadStats()
})

// 定时刷新
let refreshInterval: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  refreshInterval = setInterval(() => {
    if (!showDetail.value) {
      loadStats()
    }
  }, 30000)
})

onUnmounted(() => {
  if (refreshInterval) {
    clearInterval(refreshInterval)
  }
})
</script>

<template>
  <div class="portal-users-page">
    <!-- 顶部导航栏 -->
    <TopBar
      title="门户用户"
      subtitle="管理 Web 端注册用户"
    >
      <template #actions>
        <IconButton
          :icon="RefreshCw"
          :disabled="refreshing"
          @click="handleRefresh"
        />
        <PrimaryButton
          :icon="UserPlus"
          size="sm"
          @click="router.push('/portal-users?action=add')"
        >
          添加用户
        </PrimaryButton>
      </template>
    </TopBar>

    <div class="page-content">
      <!-- 统计卡片网格 -->
      <div class="stats-grid">
        <StatCard
          v-for="stat in statCards"
          :key="stat.id"
          v-bind="stat"
        />
      </div>

      <!-- 筛选栏 -->
      <FilterBar
        :loading="loading || refreshing"
        @search="handleSearch"
        @reset="handleReset"
      />

      <!-- 用户列表 -->
      <div class="users-list">
        <!-- 加载/空/错误状态 -->
        <UserListState
          v-if="listState !== 'data'"
          :type="listState"
          :searchable="!!filters.keyword || filters.is_vip_only"
          @retry="handleRefresh"
        />

        <!-- 用户卡片列表 -->
        <template v-else>
          <div class="user-cards">
            <UserCard
              v-for="user in cardUsers"
              :key="user.id"
              :user="user"
              @click="handleViewDetail"
              @view-detail="handleViewDetail"
              @toggle-status="handleToggleStatus"
              @delete="handleDelete"
            />
          </div>

          <!-- 加载更多 -->
          <div v-if="pagination.hasMore" class="load-more">
            <PrimaryButton
              variant="ghost"
              :loading="refreshing"
              @click="loadMore"
            >
              <template #icon>
                <ChevronDown v-if="!refreshing" :size="16" />
              </template>
              {{ refreshing ? '加载中...' : '加载更多' }}
            </PrimaryButton>
          </div>
        </template>
      </div>
    </div>

    <!-- 用户详情抽屉 -->
    <UserDetailSheet
      :user="selectedUser"
      :loading="detailLoading"
      @close="handleCloseDetail"
      @toggle-status="handleDetailToggleStatus"
      @delete="handleDetailDelete"
    />
  </div>
</template>

<style scoped>
.portal-users-page {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  background: var(--bg-primary);
}

.page-content {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-4);
}

/* 统计卡片网格 2x2 */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--space-3);
}

/* 用户列表 */
.users-list {
  flex: 1;
}

.user-cards {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

/* 加载更多 */
.load-more {
  display: flex;
  justify-content: center;
  padding: var(--space-5) 0;
}

/* 响应式 */
@media (max-width: 480px) {
  .stats-grid {
    grid-template-columns: 1fr;
    gap: var(--space-2);
  }
}
</style>
