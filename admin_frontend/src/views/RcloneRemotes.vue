<script setup lang="ts">
/**
 * Rclone 配置：remote 集中管理
 *
 * - Remote 列表：个人盘（OAuth）/ 服务账号 + 团队盘
 * - 一键生成 rclone.conf 并应用到 rclone 容器
 * - 指定哪个 remote 用于后台探测（ffprobe）
 *
 * 密钥类字段（client_secret / token / 服务账号 JSON）前端不回传明文，
 * 只显示是否已配置。
 */
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { KeyRound, Plus, RefreshCw, Trash2, Pencil, Zap, Eye, Upload, CheckCircle } from 'lucide-vue-next'
import {
  fetchRcloneRemotes,
  createRcloneRemote,
  updateRcloneRemote,
  deleteRcloneRemote,
  generateRcloneConf,
  previewRcloneConf,
  setProbeRcloneRemote,
  fetchRcloneOAuthUrl,
  submitRcloneOAuthCode,
  uploadRcloneServiceAccount,
} from '@/api/admin'
import type { RcloneRemote } from '@/types'

const remotes = ref<RcloneRemote[]>([])
const loading = ref(false)
const generating = ref(false)
const previewVisible = ref(false)
const previewContent = ref('')

const dialogVisible = ref(false)
const editing = ref<RcloneRemote | null>(null)
const saving = ref(false)
const form = ref({
  name: '',
  drive_type: 'personal' as 'personal' | 'service_account',
  client_id: '',
  client_secret: '',
  team_drive_id: '',
  is_enabled: true,
  remark: '',
})

// OAuth
const oauthVisible = ref(false)
const oauthRemote = ref<RcloneRemote | null>(null)
const oauthUrl = ref('')
const oauthRedirectUri = ref('')
const oauthCode = ref('')
const oauthSubmitting = ref(false)

// 服务账号上传
const saUploading = ref(false)

async function load() {
  loading.value = true
  try {
    const res = await fetchRcloneRemotes()
    remotes.value = res.remotes
  } catch (e: any) {
    ElMessage.error(e?.message || '加载失败')
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editing.value = null
  form.value = {
    name: '',
    drive_type: 'personal',
    client_id: '',
    client_secret: '',
    team_drive_id: '',
    is_enabled: true,
    remark: '',
  }
  dialogVisible.value = true
}

function openEdit(row: RcloneRemote) {
  editing.value = row
  form.value = {
    name: row.name,
    drive_type: row.drive_type,
    client_id: row.client_id,
    client_secret: '', // 不回传，前端留空 = 不修改
    team_drive_id: row.team_drive_id,
    is_enabled: row.is_enabled,
    remark: row.remark,
  }
  dialogVisible.value = true
}

async function save() {
  if (!form.value.name.trim()) {
    ElMessage.warning('请填写 remote 名称')
    return
  }
  saving.value = true
  try {
    if (editing.value) {
      const data: any = {
        name: form.value.name.trim(),
        team_drive_id: form.value.team_drive_id.trim(),
        is_enabled: form.value.is_enabled,
        remark: form.value.remark,
      }
      if (form.value.drive_type === 'personal') {
        data.client_id = form.value.client_id.trim()
        if (form.value.client_secret.trim()) {
          data.client_secret = form.value.client_secret.trim()
        }
      }
      await updateRcloneRemote(editing.value.id, data)
      ElMessage.success('已更新')
    } else {
      await createRcloneRemote({
        name: form.value.name.trim(),
        remote_type: 'drive',
        drive_type: form.value.drive_type,
        client_id: form.value.client_id.trim(),
        client_secret: form.value.client_secret.trim(),
        team_drive_id: form.value.team_drive_id.trim(),
        is_enabled: form.value.is_enabled,
        remark: form.value.remark,
      })
      ElMessage.success('已创建')
    }
    dialogVisible.value = false
    load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '保存失败')
  } finally {
    saving.value = false
  }
}

async function remove(row: RcloneRemote) {
  try {
    await ElMessageBox.confirm(
      `确定删除 remote「${row.name}」吗？只删数据库配置，不动云盘文件。`,
      '删除确认',
      { type: 'warning' }
    )
  } catch {
    return
  }
  try {
    await deleteRcloneRemote(row.id)
    ElMessage.success('已删除')
    load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '删除失败')
  }
}

async function setProbe(row: RcloneRemote) {
  try {
    const res = await setProbeRcloneRemote(row.id)
    ElMessage.success(`探测 remote 已设为「${res.probe_remote}」`)
    load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '设置失败')
  }
}

