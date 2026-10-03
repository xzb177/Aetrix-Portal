<script setup lang="ts">
/**
 * 访问拦截：UA 关键词 + IP 归属地
 *
 * 这一页管的是「谁能访问本站」，所以它的默认状态是**什么都不做**——
 * 两个开关默认关闭，不配置时中间件只做一次时间比较就透传，零开销。
 * 页面顺序按管理员实际的踩坑顺序排：
 *
 * 1. **先看清现在开着没有**（顶部状态条）。开着就明说开着，因为它的表现是
 *    「用户打不开站」，而用户只会来问管理员，不会来看这一页。
 * 2. **UA 规则**：黑名单屏蔽爬虫 / 特定客户端，白名单反过来「只放行这几个」。
 *    白名单优先于黑名单——同时配了两边且命中白名单时，按放行走。
 * 3. **IP 归属地规则**：屏蔽名单内，或只允许名单内（"只允许国内访问" 是后者）。
 * 4. **试一下**：填一个 IP + UA，用当前规则跑一遍但不拦截任何东西。
 *    开「只允许国内」之前务必拿自己的出口 IP 试一次——规则写歪了会把自己
 *    也关在门外，而这一页正是被关在门外之后唯一还能打开的地方。
 *
 * 判定逻辑在后端 `backend/access_guard.py`，本页只做配置与展示。
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { FlaskConical, Globe2, Info, RefreshCw, Save, ShieldOff, Undo2 } from 'lucide-vue-next'
import {
  fetchAccessGuard,
  previewAccessGuard,
  saveAccessGuardPolicy,
  type AccessGuardPolicy,
  type AccessGuardPreview,
  type AccessGuardRegionMode,
} from '@/api/admin'
import { useAuthStore } from '@/stores/auth'

/**
 * 能不能写。
 *
 * 访问拦截是**全站**开关：UA 白名单一旦写歪（漏了某个客户端、或忘了管理员自己
 * 的浏览器），整站对外关闭，而它本身就是「把自己锁在门外」的保险——只能回这一页
 * 改配置才能解开。所以只有超管能写，与防共享同级。
 *
 * ⚠️ 这层置灰只是**提示**，真正的拦截在后端 ``admin_roles.SUPER_ONLY_PREFIXES``：
 * 绕开界面直接打接口，运营角色也会拿到 403。
 */
const auth = useAuthStore()
const canWrite = computed(() => auth.admin?.is_super !== false)
const WRITE_HINT = '访问拦截是全站开关（UA 黑白名单 / 地区封禁），需要超级管理员才能修改'

const data = ref<AccessGuardPolicy | null>(null)
const loading = ref(false)
const saving = ref(false)
const testing = ref(false)

/** 本地草稿：改完点「保存」才写后端 */
const draft = ref<AccessGuardPolicy | null>(null)

/**
 * 关键词在输入框里用逗号/换行连着写，后端存的是解析后的数组。
 * 回填时拼回一行文本，展示的就是管理员当初填的样子。
 */
function toText(list: string[]): string {
  return (list || []).join(', ')
}

const uaAllowText = ref('')
const uaDenyText = ref('')
const countryText = ref('')
const keywordText = ref('')

const dirty = computed(() => {
  const cur = data.value
  if (!cur) return false
  return (
    cur.ua_enabled !== draft.value?.ua_enabled ||
    cur.ua_deny.join(',') !== uaDenyText.value.replace(/[,，;；\s]+/g, ',').replace(/,$/, '') ||
    cur.ua_allow.join(',') !== uaAllowText.value.replace(/[,，;；\s]+/g, ',').replace(/,$/, '') ||
    cur.region_enabled !== draft.value?.region_enabled ||
    cur.region_mode !== draft.value?.region_mode ||
    cur.region_countries.join(',') !== countryText.value.replace(/[,，;；\s]+/g, ',').replace(/,$/, '') ||
    cur.region_keywords.join(',') !== keywordText.value.replace(/[,，;；\s]+/g, ',').replace(/,$/, '')
  )
})

