<script setup lang="ts">
/**
 * 统一码管理（M1）
 *
 * 两页并一页：卡码（注册/续期/白名单/积分/折扣）+ 兑换码（旧系统，逐步迁移）
 * 通过标签页切换，统一入口管理所有码。
 */
import { computed, defineAsyncComponent } from 'vue'
import { useRoute, useRouter } from 'vue-router'

// 两个标签页各自是一整页：按需加载，只看卡码时不用把兑换码页也打进首屏
const RegistrationCodes = defineAsyncComponent(() => import('./RegistrationCodes.vue'))
const ExchangeCodes = defineAsyncComponent(() => import('./ExchangeCodes.vue'))

type CodesTab = 'reg' | 'exchange'

const route = useRoute()
const router = useRouter()

/** 当前标签与 ?tab= 同步：旧地址 /exchange-codes、/registration-codes 跳过来能落到对应标签，刷新也不丢 */
const activeTab = computed<CodesTab>({
  get: () => (route.query.tab === 'exchange' ? 'exchange' : 'reg'),
  set: (tab) => {
    if (tab === activeTab.value) return
    router.replace({ query: { ...route.query, tab } })
  },
})
</script>

<template>
  <!-- 两个子页各自带 PageHeader（眉题「运营中心」），这里只放标签条，不再叠第二个页头 -->
  <div class="admin-page codes-page">
    <div class="tab-bar" role="tablist" aria-label="码类型">
      <button
        id="codes-tab-reg"
        type="button"
        role="tab"
        class="tab-btn"
        :class="{ active: activeTab === 'reg' }"
        :aria-selected="activeTab === 'reg'"
        aria-controls="codes-panel"
        @click="activeTab = 'reg'"
      >
        卡码
        <span class="tab-hint">注册 / 续期 / 积分 / 折扣</span>
      </button>
      <button
        id="codes-tab-exchange"
        type="button"
        role="tab"
        class="tab-btn"
        :class="{ active: activeTab === 'exchange' }"
        :aria-selected="activeTab === 'exchange'"
        aria-controls="codes-panel"
        @click="activeTab = 'exchange'"
      >
        兑换码
        <span class="tab-hint">旧系统 · 逐步迁移</span>
      </button>
    </div>

    <div
      id="codes-panel"
      class="tab-panel"
      role="tabpanel"
      :aria-labelledby="activeTab === 'reg' ? 'codes-tab-reg' : 'codes-tab-exchange'"
    >
      <!-- KeepAlive：来回切标签不重拉数据、不丢筛选 -->
      <KeepAlive>
        <RegistrationCodes v-if="activeTab === 'reg'" />
        <ExchangeCodes v-else />
      </KeepAlive>
    </div>
  </div>
</template>

<style scoped>
/* 外层间距交给 .admin-content（不再自带 padding / max-width，否则手机上左右各多出 16px） */
.tab-bar {
  display: flex;
  gap: 4px;
  border-bottom: 1px solid var(--au-border);
  overflow-x: auto;
  scrollbar-width: none;
}
.tab-btn {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  flex-shrink: 0;
  padding: 10px 18px;
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  color: var(--au-text-2);
  font: inherit;
  font-size: 15px;
  font-weight: 500;
  cursor: pointer;
  margin-bottom: -1px;
  transition: color var(--au-fast) var(--au-ease), border-color var(--au-fast) var(--au-ease);
}
.tab-btn:hover { color: var(--au-text); }
.tab-btn:focus-visible { outline: 2px solid var(--au-border-focus); outline-offset: -2px; }
.tab-btn.active {
  color: var(--au-primary);
  border-bottom-color: var(--au-primary);
}
.tab-hint {
  font-size: 12px;
  color: var(--au-text-3);
  font-weight: 400;
}
.tab-btn.active .tab-hint { color: var(--au-primary); }
.tab-panel { min-width: 0; }

@media (max-width: 640px) {
  .tab-btn { padding: 8px 12px; font-size: 14px; }
  .tab-hint { display: none; }
}
</style>