async function doGenerate() {
  try {
    await ElMessageBox.confirm(
      '从数据库生成 rclone.conf，写入 rclone 容器并重启生效。旧配置会自动备份。继续？',
      '生成并应用配置',
      { type: 'warning' }
    )
  } catch {
    return
  }
  generating.value = true
  try {
    const res = await generateRcloneConf()
    ElMessage.success(res.message)
    if (!res.reload.success) {
      ElMessage.warning('配置已写入，但 rclone 重启失败：' + res.reload.message)
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '生成失败')
  } finally {
    generating.value = false
  }
}

async function showPreview() {
  try {
    const res = await previewRcloneConf()
    previewContent.value = res.preview || '(空：没有启用的 remote)'
    previewVisible.value = true
  } catch (e: any) {
    ElMessage.error(e?.message || '预览失败')
  }
}

// OAuth
async function openOAuth(row: RcloneRemote) {
  try {
    const res = await fetchRcloneOAuthUrl(row.id)
    oauthRemote.value = row
    oauthUrl.value = res.oauth_url
    oauthRedirectUri.value = res.redirect_uri
    oauthCode.value = ''
    oauthVisible.value = true
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '获取授权链接失败')
  }
}

function openOAuthPage() {
  window.open(oauthUrl.value, '_blank')
}

async function submitOAuth() {
  if (!oauthCode.value.trim()) {
    ElMessage.warning('请粘贴授权码')
    return
  }
  oauthSubmitting.value = true
  try {
    await submitRcloneOAuthCode(oauthRemote.value!.id, {
      code: oauthCode.value.trim(),
      redirect_uri: oauthRedirectUri.value,
    })
    ElMessage.success('授权成功，token 已保存')
    oauthVisible.value = false
    load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '授权失败')
  } finally {
    oauthSubmitting.value = false
  }
}

// 服务账号上传
async function handleSaUpload(row: RcloneRemote, file: File) {
  saUploading.value = true
  try {
    const res = await uploadRcloneServiceAccount(row.id, file)
    ElMessage.success(`已上传服务账号：${res.client_email}`)
    load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '上传失败')
  } finally {
    saUploading.value = false
  }
  return false // 阻止 el-upload 自动上传
}

function driveTypeLabel(row: RcloneRemote) {
  return row.drive_type === 'service_account' ? '服务账号' : '个人盘'
}

onMounted(load)
</script>

