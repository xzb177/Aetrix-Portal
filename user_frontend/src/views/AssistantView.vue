<script setup lang="ts">
/**
 * AI 助手（能力：AI 模型设置）
 *
 * 管理员在后台「系统设置 → AI 模型设置」里填好端点 / 模型 / 密钥后这里才出现内容；
 * 没配好时不做「假可用」：直接说明属于哪种情况（未配置 / 已关闭 / 今日额度用完），
 * 用户不用去猜为什么点了没反应。
 *
 * 对话上下文只保留最近 8 轮（后端会再次裁剪，并丢弃客户端伪造的 system 轮次）。
 */
import { computed, nextTick, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { Bot, RefreshCw, Send, Sparkles, User as UserIcon } from 'lucide-vue-next'
import { aiApi, type AiStatus } from '@/api'
import { useToast } from '@/composables/useToast'

interface Bubble {
  role: 'user' | 'assistant' | 'error'
  content: string
  model?: string
}

const toast = useToast()

const loading = ref(true)
const status = ref<AiStatus | null>(null)
const question = ref('')
const sending = ref(false)
const bubbles = ref<Bubble[]>([])
const scroller = ref<HTMLElement | null>(null)

const available = computed(() => status.value?.enabled === true)
const quotaText = computed(() => {
  const s = status.value
  if (!s?.enabled) return ''
  if (!s.daily_limit || s.remaining === null) return '不限提问次数'
  return `今日剩余 ${s.remaining} / ${s.daily_limit} 次`
})
const exhausted = computed(() => available.value && status.value?.remaining === 0)

const SUGGESTIONS = [
  '这个站怎么在电视上看？',
  '会员有什么用？',
  '求片多久会处理？',
]

async function load() {
  loading.value = true
  try {
    status.value = await aiApi.status()
  } catch {
    status.value = null
  } finally {
    loading.value = false
  }
}

onMounted(load)

async function scrollToEnd() {
  await nextTick()
  scroller.value?.scrollTo({ top: scroller.value.scrollHeight, behavior: 'smooth' })
}

async function ask(text?: string) {
  const content = (text ?? question.value).trim()
  if (!content || sending.value) return
  question.value = ''
  bubbles.value.push({ role: 'user', content })
  sending.value = true
  scrollToEnd()
  try {
    // 只把 user / assistant 轮次交给后端（它也会再过滤一次）
    const history = bubbles.value
      .filter((b) => b.role !== 'error')
      .map((b) => ({ role: b.role as 'user' | 'assistant', content: b.content }))
      .slice(-8)
    const res = await aiApi.ask(content, history)
    bubbles.value.push({ role: 'assistant', content: res.answer, model: res.model })
    status.value = { ...(status.value as AiStatus), ...res }
  } catch (err) {
    const detail = (err as { response?: { data?: { detail?: string } }; message?: string })
    bubbles.value.push({
      role: 'error',
      content: detail?.response?.data?.detail || detail?.message || '提问失败，请稍后再试',
    })
    // 配额用尽 / 被关闭时刷新一次状态，界面提示随之更新
    load()
  } finally {
    sending.value = false
    scrollToEnd()
  }
}
</script>

<template>
  <div class="assistant-view">
    <div class="au-page">
      <header class="page-head au-anim-up">
        <div>
          <h1 class="page-title"><Bot :size="20" />AI 助手</h1>
          <p class="page-sub">
            <template v-if="available">由本站配置的模型提供回答 · {{ quotaText }}</template>
            <template v-else>帮你解答使用上的问题</template>
          </p>
        </div>
        <button class="au-btn au-btn-ghost au-btn-sm" :disabled="loading" @click="load">
          <RefreshCw :size="14" />刷新
        </button>
      </header>

      <!-- 未配置 / 不可用：说清楚是哪种情况 -->
      <section v-if="!loading && !available" class="au-card au-card-pad empty-card au-anim-up">
        <Sparkles :size="22" />
        <h2>AI 助手暂未开放</h2>
        <p>{{ status?.reason || '管理员尚未开启 AI 助手。' }}</p>
        <p class="empty-tip">
          需要即时帮助？可以到
          <RouterLink to="/tickets">工单支持</RouterLink>
          找人，或看看
          <RouterLink to="/messages?tab=announcement">站内公告</RouterLink>。
        </p>
      </section>

      <template v-else-if="available">
        <section ref="scroller" class="au-card chat au-anim-up">
          <div v-if="!bubbles.length" class="chat-empty">
            <Sparkles :size="18" />
            <p>可以这样问：</p>
            <div class="chips">
              <button
                v-for="s in SUGGESTIONS"
                :key="s"
                class="chip"
                type="button"
                @click="ask(s)"
              >{{ s }}</button>
            </div>
          </div>

          <div v-for="(b, i) in bubbles" :key="i" class="bubble-row" :class="b.role">
            <span class="avatar">
              <UserIcon v-if="b.role === 'user'" :size="14" />
              <Bot v-else :size="14" />
            </span>
            <div class="bubble">
              <p>{{ b.content }}</p>
              <span v-if="b.model" class="model-tag">{{ b.model }}</span>
            </div>
          </div>
        </section>

        <div class="composer au-anim-up">
          <input
            v-model="question"
            class="au-input"
            type="text"
            :disabled="sending || exhausted"
            :placeholder="exhausted ? '今日提问次数已用完，明天再来' : '输入你的问题…'"
            @keyup.enter="ask()"
          />
          <button
            class="au-btn au-btn-primary"
            :disabled="sending || exhausted || !question.trim()"
            @click="ask()"
          >
            <Send :size="14" />{{ sending ? '思考中…' : '发送' }}
          </button>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.empty-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: flex-start;
  color: var(--text-muted);
}