const MODE_OPTIONS: { value: AccessGuardRegionMode; label: string; hint: string }[] = [
  { value: 'block', label: '屏蔽名单内的地区', hint: '命中即拦，其余放行（黑名单思路）' },
  { value: 'allow', label: '只允许名单内的地区', hint: '「只允许国内访问」用这一档；查不到归属地一律放行' },
]

/** 开关开着但一个关键词都没填 = 配置没填完，后端按「不生效」处理，这里提前说清 */
const uaIncomplete = computed(() =>
  Boolean(draft.value?.ua_enabled) && !uaDenyText.value.trim() && !uaAllowText.value.trim(),
)
const regionIncomplete = computed(() =>
  Boolean(draft.value?.region_enabled) && !countryText.value.trim() && !keywordText.value.trim(),
)
/** 开了地区规则但没配地理能力：永远查不到归属地，等于白开 */
const regionButNoGeo = computed(() =>
  Boolean(draft.value?.region_enabled) && data.value?.geo_ready === false,
)

async function load() {
  loading.value = true
  try {
    const res = await fetchAccessGuard()
    data.value = res.policy
    draft.value = { ...res.policy }
    uaAllowText.value = toText(res.policy.ua_allow)
    uaDenyText.value = toText(res.policy.ua_deny)
    countryText.value = toText(res.policy.region_countries)
    keywordText.value = toText(res.policy.region_keywords)
  } finally {
    loading.value = false
  }
}

onMounted(load)

/** 输入框 → 后端要的逗号分隔串（分隔符统一成英文逗号，其余原样交给后端解析） */
function norm(text: string): string {
  return text.replace(/[,，;；\n\r\t]+/g, ',').replace(/^,|,$/g, '')
}

async function save() {
  const d = draft.value
  if (!d) return
  saving.value = true
  try {
    const res = await saveAccessGuardPolicy({
      ua_enabled: d.ua_enabled,
      ua_allow: norm(uaAllowText.value),
      ua_deny: norm(uaDenyText.value),
      region_enabled: d.region_enabled,
      region_mode: d.region_mode,
      region_countries: norm(countryText.value),
      region_keywords: norm(keywordText.value),
    })
    data.value = res.policy
    // 以后端返回的**真实生效值**回填，不自己猜
    draft.value = { ...res.policy }
    uaAllowText.value = toText(res.policy.ua_allow)
    uaDenyText.value = toText(res.policy.ua_deny)
    countryText.value = toText(res.policy.region_countries)
    keywordText.value = toText(res.policy.region_keywords)
    ElMessage.success(res.policy.active ? '访问拦截配置已保存并立即生效' : '配置已保存（当前不生效）')
  } catch {
    /* 拦截器已提示 */
  } finally {
    saving.value = false
  }
}

function revert() {
  const cur = data.value
  if (!cur) return
  draft.value = { ...cur }
  uaAllowText.value = toText(cur.ua_allow)
  uaDenyText.value = toText(cur.ua_deny)
  countryText.value = toText(cur.region_countries)
  keywordText.value = toText(cur.region_keywords)
}

// ==================== 试跑 ====================

const testIp = ref('')
const testUa = ref('')
const testResult = ref<AccessGuardPreview | null>(null)

async function runTest() {
  testing.value = true
  testResult.value = null
  try {
    const res = await previewAccessGuard({
      ip: testIp.value.trim(),
      user_agent: testUa.value.trim(),
    })
    testResult.value = res.result
  } catch {
    /* 拦截器已提示 */
  } finally {
    testing.value = false
  }
}

