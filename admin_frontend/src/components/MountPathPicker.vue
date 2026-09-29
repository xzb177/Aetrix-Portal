<template>
  <el-dialog
    v-model="visible"
    title="选择挂载目录"
    width="560px"
    :close-on-click-modal="false"
    @open="onOpen"
  >
    <div class="picker-body">
      <!-- 挂载选择（数据驱动，不写死） -->
      <el-form-item label="存储挂载">
        <el-select
          v-model="mountId"
          placeholder="请选择挂载"
          style="width: 100%"
          :loading="mountsLoading"
          @change="onMountChange"
        >
          <el-option
            v-for="m in mounts"
            :key="m.id"
            :label="`${m.name}（${m.mount_type || ''}）`"
            :value="m.id"
          />
        </el-select>
      </el-form-item>

      <!-- 面包屑导航 -->
      <div v-if="mountId" class="picker-crumbs">
        <el-breadcrumb separator="/">
          <el-breadcrumb-item>
            <a @click.prevent="goPath('/')">根目录</a>
          </el-breadcrumb-item>
          <el-breadcrumb-item v-for="c in crumbs" :key="c.path">
            <a @click.prevent="goPath(c.path)">{{ c.name }}</a>
          </el-breadcrumb-item>
        </el-breadcrumb>
        <div class="picker-current">当前：<code>{{ displayPath }}</code></div>
      </div>

      <!-- 目录列表 -->
      <div v-if="mountId" v-loading="dirsLoading" class="picker-dirs">
        <div v-if="parent" class="picker-dir-row picker-up" @click="goPath(parent)">
          <span class="dir-icon">↩</span> 返回上一级
        </div>
        <div v-if="!dirsLoading && dirs.length === 0" class="picker-empty">
          该目录下没有子目录
        </div>
        <div
          v-for="d in dirs"
          :key="d.path"
          class="picker-dir-row"
          @click="goPath(d.path)"
        >
          <span class="dir-icon">📁</span> {{ d.name }}
        </div>
        <div v-if="loadError" class="picker-error">{{ loadError }}</div>
      </div>
    </div>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button
        type="primary"
        :disabled="!mountId"
        @click="confirmSelect"
      >
        选择此目录
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { browseMountDirs, fetchMounts } from '@/api/admin'
import type { MountPickerCrumb, MountPickerDir } from '@/api/admin'

const emit = defineEmits<{
  (e: 'select', mountPath: string): void
}>()

const visible = ref(false)
const mounts = ref<Array<{ id: number; name: string; mount_type?: string }>>([])
const mountsLoading = ref(false)
const mountId = ref<number | null>(null)
const currentPath = ref('/')
const crumbs = ref<MountPickerCrumb[]>([])
const dirs = ref<MountPickerDir[]>([])
const parent = ref<string | null>(null)
const dirsLoading = ref(false)
const loadError = ref('')

const displayPath = computed(() => {
  if (!mountId.value) return ''
  const p = currentPath.value === '/' ? '' : currentPath.value
  return `mount://${mountId.value}${p}`
})

function open() {
  visible.value = true
}

async function onOpen() {
  // 每次打开重置状态
  mountId.value = null
  currentPath.value = '/'
  crumbs.value = []
  dirs.value = []
  parent.value = null
  loadError.value = ''
  mountsLoading.value = true
  try {
    const res = await fetchMounts()
    mounts.value = (res.mounts || []).filter((m: any) => m.is_enabled !== false)
    // 如果只有一个挂载，自动选中
    if (mounts.value.length === 1) {
      mountId.value = mounts.value[0].id
      await loadDirs()
    }
  } catch (e: any) {
    ElMessage.error(e?.message || '加载挂载列表失败')
  } finally {
    mountsLoading.value = false
  }
}

async function onMountChange() {
  currentPath.value = '/'
  await loadDirs()
}

async function goPath(path: string) {
  currentPath.value = path
  await loadDirs()
}

async function loadDirs() {
  if (!mountId.value) return
  dirsLoading.value = true
  loadError.value = ''
  try {
    const res = await browseMountDirs(mountId.value, currentPath.value === '/' ? undefined : currentPath.value)
    currentPath.value = res.path
    crumbs.value = res.crumbs
    dirs.value = res.dirs
    parent.value = res.parent
  } catch (e: any) {
    loadError.value = e?.response?.data?.detail || e?.message || '加载目录失败'
    dirs.value = []
  } finally {
    dirsLoading.value = false
  }
}

function confirmSelect() {
  if (!mountId.value) return
  emit('select', displayPath.value)
  visible.value = false
}

defineExpose({ open })
</script>

<style scoped>
.picker-body {
  min-height: 200px;
}
.picker-crumbs {
  margin: 12px 0;
}
.picker-crumbs a {
  cursor: pointer;
  color: var(--el-color-primary);
}
.picker-current {
  margin-top: 8px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}
.picker-current code {
  background: var(--el-fill-color-light);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 12px;
}
.picker-dirs {
  max-height: 320px;
  overflow-y: auto;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  min-height: 120px;
}
.picker-dir-row {
  padding: 10px 14px;
  cursor: pointer;
  border-bottom: 1px solid var(--el-border-color-extra-light);
  display: flex;
  align-items: center;
  gap: 8px;
}
.picker-dir-row:hover {
  background: var(--el-fill-color-light);
}
.picker-dir-row:last-child {
  border-bottom: none;
}
.picker-up {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.dir-icon {
  font-size: 16px;
}
.picker-empty {
  padding: 24px;
  text-align: center;
  color: var(--el-text-color-placeholder);
}
.picker-error {
  padding: 12px 14px;
  color: var(--el-color-danger);
  font-size: 13px;
}
</style>
