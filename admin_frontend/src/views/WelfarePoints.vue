<script setup lang="ts">
/**
 * 公益服·积分与公益配置：SystemConfig 表单
 */
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { RefreshCw, Save } from 'lucide-vue-next'
import { fetchWelfareConfig, saveWelfareConfig } from '@/api/welfare'

const loading = ref(false)
const saving = ref(false)
const form = ref<Record<string, string>>({})

const fields = [
  { key: 'points_signin_min', label: '签到最低分/天', hint: '默认 1' },
  { key: 'points_signin_max', label: '签到最高分/天', hint: '默认 3' },
  { key: 'points_signin_streak_bonus', label: '连签奖励分', hint: '连续7天，默认 2' },
  { key: 'points_chat_daily_cap', label: '发言每日上限', hint: '默认 20' },
  { key: 'points_redeem_7d', label: '兑换7天所需积分', hint: '默认 100' },
  { key: 'points_redeem_30d', label: '兑换30天所需积分', hint: '默认 300' },
  { key: 'welfare_grace_days', label: '到期保留天数', hint: '默认 7' },
  { key: 'welfare_inactive_days', label: '未活跃禁用天数', hint: '默认 30' },
  { key: 'welfare_request_monthly', label: '公益求片/月', hint: '默认 3' },
  { key: 'lottery_cost', label: '抽奖消耗积分', hint: '默认 10' },
]

async function load() {
  loading.value = true
  try {
    form.value = await fetchWelfareConfig()
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    await saveWelfareConfig(form.value)
    ElMessage.success('已保存')
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page">
    <div class="page-head">
      <h2>积分与公益配置</h2>
      <div class="head-actions">
        <el-button :icon="RefreshCw" @click="load">刷新</el-button>
        <el-button type="primary" :icon="Save" :loading="saving" @click="save">保存</el-button>
      </div>
    </div>

    <el-card v-loading="loading">
      <el-form label-width="160px">
        <el-form-item v-for="f in fields" :key="f.key" :label="f.label">
          <el-input v-model="form[f.key]" style="width: 200px" />
          <span style="margin-left: 8px; color: #909399">{{ f.hint }}</span>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<style scoped>
.page-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.page-head h2 { margin: 0; font-size: 18px; }
.head-actions { display: flex; gap: 8px; align-items: center; }
</style>
