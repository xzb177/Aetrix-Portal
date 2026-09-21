<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { CheckCircle2, CircleHelp, ExternalLink, Server, ShieldCheck, Wifi } from 'lucide-vue-next'
import { fetchEmbyConnections, saveEmbyConnection, testEmbyConnection, type EmbyConnections } from '@/api/admin'

const loading = ref(true)
const saving = ref<'managed_ea' | 'external' | null>(null)
const testing = ref<'managed_ea' | 'external' | null>(null)
const state = reactive<EmbyConnections>({
  managed_ea: { url: '', enabled: false },
  external: { url: '', enabled: false, has_api_key: false },
  active_mode: 'managed_ea',
})
const apiKey = ref('')
const result = reactive<Record<string, { ok: boolean; message?: string; server_name?: string }>>({})

async function load() {
  loading.value = true
  try { Object.assign(state, await fetchEmbyConnections()) } catch { ElMessage.error('读取 Emby 服务配置失败') } finally { loading.value = false }
}
async function test(mode: 'managed_ea' | 'external') {
  const item = state[mode]
  if (!item.url) return ElMessage.warning('请先填写服务地址')
  testing.value = mode
  try {
    const response = await testEmbyConnection({ mode, url: item.url, api_key: mode === 'external' ? apiKey.value || undefined : undefined })
    result[mode] = response
    response.ok ? ElMessage.success('连接成功') : ElMessage.warning(response.message || '连接失败')
  } catch { ElMessage.error('连接测试失败') } finally { testing.value = null }
}
async function save(mode: 'managed_ea' | 'external') {
  const item = state[mode]
  if (!item.url) return ElMessage.warning('请先填写服务地址')
  saving.value = mode
  try {
    const response = await saveEmbyConnection({ mode, url: item.url, enabled: item.enabled, api_key: mode === 'external' ? apiKey.value || undefined : undefined })
    result[mode] = response.probe
    if (response.probe.ok) state.active_mode = mode
    response.probe.ok ? ElMessage.success('已保存并连接成功') : ElMessage.warning('已保存，但当前服务连接失败；自建功能不会被启用')
    if (mode === 'external') apiKey.value = ''
  } catch { ElMessage.error('保存失败，请检查地址') } finally { saving.value = null }
}
onMounted(load)
</script>

