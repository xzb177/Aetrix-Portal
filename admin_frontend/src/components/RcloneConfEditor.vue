<script setup lang="ts">
/**
 * rclone.conf：用户粘贴，面板只负责落盘并给 rclone 命令加 --config
 *
 * 以前这里是一个「rclone remote 管理」页：逐条填 client_id / token / 服务账号 JSON，
 * 由后端拼出 rclone.conf 再写进 rclone 容器。v2.42.11 起这条路整个删掉了——
 * 面板不代管凭据，也不该决定 rclone 装在哪、配置写在哪。
 *
 * 现在只有一件事：把用户粘进来的标准 INI 文本（`rclone config` 生成的那种）
 * 整份写到 data/rclone/rclone.conf。**不回显原文**——里面全是 token / secret，
 * 回显就等于把它写进浏览器历史与前端日志；所以这里只显示 remote 名列表。
 */
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { RefreshCw, Save } from 'lucide-vue-next'
import { fetchRcloneConf, saveRcloneConf } from '@/api/admin'

const emit = defineEmits<{ saved: [] }>()

const EXAMPLE = `[gdrive]
type = drive
client_id = your-client-id.apps.googleusercontent.com
client_secret = your-client-secret
token = {"access_token":"ya29.…","token_type":"Bearer","refresh_token":"1//…","expiry":"2026-01-01T00:00:00.000000000+08:00"}
team_drive =

[MP]
type = webdav
url = https://dav.example.com
vendor = other
user = your-user
pass = your-pass`

const status = ref<{ path: string; configured: boolean; remotes: string[] } | null>(null)
const draft = ref('')
const loading = ref(false)
const saving = ref(false)

async function load() {
  loading.value = true
  try {
    status.value = await fetchRcloneConf()
  } catch {
    status.value = null
  } finally {
    loading.value = false
  }
}

async function save() {
  if (!draft.value.trim()) {
    ElMessage.warning('请粘贴 rclone.conf 的内容')
    return
  }
  saving.value = true
  try {
    const res = await saveRcloneConf(draft.value)
    ElMessage.success(`已保存到 ${res.path}（${res.total} 个 remote）`)
    draft.value = ''
    await load()
    emit('saved')
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    ElMessage.error(detail || '保存失败')
  } finally {
    saving.value = false
  }
}

function useExample() {
  draft.value = EXAMPLE
}

onMounted(load)
</script>

<template>
  <div class="conf-editor">
    <el-alert type="info" :closable="false" show-icon style="margin-bottom: 16px">
      <template #title>面板不代管 rclone 凭据，只负责「能跑 rclone」</template>
      <div class="conf-note">
        <p style="margin: 6px 0 0">
          rclone <b>装在哪、配置写在哪，你自己决定</b>。把 <code>rclone config</code> 生成的
          INI 文本原样粘到下面，它会落到
          <code>{{ status?.path || 'data/rclone/rclone.conf' }}</code>（权限 600），
          调用 rclone 时自动带 <code>--config</code> 指过去。
        </p>
        <p style="margin: 6px 0 0">
          服务器上得先有 rclone 可执行文件。容器里没有的话，在
          <code>docker-compose.yml</code> 里加一行装它，或者挂一个宿主机上装好的进去。
        </p>
      </div>
    </el-alert>

    <div class="conf-status">
      <el-button :loading="loading" size="small" @click="load">
        <RefreshCw :size="13" />
      </el-button>
      <template v-if="status?.configured">
        <span class="mini-badge ok">{{ status.remotes.length }} 个 remote</span>
        <code v-for="r in status.remotes" :key="r" class="remote-tag">{{ r }}</code>
      </template>
      <span v-else-if="status" class="mini-badge off">还没有 rclone.conf</span>
    </div>

    <el-input
      v-model="draft"
      type="textarea"
      :rows="14"
      placeholder="在这里粘贴 rclone.conf 的完整内容（标准 INI 文本）"
    />

    <div class="conf-actions">
      <el-button type="primary" :loading="saving" @click="save">
        <Save :size="14" style="margin-right: 4px" />保存并覆盖
      </el-button>
      <el-button @click="useExample">填入示例</el-button>
      <span class="form-hint">
        整份替换。原文不回显——那里面全是 token / secret；要改就重新粘一份。
      </span>
    </div>
  </div>
</template>

<style scoped>
.conf-note p {
  line-height: 1.6;
}

.conf-status {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}

.remote-tag {
  padding: 1px 7px;
  border: 1px solid var(--el-border-color);
  border-radius: 4px;
  font-size: 12px;
  background: var(--el-fill-color-light);
}

.conf-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 12px;
}
</style>