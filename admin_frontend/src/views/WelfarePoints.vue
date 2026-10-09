<script setup lang="ts">
/**
 * 公益服·积分与公益配置：SystemConfig 表单
 *
 * v2.55（暗房影院统一）：PageHeader + 分组 SectionCard，
 * 逻辑与 PR #432 一致，仅模板迁移到共享组件。
 *
 * 注意：签到积分三项（min/max/streak_bonus）与系统设置「每日签到」
 * （checkin_base_points 等）是两套并存配置，待用户确认合并方案，
 * 本次只做布局统一，不动配置键。
 */
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { CalendarCheck, Coins, RefreshCw, Save, Settings2 } from 'lucide-vue-next'
import { PageHeader, SectionCard } from '@/components/ui'
import { fetchWelfareConfig, saveWelfareConfig } from '@/api/welfare'

const loading = ref(false)
const saving = ref(false)
const form = ref<Record<string, string>>({})

const signinFields = [
  { key: 'points_signin_min', label: '签到最低分', hint: '每天随机下限，默认 1', suffix: '积分/天' },
  { key: 'points_signin_max', label: '签到最高分', hint: '每天随机上限，默认 3', suffix: '积分/天' },
  { key: 'points_signin_streak_bonus', label: '连签奖励', hint: '连续 7 天额外奖励，默认 2', suffix: '积分' },
]

const earnRedeemFields = [
  { key: 'points_chat_daily_cap', label: '发言每日上限', hint: '默认 20', suffix: '积分/天' },
  { key: 'points_redeem_7d', label: '兑换 7 天', hint: '默认 100', suffix: '积分' },
  { key: 'points_redeem_30d', label: '兑换 30 天', hint: '默认 300', suffix: '积分' },
]

const welfareFields = [
  { key: 'welfare_grace_days', label: '到期保留天数', hint: '到期后可登录但不可播放，默认 7', suffix: '天' },
  { key: 'welfare_inactive_days', label: '未活跃禁用天数', hint: '默认 30', suffix: '天' },
  { key: 'welfare_request_monthly', label: '公益求片额度', hint: '默认 3', suffix: '次/月' },
  { key: 'lottery_cost', label: '抽奖消耗积分', hint: '默认 10', suffix: '积分/次' },
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
  <div>
    <PageHeader
      eyebrow="公益服"
      title="积分与公益配置"
      description="签到积分规则、兑换比例与公益服到期策略"
    >
      <template #actions>
        <el-button :icon="RefreshCw" @click="load">刷新</el-button>
        <el-button type="primary" :icon="Save" :loading="saving" @click="save">保存</el-button>
      </template>
    </PageHeader>

    <div v-loading="loading" class="form-grid">
      <SectionCard
        title="签到积分"
        :icon="CalendarCheck"
        description="每日签到随机区间与连续签到奖励"
      >
        <el-form label-width="120px" class="config-form">
          <el-form-item v-for="f in signinFields" :key="f.key" :label="f.label">
            <el-input v-model="form[f.key]" style="width: 160px" />
            <span class="field-suffix">{{ f.suffix }}</span>
            <span class="field-hint">{{ f.hint }}</span>
          </el-form-item>
        </el-form>
      </SectionCard>

      <SectionCard
        title="获取与兑换"
        :icon="Coins"
        description="发言积分上限与积分兑换公益天数"
      >
        <el-form label-width="120px" class="config-form">
          <el-form-item v-for="f in earnRedeemFields" :key="f.key" :label="f.label">
            <el-input v-model="form[f.key]" style="width: 160px" />
            <span class="field-suffix">{{ f.suffix }}</span>
            <span class="field-hint">{{ f.hint }}</span>
          </el-form-item>
        </el-form>
      </SectionCard>

      <SectionCard
        title="公益服规则"
        :icon="Settings2"
        description="到期保留、未活跃禁用、求片额度与抽奖消耗"
      >
        <el-form label-width="120px" class="config-form">
          <el-form-item v-for="f in welfareFields" :key="f.key" :label="f.label">
            <el-input v-model="form[f.key]" style="width: 160px" />
            <span class="field-suffix">{{ f.suffix }}</span>
            <span class="field-hint">{{ f.hint }}</span>
          </el-form-item>
        </el-form>
      </SectionCard>
    </div>
  </div>
</template>

<style scoped>
.form-grid {
  display: grid;
  gap: 16px;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
}
.config-form :deep(.el-form-item) {
  margin-bottom: 14px;
}
.config-form :deep(.el-form-item:last-child) {
  margin-bottom: 0;
}
.field-suffix {
  margin-left: 8px;
  color: var(--au-text-2);
  white-space: nowrap;
}
.field-hint {
  margin-left: 8px;
  color: var(--au-text-2);
  font-size: 12px;
}
</style>