<template>
  <div class="page" v-loading="loading">
    <div class="page-heading">
      <div><p class="eyebrow">EMBY SERVICE ROUTING</p><h2>Emby 服务入口</h2><p class="page-desc">这里决定门户和管理后台要连接哪一台 Emby 服务。两种模式只能选一台作为当前使用入口。</p></div>
    </div>
    <el-alert title="小白版说明" type="info" :closable="false" show-icon class="guide">
      <template #default>如果你部署了本项目自带的 Emby API（EA），选「分离部署后端服」；如果你已经有一台独立的正版 Emby/Jellyfin 兼容服务，选「已有 Emby 服」。未完成连接前，媒体库、播放和账号联动功能不会正常工作。</template>
    </el-alert>
    <div class="server-grid">
      <section class="server-card" :class="{ active: state.active_mode === 'managed_ea' }">
        <div class="card-top"><div class="icon managed"><Server :size="20" /></div><div><h3>分离部署后端服</h3><p>本项目自带的 EA · Emby API</p></div><el-tag v-if="state.active_mode === 'managed_ea'" type="success">当前使用</el-tag></div>
        <div class="explain"><ShieldCheck :size="16" />需要与面板共享数据库和 SECRET_KEY；EA 没部署时不能使用。</div>
        <el-form label-position="top"><el-form-item label="EA 服务地址"><el-input v-model="state.managed_ea.url" placeholder="例如 https://emby-api.example.com" /></el-form-item><el-form-item label="启用此服务"><el-switch v-model="state.managed_ea.enabled" /></el-form-item></el-form>
        <div v-if="result.managed_ea || (state.managed_ea.url && state.managed_ea.enabled)" class="probe" :class="result.managed_ea?.ok || state.managed_ea.reachable ? 'ok' : 'bad'"><CheckCircle2 :size="16" />{{ result.managed_ea?.ok || state.managed_ea.reachable ? `已连接：${result.managed_ea?.server_name || 'EA'}` : (result.managed_ea?.message || '尚未通过连接测试') }}</div>
        <div class="actions"><el-button @click="test('managed_ea')" :loading="testing === 'managed_ea'"><Wifi :size="15" />测试连接</el-button><el-button type="primary" @click="save('managed_ea')" :loading="saving === 'managed_ea'">保存并使用</el-button></div>
      </section>
      <section class="server-card" :class="{ active: state.active_mode === 'external' }">
        <div class="card-top"><div class="icon external"><ExternalLink :size="20" /></div><div><h3>已有 Emby 服</h3><p>接入你已经部署好的第三方 Emby</p></div><el-tag v-if="state.active_mode === 'external'" type="success">当前使用</el-tag></div>
        <div class="explain"><CircleHelp :size="16" />此模式只负责连接已有服务；本项目的会员、用户和媒体库策略不会自动写入第三方 Emby。</div>
        <el-form label-position="top"><el-form-item label="Emby 服务地址"><el-input v-model="state.external.url" placeholder="例如 https://my-emby.example.com" /></el-form-item><el-form-item label="API Key（可选）"><el-input v-model="apiKey" type="password" show-password :placeholder="state.external.has_api_key ? '已保存密钥，不填则继续使用' : '从 Emby 控制台生成'" /></el-form-item><el-form-item label="启用此服务"><el-switch v-model="state.external.enabled" /></el-form-item></el-form>
        <div v-if="result.external || (state.external.url && state.external.enabled)" class="probe" :class="result.external?.ok || state.external.reachable ? 'ok' : 'bad'"><CheckCircle2 :size="16" />{{ result.external?.ok || state.external.reachable ? `已连接：${result.external?.server_name || 'Emby'}` : (result.external?.message || '尚未通过连接测试') }}</div>
        <div class="actions"><el-button @click="test('external')" :loading="testing === 'external'"><Wifi :size="15" />测试连接</el-button><el-button type="primary" @click="save('external')" :loading="saving === 'external'">保存并使用</el-button></div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.page { max-width: 1180px; margin: 0 auto; }.page-heading { margin-bottom: 18px; }.eyebrow { color: var(--primary); font-size: 11px; letter-spacing: .14em; margin: 0 0 6px; }.page h2 { margin: 0; color: var(--text-primary); font-size: 24px; }.page-desc { color: var(--text-secondary); margin: 8px 0 0; line-height: 1.6; }.guide { margin-bottom: 18px; line-height: 1.6; }.server-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }.server-card { padding: 20px; border: 1px solid var(--border-default); border-radius: var(--radius-lg); background: var(--bg-surface); }.server-card.active { border-color: var(--primary); box-shadow: 0 0 0 1px var(--primary-bg); }.card-top { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }.card-top h3 { color: var(--text-primary); margin: 0 0 4px; font-size: 17px; }.card-top p { color: var(--text-muted); margin: 0; font-size: 13px; }.card-top .el-tag { margin-left: auto; }.icon { width: 42px; height: 42px; display: grid; place-items: center; border-radius: 12px; }.managed { background: var(--primary-bg); color: var(--primary); }.external { background: var(--success-bg); color: var(--success); }.explain { display: flex; gap: 8px; color: var(--text-secondary); background: var(--bg-elevated); border-radius: var(--radius-md); padding: 11px; font-size: 13px; line-height: 1.5; margin-bottom: 18px; }.explain svg { flex: 0 0 auto; color: var(--primary); margin-top: 2px; }.probe { display: flex; align-items: center; gap: 7px; padding: 9px 10px; border-radius: var(--radius-md); font-size: 13px; margin-bottom: 14px; }.probe.ok { color: var(--success); background: var(--success-bg); }.probe.bad { color: var(--danger); background: var(--danger-bg); }.actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 8px; }@media (max-width: 720px) { .server-grid { grid-template-columns: 1fr; }.server-card { padding: 15px; }.actions { flex-direction: column-reverse; }.actions .el-button { width: 100%; margin-left: 0; } }
</style>