.empty-card h2 { font-size: 16px; color: var(--text-primary); margin: 0; }
.empty-card p { margin: 0; font-size: 13px; line-height: 1.7; }
.empty-card a { color: var(--au-primary); text-decoration: none; }
.empty-tip { color: var(--text-muted); }

.chat {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-height: 220px;
  max-height: 58vh;
  overflow-y: auto;
}

.chat-empty { display: flex; flex-direction: column; gap: 10px; color: var(--text-muted); }
.chat-empty p { margin: 0; font-size: 13px; }

.chips { display: flex; flex-wrap: wrap; gap: 8px; }

.chip {
  border: 1px solid var(--au-border);
  background: var(--au-surface);
  color: var(--text-primary);
  border-radius: var(--au-r-full);
  padding: 6px 12px;
  font-size: 12px;
  cursor: pointer;
  transition: border-color var(--au-fast) var(--au-ease), background var(--au-fast) var(--au-ease);
}

.chip:hover { border-color: var(--au-primary-border); background: var(--au-primary-soft); }

.bubble-row { display: flex; gap: 10px; align-items: flex-start; }
.bubble-row.user { flex-direction: row-reverse; }

.avatar {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  flex-shrink: 0;
  border-radius: var(--au-r-full);
  background: var(--au-primary-soft);
  color: var(--au-primary);
}

.bubble-row.user .avatar { background: var(--au-surface-3); color: var(--text-primary); }

.bubble {
  max-width: 76%;
  padding: 10px 13px;
  border-radius: var(--au-r-md);
  background: var(--au-surface);
  border: 1px solid var(--au-border);
}

.bubble-row.user .bubble { background: var(--au-primary-soft); border-color: var(--au-primary-border); }
.bubble-row.error .bubble { background: var(--au-danger-soft); border-color: var(--au-danger-border); }

.bubble p { margin: 0; font-size: 13.5px; line-height: 1.7; white-space: pre-wrap; color: var(--text-primary); }

.model-tag {
  display: inline-block;
  margin-top: 6px;
  font-size: 11px;
  color: var(--text-muted);
}

.composer { display: flex; gap: 10px; }

@media (max-width: 640px) {
  .bubble { max-width: 84%; }
  .composer { flex-direction: column; }
  .composer .au-btn { width: 100%; }
}
</style>
