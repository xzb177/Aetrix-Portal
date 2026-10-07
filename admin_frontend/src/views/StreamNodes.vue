<script setup lang="ts">
/**
 * 流节点（分离架构）—— 高宽带大盘机器独立出流，免脚本自助接入。
 *
 * 流程：点"添加节点" → 填名称/公网域名/权重 → 生成一次性 token（30 分钟有效）→
 * 复制 docker 命令到新机器执行 → 容器自动 join 注册 → token 即焚。
 * 全程不用 SSH、不用手动跑脚本。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { CheckCircle2, Copy, Plus, RefreshCw, Trash2, XCircle, Clock } from 'lucide-vue-next'
import {
  createJoinToken,
  fetchStreamNodes,
  revokeJoinToken,
  unregisterStreamNode,
  type JoinTokenRow,
  type StreamNodeRow,
} from '@/api/admin'

const loading = ref(false)
const nodes = ref<StreamNodeRow[]>([])
const healthy = ref<string[]>([])
const tokens = ref<JoinTokenRow[]>([])

const showAdd = ref(false)
const form = reactive({ name: '', node_url: '', weight: 100, ttl_minutes: 30 })
const creating = ref(false)

// 生成结果
const resultToken = ref('')
const resultExpires = ref('')
const dockerCmd = computed(() => {
  const origin = window.location.origin
  return [
    'docker run -d --name aetrix-stream --restart unless-stopped \\',
    '  --cap-add SYS_ADMIN --device /dev/fuse --security-opt apparmor:unconfined \\',
    `  -e JOIN_TOKEN=${resultToken.value} \\`,
    `  -e MAIN_URL=${origin} \\`,
    '  -v /var/cache/rclone-stream:/var/cache/rclone \\',
    '  ghcr.io/xzb177/aetrix-stream-node:latest',
  ].join('\n')
})

const isHealthy = (url: string) => healthy.value.includes(url)

async function load() {
  loading.value = true
  try {
    const r = await fetchStreamNodes()
    nodes.value = r.nodes || []
    healthy.value = r.healthy || []
    tokens.value = r.tokens || []
  } catch (e: any) {
    ElMessage.error(e?.message || '加载失败')
  } finally {
    loading.value = false
  }
}

function fmtTime(ts: number) {
  if (!ts) return '-'
  return new Date(ts * 1000).toLocaleString('zh-CN', { hour12: false })
}

function statusText(t: JoinTokenRow) {
  return t.status === 'pending' ? '待使用' : t.status === 'used' ? '已使用' : '已过期'
}

async function onCreate() {
  creating.value = true
  try {
    const r = await createJoinToken({
      name: form.name || undefined,
      node_url: form.node_url || undefined,
      weight: form.weight,
      ttl_minutes: form.ttl_minutes,
    })
    resultToken.value = r.token
    resultExpires.value = fmtTime(r.expires_at)
    showAdd.value = false
    await load()
    ElMessage.success('Token 已生成，30 分钟内有效（一次性）')
  } catch (e: any) {
    ElMessage.error(e?.message || '生成失败')
  } finally {
    creating.value = false
  }
}

async function copyCmd() {
  try {
    await navigator.clipboard.writeText(dockerCmd.value)
    ElMessage.success('docker 命令已复制')
  } catch {
    ElMessage.error('复制失败，请手动选中复制')
  }
}

async function onRevoke(t: JoinTokenRow) {
  try {
    await ElMessageBox.confirm(`作废 token（${t.name}）？`, '确认', { type: 'warning' })
  } catch { return }
  try {
    await revokeJoinToken(t.token)
    ElMessage.success('已作废')
    await load()
  } catch (e: any) {
    ElMessage.error(e?.message || '作废失败')
  }
}

async function onRemove(n: StreamNodeRow) {
  try {
    await ElMessageBox.confirm(`下线流节点 ${n.url}？播放 URL 将不再改写到它。`, '确认', { type: 'warning' })
  } catch { return }
  try {
    await unregisterStreamNode(n.url)
    ElMessage.success('已下线')
    await load()
  } catch (e: any) {
    ElMessage.error(e?.message || '下线失败')
  }
}

function resetResult() {
  resultToken.value = ''
}

onMounted(load)
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2>流节点</h2>
        <p class="desc">高宽带大盘机器独立出流。添加节点生成一次性 token，新机器一条 docker 命令即完成接入，无需 SSH。</p>
      </div>
      <div class="actions">
        <el-button :icon="RefreshCw" @click="load" :loading="loading">刷新</el-button>
        <el-button type="primary" :icon="Plus" @click="showAdd = true; resetResult()">添加节点</el-button>
      </div>
    </div>

    <!-- 刚生成的 token -->
    <el-alert v-if="resultToken" type="success" :closable="false" class="token-alert">
      <template #title>
        <div class="token-head">
          <span>Token 已生成（{{ resultExpires }} 前有效，一次性）</span>
          <el-button size="small" :icon="Copy" @click="copyCmd">复制 docker 命令</el-button>
        </div>
      </template>
      <pre class="docker-cmd">{{ dockerCmd }}</pre>
      <p class="hint">在新机器上执行上面命令即可。如需 CF 隐藏 IP，见文档 docs/streaming-node.md（域名橙云 + 防火墙只放 CF 回源段）。</p>
    </el-alert>

    <!-- 节点列表 -->
    <el-card class="card" v-loading="loading">
      <template #header><span>已注册节点（{{ nodes.length }}）</span></template>
      <el-empty v-if="!nodes.length" description="暂无流节点，播放走本机出流" />
      <el-table v-else :data="nodes" stripe>
        <el-table-column prop="name" label="名称" />
        <el-table-column prop="url" label="公网地址" min-width="220" />
        <el-table-column prop="weight" label="权重" width="80" />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag v-if="isHealthy(row.url)" type="success" :icon="CheckCircle2">在线</el-tag>
            <el-tag v-else type="danger" :icon="XCircle">不可达</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button size="small" type="danger" :icon="Trash2" @click="onRemove(row)">下线</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- Token 列表 -->
    <el-card class="card" v-loading="loading">
      <template #header><span>Join Token（{{ tokens.length }}）</span></template>
      <el-empty v-if="!tokens.length" description="暂无 token" />
      <el-table v-else :data="tokens" stripe>
        <el-table-column prop="name" label="名称" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.status === 'pending'" type="warning" :icon="Clock">待使用</el-tag>
            <el-tag v-else-if="row.status === 'used'">已使用</el-tag>
            <el-tag v-else type="info">已过期</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="node_url" label="节点地址" min-width="200" />
        <el-table-column label="过期时间" width="170">
          <template #default="{ row }">{{ fmtTime(row.expires_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button v-if="row.status === 'pending'" size="small" type="danger" @click="onRevoke(row)">作废</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 添加节点弹窗 -->
    <el-dialog v-model="showAdd" title="添加流节点" width="480px">
      <el-form :model="form" label-width="110px">
        <el-form-item label="节点名称">
          <el-input v-model="form.name" placeholder="如：流节点-1（可空）" />
        </el-form-item>
        <el-form-item label="公网域名">
          <el-input v-model="form.node_url" placeholder="https://stream.example.com（可空，容器启动时上报）" />
        </el-form-item>
        <el-form-item label="权重">
          <el-input-number v-model="form.weight" :min="1" :max="1000" />
          <span class="form-hint">多节点按权重分流</span>
        </el-form-item>
        <el-form-item label="有效期（分钟）">
          <el-input-number v-model="form.ttl_minutes" :min="5" :max="1440" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showAdd = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="onCreate">生成 Token</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page { padding: 20px; max-width: 1100px; }
.page-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; }
.page-head h2 { margin: 0 0 6px; font-size: 20px; }
.desc { margin: 0; color: #909399; font-size: 13px; }
.actions { display: flex; gap: 8px; }
.card { margin-bottom: 16px; }
.token-alert { margin-bottom: 16px; }
.token-head { display: flex; justify-content: space-between; align-items: center; width: 100%; }
.docker-cmd {
  background: #1e1e1e; color: #d4d4d4; padding: 12px; border-radius: 6px;
  font-size: 12px; line-height: 1.7; overflow-x: auto; white-space: pre; margin: 8px 0;
}
.hint { margin: 4px 0 0; font-size: 12px; color: #909399; }
.form-hint { margin-left: 8px; font-size: 12px; color: #909399; }
</style>
