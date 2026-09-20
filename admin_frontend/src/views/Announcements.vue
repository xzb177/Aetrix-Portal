<script setup lang="ts">
/** 公告管理：创建/编辑/置顶/删除，联动全站推送 */
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, RefreshCw } from 'lucide-vue-next'
import { createAnnouncement, deleteAnnouncement, fetchAnnouncements, updateAnnouncement } from '@/api/admin'
import type { Announcement } from '@/types'

const list = ref<Announcement[]>([])
const loading = ref(false)

const dialogVisible = ref(false)
const editing = ref<Announcement | null>(null)
const form = ref({ title: '', content: '', type: 'system', is_pinned: false })

async function load() {
  loading.value = true
  try {
    list.value = await fetchAnnouncements()
  } finally {
    loading.value = false
  }
}

onMounted(load)

function openCreate() {
  editing.value = null
  form.value = { title: '', content: '', type: 'system', is_pinned: false }
  dialogVisible.value = true
}

function openEdit(a: Announcement) {
  editing.value = a
  form.value = { title: a.title, content: a.content, type: a.type, is_pinned: a.is_pinned }
  dialogVisible.value = true
}

async function submit() {
  if (!form.value.title.trim() || !form.value.content.trim()) {
    ElMessage.warning('标题和内容不能为空')
    return
  }
  if (editing.value) {
    await updateAnnouncement(editing.value.id, form.value)
    ElMessage.success('公告已更新并推送')
  } else {
    await createAnnouncement(form.value)
    ElMessage.success('公告已创建并推送给所有用户')
  }
  dialogVisible.value = false
  load()
}

async function remove(a: Announcement) {
  await ElMessageBox.confirm(`确定删除公告「${a.title}」吗？`, '确认', { type: 'warning' })
  await deleteAnnouncement(a.id)
  ElMessage.success('已删除')
  load()
}

async function togglePin(a: Announcement) {
  await updateAnnouncement(a.id, { is_pinned: !a.is_pinned })
  load()
}

function fmtDate(s: string): string {
  return s.slice(0, 16).replace('T', ' ')
}
</script>

<template>
  <div class="admin-page">
    <div class="admin-page-header">
      <div>
        <h1 class="admin-page-title">公告管理</h1>
        <p class="admin-page-subtitle">发布公告会实时推送给所有在线用户</p>
      </div>
      <div class="toolbar">
        <el-button type="primary" @click="openCreate"><Plus :size="14" style="margin-right: 4px" />发布公告</el-button>
        <el-button @click="load"><RefreshCw :size="14" /></el-button>
      </div>
    </div>

    <div class="admin-card">
      <el-table :data="list" v-loading="loading" style="width: 100%" :header-cell-style="{ background: 'transparent', color: '#a3a3a3' }">
        <el-table-column label="公告" min-width="260">
          <template #default="{ row }">
            <div class="ann-title">
              <span v-if="row.is_pinned" class="mini-badge pin">置顶</span>
              {{ row.title }}
            </div>
            <div class="ann-content">{{ row.content }}</div>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="90">
          <template #default="{ row }">
            <span class="mini-badge type">{{ row.type === 'system' ? '系统' : row.type }}</span>
          </template>
        </el-table-column>
        <el-table-column label="发布时间" width="150">
          <template #default="{ row }">{{ fmtDate(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="170" fixed="right">
          <template #default="{ row }">
            <el-button size="small" text @click="togglePin(row)">{{ row.is_pinned ? '取消置顶' : '置顶' }}</el-button>
            <el-button size="small" text type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button size="small" text type="danger" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="dialogVisible" :title="editing ? '编辑公告' : '发布公告'" width="480px">
      <el-form label-width="60px">
        <el-form-item label="标题"><el-input v-model="form.title" placeholder="公告标题" /></el-form-item>
        <el-form-item label="内容">
          <el-input v-model="form.content" type="textarea" :rows="5" placeholder="公告内容" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.type" style="width: 140px">
            <el-option label="系统" value="system" />
            <el-option label="维护" value="maintenance" />
            <el-option label="活动" value="activity" />
          </el-select>
        </el-form-item>
        <el-form-item label="置顶"><el-switch v-model="form.is_pinned" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submit">{{ editing ? '保存' : '发布' }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.toolbar { display: flex; gap: 8px; }
.ann-title { display: flex; align-items: center; gap: 6px; font-weight: 600; }
.ann-content {
  font-size: 12px;
  color: var(--color-text-muted, #737373);
  margin-top: 2px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.mini-badge { font-size: 10px; padding: 1px 7px; border-radius: 999px; font-weight: 600; flex-shrink: 0; }
.mini-badge.pin { background: rgba(234, 179, 8, 0.15); color: #eab308; }
.mini-badge.type { background: rgba(255, 255, 255, 0.08); color: var(--color-text-secondary, #a3a3a3); }
</style>