<template>
  <div class="rclone-remotes">
    <div class="rclone-toolbar">
      <div class="rclone-desc">
        Remote = 访问云盘的方式。改完点「生成并应用」，配置会自动写到 rclone 容器并生效。
      </div>
      <div class="rclone-actions">
        <el-button @click="showPreview">
          <Eye :size="14" style="margin-right: 4px" />预览配置
        </el-button>
        <el-button type="primary" :loading="generating" @click="doGenerate">
          <Zap :size="14" style="margin-right: 4px" />生成并应用配置
        </el-button>
        <el-button type="primary" @click="openCreate">
          <Plus :size="14" style="margin-right: 4px" />新建 Remote
        </el-button>
        <el-button @click="load"><RefreshCw :size="14" /></el-button>
      </div>
    </div>

    <el-table :data="remotes" v-loading="loading" style="width: 100%">
      <el-table-column prop="name" label="名称" min-width="140">
        <template #default="{ row }">
          <span class="remote-name">{{ row.name }}</span>
          <el-tag v-if="row.is_probe_remote" type="success" size="small" style="margin-left: 6px">
            探测用
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="类型" width="110">
        <template #default="{ row }">
          <el-tag :type="row.drive_type === 'service_account' ? 'warning' : ''" size="small">
            {{ driveTypeLabel(row) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="团队盘" min-width="160">
        <template #default="{ row }">
          <span v-if="row.team_drive_id" class="mono">{{ row.team_drive_id.slice(0, 20) }}…</span>
          <span v-else class="muted">个人盘</span>
        </template>
      </el-table-column>
      <el-table-column label="凭据" width="180">
        <template #default="{ row }">
          <div v-if="row.drive_type === 'personal'" class="cred-cell">
            <span :class="row.has_token ? 'ok' : 'missing'">
              {{ row.has_token ? '✓ 已授权' : '✗ 未授权' }}
            </span>
          </div>
          <div v-else class="cred-cell">
            <span :class="row.has_service_account ? 'ok' : 'missing'">
              {{ row.has_service_account ? '✓ ' + (row.service_account_file || '已上传') : '✗ 未上传' }}
            </span>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="80">
        <template #default="{ row }">
          <el-tag :type="row.is_enabled ? 'success' : 'info'" size="small">
            {{ row.is_enabled ? '启用' : '禁用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="300" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="openEdit(row)">
            <Pencil :size="12" />编辑
          </el-button>
          <el-button
            v-if="!row.is_probe_remote"
            size="small"
            type="success"
            @click="setProbe(row)"
          >
            设为探测用
          </el-button>
          <el-button
            v-if="row.drive_type === 'personal'"
            size="small"
            type="warning"
            @click="openOAuth(row)"
          >
            <KeyRound :size="12" />授权
          </el-button>
          <el-upload
            v-if="row.drive_type === 'service_account'"
            :show-file-list="false"
            :before-upload="(f: File) => handleSaUpload(row, f)"
            style="display: inline-block; margin-left: 8px"
          >
            <el-button size="small" type="warning" :loading="saUploading">
              <Upload :size="12" />上传密钥
            </el-button>
          </el-upload>
          <el-button size="small" type="danger" @click="remove(row)">
            <Trash2 :size="12" />
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <div v-if="!remotes.length && !loading" class="empty-hint">
      还没有配置 remote。点「新建 Remote」添加个人盘或服务账号。
    </div>

    <!-- 新建/编辑 -->
    <el-dialog
      v-model="dialogVisible"
      :title="editing ? `编辑 ${editing.name}` : '新建 Remote'"
      width="520px"
    >
      <el-form :model="form" label-width="110px">
        <el-form-item label="名称" required>
          <el-input v-model="form.name" placeholder="如 paul_emby（字母数字下划线）" :disabled="!!editing" />
        </el-form-item>
        <el-form-item label="类型">
          <el-radio-group v-model="form.drive_type" :disabled="!!editing">
            <el-radio value="personal">个人盘（OAuth）</el-radio>
            <el-radio value="service_account">服务账号</el-radio>
          </el-radio-group>
        </el-form-item>
        <template v-if="form.drive_type === 'personal'">
          <el-form-item label="Client ID">
            <el-input v-model="form.client_id" placeholder="Google OAuth Client ID" />
          </el-form-item>
          <el-form-item label="Client Secret">
            <el-input
              v-model="form.client_secret"
              type="password"
              show-password
              :placeholder="editing ? '(留空不修改)' : 'Google OAuth Client Secret'"
            />
          </el-form-item>
        </template>
        <el-form-item label="团队盘 ID">
          <el-input v-model="form.team_drive_id" placeholder="留空 = 个人盘" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.is_enabled" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.remark" placeholder="选填" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <!-- 预览 -->
    <el-dialog v-model="previewVisible" title="rclone.conf 预览（敏感字段已脱敏）" width="640px">
      <pre class="conf-preview">{{ previewContent }}</pre>
    </el-dialog>

    <!-- OAuth 授权 -->
    <el-dialog v-model="oauthVisible" title="Google 授权" width="520px">
      <p>1. 点下面按钮打开 Google 授权页，登录并允许访问 Drive</p>
      <p>2. 把跳转后地址栏里的 <code>code=</code> 参数值粘贴到下面</p>
      <el-button type="primary" @click="openOAuthPage" style="margin: 12px 0">
        打开 Google 授权页
      </el-button>
      <el-input
        v-model="oauthCode"
        type="textarea"
        :rows="3"
        placeholder="粘贴授权码（code= 后面的那串）"
      />
      <template #footer>
        <el-button @click="oauthVisible = false">取消</el-button>
        <el-button type="primary" :loading="oauthSubmitting" @click="submitOAuth">
          <CheckCircle :size="14" style="margin-right: 4px" />提交授权码
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.rclone-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  flex-wrap: wrap;
  gap: 12px;
}
.rclone-desc {
  color: #909399;
  font-size: 13px;
}
.rclone-actions {
  display: flex;
  gap: 8px;
}
.remote-name {
  font-weight: 600;
  font-family: monospace;
}
.mono {
  font-family: monospace;
  font-size: 12px;
}
.muted {
  color: #909399;
}
.ok {
  color: #67c23a;
}
.missing {
  color: #f56c6c;
}
.cred-cell {
  font-size: 13px;
}
.empty-hint {
  text-align: center;
  color: #909399;
  padding: 40px 0;
}
.conf-preview {
  background: #f5f7fa;
  border-radius: 6px;
  padding: 16px;
  font-size: 12px;
  max-height: 400px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