/** 试跑结论一句话说清（含「不生效」与「查不到归属地」这两种最容易被误读的放行） */
const testSummary = computed(() => {
  const r = testResult.value
  if (!r) return ''
  if (!r.active) return '当前规则没有生效，什么都不会被拦'
  if (!r.resolved && r.country === '' && r.region === '') {
    return r.blocked
      ? '已按 UA 规则拦下（归属地未参与判定）'
      : '放行：归属地查不到，按「不知道在哪」处理'
  }
  if (r.blocked) return `拦下：${r.message}${r.matched ? `（命中「${r.matched}」）` : ''}`
  return '放行：未被任何规则命中'
})
</script>

<template>
  <div class="admin-page">
    <div class="admin-page-header">
      <div>
        <h1 class="admin-page-title">访问拦截</h1>
        <p class="admin-page-desc">
          按 UA 关键词与 IP 归属地拦截访问。全部规则默认关闭，关闭时对正常请求零开销。
        </p>
      </div>
      <div class="toolbar">
        <el-button :loading="loading" @click="load">
          <RefreshCw :size="14" style="margin-right: 4px" />刷新
        </el-button>
      </div>
    </div>

    <!-- 现在的状态：开着的时候必须一眼看见 -->
    <div v-if="data" class="stat-grid">
      <div class="stat-tile" :class="{ 'is-danger': data.active }">
        <div class="stat-label"><ShieldOff :size="13" /> 当前状态</div>
        <div class="stat-value">{{ data.active ? '拦截生效中' : '未启用' }}</div>
        <div class="stat-hint">
          {{ data.active ? '命中的请求会收到 403 与提示页' : '所有请求原样放行' }}
        </div>
      </div>
      <div class="stat-tile" :class="{ 'is-warn': data.ua_enabled }">
        <div class="stat-label">UA 规则</div>
        <div class="stat-value">{{ data.ua_enabled ? '开启' : '关闭' }}</div>
        <div class="stat-hint">
          黑名单 {{ data.ua_deny.length }} 项 · 白名单 {{ data.ua_allow.length }} 项
        </div>
      </div>
      <div class="stat-tile" :class="{ 'is-warn': data.region_enabled }">
        <div class="stat-label"><Globe2 :size="13" /> 归属地规则</div>
        <div class="stat-value">{{ data.region_enabled ? '开启' : '关闭' }}</div>
        <div class="stat-hint">{{ data.mode_labels[data.region_mode] || data.region_mode }}</div>
      </div>
      <div class="stat-tile" :class="{ 'is-warn': !data.geo_ready }">
        <div class="stat-label"><FlaskConical :size="13" /> 地理能力</div>
        <div class="stat-value">{{ data.geo_ready ? '已配置' : '未配置' }}</div>
        <div class="stat-hint">{{ data.geo_ready ? '可以解析归属地' : '归属地规则不会生效' }}</div>
      </div>
    </div>

    <el-alert
      v-if="data && !data.geo_ready"
      class="ag-alert"
      type="warning"
      show-icon
      :closable="false"
      title="未配置「IP 与地理位置」能力"
      description="归属地规则需要它才能查到来访者所在地区。没配置时地区规则一律不生效，且系统按「查不到就放行」处理，不会误伤任何人。可到「能力中心 → IP 与地理位置」配置。"
    />

    <section v-if="draft" class="admin-card">
      <header class="card-header">
        <h2>规则</h2>
        <span v-if="dirty" class="fact warn">有未保存的改动</span>
      </header>

      <el-alert
        v-if="!canWrite"
        type="warning"
        :closable="false"
        show-icon
        class="ag-alert"
      >
        {{ WRITE_HINT }}。下面的保存按钮已置灰，但内容仍然可读。
      </el-alert>

      <el-form label-position="top">
        <!-- UA -->
        <div class="ag-block">
          <div class="ag-block-head">
            <h3>UA 关键词</h3>
            <el-switch v-model="draft.ua_enabled" active-text="启用" inactive-text="关闭" />
          </div>
          <p class="ag-hint">
            按 <code>User-Agent</code> 做<strong>子串</strong>匹配（大小写不敏感）。
            白名单非空时表示「只放行命中的」，且<strong>优先于黑名单</strong>。
            关键词用逗号或换行分隔。
            <br />
            <strong>白名单有风险：</strong>白名单没包含你自己浏览器的 UA 时，你会被关在门外。
            同一台服务器 / 同一局域网的访问始终放行，可以从那里改回来。
          </p>
          <el-form-item label="黑名单（命中即拦，如 Googlebot、SemrushBot）">
            <el-input
              v-model="uaDenyText"
              type="textarea"
              :rows="2"
              placeholder="Googlebot, SemrushBot, AhrefsBot"
            />
          </el-form-item>
          <el-form-item label="白名单（非空时只放行命中的，如 Emby、Infuse）">
            <el-input
              v-model="uaAllowText"
              type="textarea"
              :rows="2"
              placeholder="Emby, Infuse, FongMi"
            />
          </el-form-item>
          <p v-if="uaIncomplete" class="ag-note is-warn">
            开关已打开但两个列表都是空的——这样不会拦任何人，请先填关键词。
          </p>
        </div>

        <!-- 归属地 -->
        <div class="ag-block">
          <div class="ag-block-head">
            <h3><Globe2 :size="15" style="margin-right: 6px" />IP 归属地</h3>
            <el-switch v-model="draft.region_enabled" active-text="启用" inactive-text="关闭" />
          </div>
          <p class="ag-hint">
            归属地来自「IP 与地理位置」能力。<strong>查不到就放行</strong>——
            查不到意味着「不知道在哪」，不是「在名单外」，尤其在「只允许」这一档下
            把「未知」当成「境外」会让地理库一挂全站对外全灭。
          </p>
          <el-form-item label="判定方向">
            <el-radio-group v-model="draft.region_mode">
              <el-radio-button
                v-for="opt in MODE_OPTIONS"
                :key="opt.value"
                :value="opt.value"
              >{{ opt.label }}</el-radio-button>
            </el-radio-group>
            <span class="ag-hint">
              {{ MODE_OPTIONS.find((o) => o.value === draft!.region_mode)?.hint }}
            </span>
          </el-form-item>
          <el-form-item label="国家 / 地区（只与国家名比对，如「中国」）">
            <el-input v-model="countryText" placeholder="中国" />
          </el-form-item>
          <el-form-item label="省 / 市（与地区串比对，如「香港」「新加坡」）">
            <el-input v-model="keywordText" placeholder="香港, 台湾, 新加坡" />
          </el-form-item>
          <p v-if="regionIncomplete" class="ag-note is-warn">
            开关已打开但两个列表都是空的——这样不会拦任何人，请先填关键词。
          </p>
          <p v-else-if="regionButNoGeo" class="ag-note is-warn">
            还没配置地理能力，这一档当前查不到任何归属地，等于没开。
          </p>
        </div>

        <div class="ag-actions">
          <el-button type="primary" :loading="saving" :disabled="!canWrite || !dirty" @click="save">
            <Save :size="14" style="margin-right: 4px" />保存
          </el-button>
          <el-button :disabled="!dirty" @click="revert">
            <Undo2 :size="14" style="margin-right: 4px" />还原
          </el-button>
          <span class="ag-hint">
            生效范围是全站（含 Emby 客户端），但不拦内网 / 本机来源。保存后同进程立即生效，其他进程最多 5 秒。
          </span>
        </div>
      </el-form>
    </section>

    <!-- 试跑 -->
    <section class="admin-card">
      <header class="card-header">
        <h2>试一下</h2>
        <span class="ag-hint" style="margin: 0">
          用当前规则跑一个样本，<strong>不会拦截任何真实请求</strong>
        </span>
      </header>

      <div class="ag-test">
        <el-input v-model="testIp" placeholder="来访者 IP，如 1.1.1.1" class="ag-test-ip" />
        <el-input
          v-model="testUa"
          placeholder="User-Agent，如 Mozilla/5.0 Chrome/120"
          class="ag-test-ua"
        />
        <el-button type="primary" :loading="testing" @click="runTest">
          <FlaskConical :size="14" style="margin-right: 4px" />试跑
        </el-button>
      </div>

      <div v-if="testResult" class="ag-result" :class="{ 'is-blocked': testResult.blocked }">
        <div class="ag-result-head">
          <strong>{{ testSummary }}</strong>
          <el-tag :type="testResult.blocked ? 'danger' : 'success'" size="small">
            {{ testResult.blocked ? '拦下' : '放行' }}
          </el-tag>
        </div>
        <dl class="ag-result-list">
          <dt>归属地</dt>
          <dd>
            <template v-if="testResult.resolved || testResult.country || testResult.region">
              {{ [testResult.country, testResult.region].filter(Boolean).join(' ') || '—' }}
            </template>
            <template v-else>查不到（按「不知道在哪」处理，放行）</template>
          </dd>
          <dt>命中</dt>
          <dd>{{ testResult.matched || '—' }}</dd>
          <dt>UA</dt>
          <dd class="ag-mono">{{ testResult.user_agent || '（空）' }}</dd>
        </dl>
      </div>

      <p class="ag-hint ag-test-tip">
        <Info :size="12" style="margin-right: 4px; vertical-align: -1px" />
        开「只允许国内访问」前，先把自己的出口 IP 填进来试一次。
      </p>
    </section>
  </div>
