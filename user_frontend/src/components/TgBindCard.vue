<template>
  <div v-if="compact" class="tg-bind-compact">
    <Send :size="16" class="tg-bind-icon" />
    <span class="tg-bind-title">绑定 Telegram，解锁公益服功能</span>
    <button class="au-btn au-btn-primary" @click="goBind">去绑定</button>
  </div>
  <div v-else class="au-card au-card-pad tg-bind">
    <div class="tg-bind-head">
      <div class="tg-bind-icon-wrap">
        <Send :size="22" />
      </div>
      <span class="au-badge">公益服</span>
    </div>
    <h3 class="tg-bind-title">绑定 Telegram，解锁公益服功能</h3>
    <p class="tg-bind-desc">公益服功能（签到、积分、红包、抽奖）需要绑定 Telegram，防小号，1 分钟搞定</p>
    <button class="au-btn au-btn-primary" @click="goBind">去绑定</button>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'
import { Send } from 'lucide-vue-next'

withDefaults(defineProps<{ compact?: boolean }>(), { compact: false })

const router = useRouter()

function goBind() {
  router.push('/profile')
}
</script>

<style scoped>
.tg-bind {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 12px;
}
.tg-bind-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
}
.tg-bind-icon-wrap {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: 10px;
  background: var(--au-surface-2);
  color: var(--au-text);
}
.tg-bind-title {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: var(--au-text);
}
.tg-bind-desc {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
  color: var(--au-text-2);
}
.tg-bind .au-btn {
  margin-top: 4px;
}
.tg-bind-compact {
  display: flex;
  align-items: center;
  gap: 8px;
}
.tg-bind-compact .tg-bind-icon {
  color: var(--au-text-2);
}
.tg-bind-compact .tg-bind-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--au-text-2);
}
</style>
