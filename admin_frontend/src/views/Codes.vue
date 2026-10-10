<script setup lang="ts">
/**
 * 统一码管理（M1）
 *
 * 两页并一页：卡码（注册/续期/白名单/积分/折扣）+ 兑换码（旧系统，逐步迁移）
 * 通过标签页切换，统一入口管理所有码。
 */
import { ref } from 'vue'
import RegistrationCodes from './RegistrationCodes.vue'
import ExchangeCodes from './ExchangeCodes.vue'

const activeTab = ref<'reg' | 'exchange'>('reg')
</script>

<template>
  <div class="codes-page">
    <div class="tab-bar">
      <button
        type="button"
        class="tab-btn"
        :class="{ active: activeTab === 'reg' }"
        @click="activeTab = 'reg'"
      >
        卡码
        <span class="tab-hint">注册 / 续期 / 积分 / 折扣</span>
      </button>
      <button
        type="button"
        class="tab-btn"
        :class="{ active: activeTab === 'exchange' }"
        @click="activeTab = 'exchange'"
      >
        兑换码
        <span class="tab-hint">旧系统 · 逐步迁移</span>
      </button>
    </div>

    <div class="tab-panel">
      <RegistrationCodes v-if="activeTab === 'reg'" />
      <ExchangeCodes v-else />
    </div>
  </div>
</template>

<style scoped>
.codes-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 16px;
  max-width: 1400px;
  margin: 0 auto;
}
.tab-bar {
  display: flex;
  gap: 8px;
  border-bottom: 1px solid var(--au-border, #2a2a2a);
  padding-bottom: 0;
}
.tab-btn {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  padding: 10px 18px;
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  color: var(--au-text-2, #888);
  font-size: 15px;
  font-weight: 500;
  cursor: pointer;
  margin-bottom: -1px;
}
.tab-btn.active {
  color: var(--au-primary, #e8a84a);
  border-bottom-color: var(--au-primary, #e8a84a);
}
.tab-hint {
  font-size: 12px;
  color: var(--au-text-3, #666);
  font-weight: normal;
}
.tab-btn.active .tab-hint {
  color: var(--au-primary, #e8a84a);
  opacity: 0.8;
}
.tab-panel {
  min-height: 400px;
}
</style>