</template>

<style scoped>
.ag-alert { margin: 0 0 12px; }
.ag-block {
  padding-bottom: 16px;
  margin-bottom: 16px;
  border-bottom: 1px solid var(--border-subtle);
}
.ag-block:last-of-type { border-bottom: none; margin-bottom: 0; padding-bottom: 0; }
.ag-block-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 4px;
}
.ag-block-head h3 {
  display: flex;
  align-items: center;
  margin: 0;
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
}
.ag-hint {
  display: block;
  margin: 0 0 8px;
  font-size: var(--font-size-xs);
  color: var(--text-secondary);
  line-height: 1.8;
}
.ag-note {
  margin: 4px 0 0;
  font-size: var(--font-size-xs);
  line-height: 1.7;
}
.ag-note.is-warn { color: var(--warning); }
.ag-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  padding-top: 12px;
  border-top: 1px solid var(--border-subtle);
}
.ag-actions .ag-hint { margin: 0; }
.ag-test {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.ag-test-ip { flex: 1 1 180px; min-width: 0; }
.ag-test-ua { flex: 2 1 260px; min-width: 0; }
.ag-result {
  margin-top: 12px;
  padding: 12px 14px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  background: var(--bg-inset);
}
.ag-result.is-blocked { border-color: var(--danger-border); }
.ag-result-head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 8px;
  font-size: var(--font-size-sm);
  color: var(--text-primary);
}
.ag-result-list {
  display: grid;
  grid-template-columns: 72px 1fr;
  gap: 4px 10px;
  margin: 0;
  font-size: var(--font-size-xs);
}
/* dt 用 secondary 而不是 muted：muted 在浅色主题的 --bg-inset 上只有 3.18:1，
   而这里写的是「归属地 / 命中 / UA」这些必须看懂的关键字 */
.ag-result-list dt { color: var(--text-secondary); }
.ag-result-list dd { margin: 0; color: var(--text-secondary); word-break: break-all; }
.ag-mono { font-family: var(--font-mono); }
.ag-test-tip { margin: 10px 0 0; }

.fact.warn { color: var(--warning); font-size: var(--font-size-xs); }
.stat-tile.is-warn { border-color: var(--warning-border); }
.stat-tile.is-danger { border-color: var(--danger-border); }

/* 手机：试跑输入框竖排，按钮独占一行 */
@media (max-width: 767px) {
  .ag-test-ip,
  .ag-test-ua { flex: 1 1 100%; }
  .ag-actions .el-button { flex: 1 1 auto; }
  .ag-actions .ag-hint { flex: 1 1 100%; }
  .ag-block-head { flex-wrap: wrap; }
}
</style>