<script setup lang="ts">
/**
 * 家庭席位页面
 * 创建家庭、邀请成员、管理子账号
 */
import { ref, onMounted } from 'vue'
import { familyApi } from '@/api/innovations'
import type { FamilyInfo } from '@/api/types'
import { Users, UserPlus, Crown, Shield, Trash2 } from 'lucide-vue-next'

const family = ref<FamilyInfo | null>(null)
const loading = ref(true)
const creating = ref(false)
const inviteUsername = ref('')
const inviteNickname = ref('')
const showInvite = ref(false)

const plans = [
  { type: 'standard', name: '标准家庭', max: 3, desc: '3 个成员，适合小家庭' },
  { type: 'premium', name: '高级家庭', max: 5, desc: '5 个成员，适合大家庭' },
  { type: 'elite', name: '旗舰家庭', max: 8, desc: '8 个成员，适合团队共享' },
]

async function loadFamily() {
  loading.value = true
  try {
    family.value = await familyApi.getInfo() as unknown as FamilyInfo
  } catch (e) {
    console.error('加载家庭信息失败:', e)
  } finally {
    loading.value = false
  }
}

async function createFamily(planType: string) {
  creating.value = true
  try {
    await familyApi.create(planType)
    await loadFamily()
  } catch (e: any) {
    alert(e?.response?.data?.detail || '创建失败')
  } finally {
    creating.value = false
  }
}

async function addMember() {
  if (!inviteUsername.value.trim()) return
  try {
    await familyApi.addMember(inviteUsername.value.trim(), inviteNickname.value.trim())
    inviteUsername.value = ''
    inviteNickname.value = ''
    showInvite.value = false
    await loadFamily()
  } catch (e: any) {
    alert(e?.response?.data?.detail || '邀请失败')
  }
}

async function removeMember(memberId: number) {
  if (!confirm('确定要移除该成员吗？')) return
  try {
    await familyApi.removeMember(memberId)
    await loadFamily()
  } catch (e: any) {
    alert(e?.response?.data?.detail || '移除失败')
  }
}

onMounted(loadFamily)
</script>

<template>
  <div class="family-page">
    <div class="page-header">
      <h1><Users :size="24" /> 家庭席位</h1>
      <p class="subtitle">与家人共享 Emby 观影体验</p>
    </div>

    <!-- 加载中 -->
    <div v-if="loading" class="loading-state">加载中...</div>

    <!-- 未创建家庭 -->
    <div v-else-if="family && !family.has_family" class="create-section">
      <h2>创建你的家庭组</h2>
      <div class="plan-cards">
        <div
          v-for="plan in plans"
          :key="plan.type"
          class="plan-card"
          @click="createFamily(plan.type)"
        >
          <Crown :size="32" />
          <h3>{{ plan.name }}</h3>
          <p class="max-members">最多 {{ plan.max }} 人</p>
          <p class="desc">{{ plan.desc }}</p>
          <button class="btn-create" :disabled="creating">
            {{ creating ? '创建中...' : '创建' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 已有家庭 -->
    <div v-else-if="family?.has_family" class="family-info">
      <div class="family-header">
        <div>
          <h2>{{ family.plan_name }}</h2>
          <p>{{ family.current_members }}/{{ family.max_members }} 成员</p>
        </div>
        <button class="btn-invite" @click="showInvite = !showInvite">
          <UserPlus :size="16" /> 邀请成员
        </button>
      </div>

      <!-- 邀请表单 -->
      <div v-if="showInvite" class="invite-form">
        <input v-model="inviteUsername" placeholder="用户名" />
        <input v-model="inviteNickname" placeholder="昵称（可选）" />
        <button @click="addMember" class="btn-confirm">确认邀请</button>
      </div>

      <!-- 成员列表 -->
      <div class="member-list">
        <div v-for="member in family.members" :key="member.id" class="member-card">
          <div class="member-info">
            <div class="avatar">{{ member.nickname?.[0] || member.username[0] }}</div>
            <div>
              <p class="name">{{ member.nickname || member.username }}</p>
              <p class="role">
                <Shield :size="12" v-if="member.role === 'member'" />
                {{ member.role === 'owner' ? '管理员' : '成员' }}
              </p>
            </div>
          </div>
          <button
            v-if="member.role !== 'owner'"
            class="btn-remove"
            @click="removeMember(member.id)"
          >
            <Trash2 :size="14" />
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.family-page {
  padding: 1rem;
  max-width: 600px;
  margin: 0 auto;
}
.page-header { margin-bottom: 1.5rem; }
.page-header h1 { display: flex; align-items: center; gap: 0.5rem; font-size: 1.5rem; }
.subtitle { color: #888; margin-top: 0.25rem; }
.plan-cards { display: grid; gap: 1rem; margin-top: 1rem; }
.plan-card {
  border: 1px solid #e5e7eb; border-radius: 12px; padding: 1.5rem;
  text-align: center; cursor: pointer; transition: all 0.2s;
}
.plan-card:hover { border-color: #3b82f6; box-shadow: 0 4px 12px rgba(59,130,246,0.15); }
.max-members { font-size: 1.25rem; font-weight: 600; color: #3b82f6; }
.desc { color: #666; font-size: 0.875rem; }
.btn-create {
  margin-top: 1rem; padding: 0.5rem 2rem; background: #3b82f6; color: white;
  border: none; border-radius: 8px; cursor: pointer;
}
.family-header {
  display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem;
}
.btn-invite {
  display: flex; align-items: center; gap: 0.25rem; padding: 0.5rem 1rem;
  background: #10b981; color: white; border: none; border-radius: 8px; cursor: pointer;
}
.invite-form {
  display: flex; gap: 0.5rem; margin-bottom: 1rem; flex-wrap: wrap;
}
.invite-form input {
  flex: 1; min-width: 120px; padding: 0.5rem; border: 1px solid #d1d5db; border-radius: 6px;
}
.btn-confirm {
  padding: 0.5rem 1rem; background: #3b82f6; color: white; border: none; border-radius: 6px; cursor: pointer;
}
.member-list { display: grid; gap: 0.75rem; }
.member-card {
  display: flex; justify-content: space-between; align-items: center;
  padding: 0.75rem 1rem; background: #f9fafb; border-radius: 10px;
}
.member-info { display: flex; align-items: center; gap: 0.75rem; }
.avatar {
  width: 36px; height: 36px; border-radius: 50%; background: #3b82f6; color: white;
  display: flex; align-items: center; justify-content: center; font-weight: 600;
}
.name { font-weight: 500; }
.role { font-size: 0.75rem; color: #888; display: flex; align-items: center; gap: 0.25rem; }
.btn-remove {
  background: none; border: none; color: #ef4444; cursor: pointer; padding: 0.25rem;
}
</style>
