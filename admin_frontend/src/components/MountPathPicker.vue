<template>
  <el-dialog
    v-model="visible"
    title="选择挂载目录"
    width="min(560px, 92vw)"
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

      <!-- 选择模式：单选（原有行为）/ 多选（新增：勾选多个目录一次性追加） -->
      <div class="picker-mode">
        <el-radio-group v-model="mode" size="small">
          <el-radio-button value="single">单选</el-radio-button>
          <el-radio-button value="multi">多选</el-radio-button>
        </el-radio-group>
        <span class="picker-mode-hint">
          {{ mode === 'single'
            ? '点击目录逐级进入，确认后选择当前目录'
            : '点左侧方框勾选，进入下一级后勾选仍然保留' }}
        </span>
      </div>

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
          :class="{ 'is-selected': mode === 'multi' && isSelected(dirFullPath(d.path)) }"
          @click="goPath(d.path)"
        >
          <span
            v-if="mode === 'multi'"
            class="picker-box"
            :class="{ on: isSelected(dirFullPath(d.path)) }"
            role="checkbox"
            :aria-checked="isSelected(dirFullPath(d.path))"
            :aria-label="`勾选 ${d.name}`"
            @click.stop="toggleSelect(dirFullPath(d.path))"
          >✓</span>
          <span class="dir-icon">📁</span> {{ d.name }}
        </div>
        <div v-if="loadError" class="picker-error">{{ loadError }}</div>
      </div>

      <!-- 多选：已选清单 + 数量 + 全选/清空 -->
      <div v-if="mode === 'multi' && mountId" class="picker-sel">
        <div v-if="selected.length" class="picker-sel-list">
          <div v-for="p in selected" :key="p" class="picker-sel-item">
            <code>{{ p }}</code>
            <button
              type="button"
              class="picker-sel-x"
              :aria-label="`移除 ${p}`"
              @click="removeSelected(p)"
            >×</button>
          </div>
        </div>
        <div class="picker-sel-bar">
          <span class="picker-sel-count">已选 <b>{{ selected.length }}</b> 个目录</span>
          <span class="picker-sel-actions">
            <el-button
              size="small"
              :disabled="!pagePaths.length"
              @click="allPageSelected ? clearPageSelect() : selectAllPage()"
            >
              {{ allPageSelected ? '取消本页' : '全选本页' }}
            </el-button>
            <el-button size="small" :disabled="!selected.length" @click="clearSelected">
              清空
            </el-button>
          </span>
        </div>
        <p v-if="!selected.length" class="picker-sel-hint">
          勾选要追加的目录（可跨层级多次勾选），确认后一次性写入路径框。
        </p>
      </div>
    </div>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button
        v-if="mode === 'single'"
        type="primary"
        :disabled="!mountId"
        @click="confirmSelect"
      >
        选择此目录
      </el-button>
      <el-button
        v-else
        type="primary"
        :disabled="!selected.length"
        @click="confirmMulti"
      >
        追加所选（{{ selected.length }}）
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
  /** 单选：追加一个目录（原有行为，口径未变） */
  (e: 'select', mountPath: string): void
  /** 多选：一次性追加多个目录（调用方负责去重与写入顺序） */
  (e: 'select-multi', mountPaths: string[]): void
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

/** 选择模式：single = 原有单选（默认，行为不变）；multi = 勾选多个目录一次追加 */
const mode = ref<'single' | 'multi'>('single')
/** 多选勾选的完整 mount:// 路径：跨目录保留（换个层级继续勾），换挂载/重开时清空 */
const selected = ref<string[]>([])

const displayPath = computed(() => dirFullPath(currentPath.value))

/** 挂载内路径 → 完整 mount:// 路径（与 displayPath 同一口径） */
function dirFullPath(p: string): string {
  if (!mountId.value) return ''
  const raw = (p || '').trim()
  const norm = !raw || raw === '/' ? '' : (raw.startsWith('/') ? raw : `/${raw}`)
  return `mount://${mountId.value}${norm}`
}

function open() {
  visible.value = true
}

async function onOpen() {
  // 每次打开重置状态（模式也回到默认的单选，保证老路径行为不变）
  mountId.value = null
  currentPath.value = '/'
  crumbs.value = []
  dirs.value = []
  parent.value = null
  loadError.value = ''
  mode.value = 'single'
  selected.value = []
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
  // 勾选里带着上一个挂载的 mount://<id>，换挂载后语义就不对了：整批作废
  selected.value = []
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

// ---- 多选 ----

function isSelected(path: string): boolean {
  return !!path && selected.value.includes(path)
}

function toggleSelect(path: string) {
  if (!path) return
  const i = selected.value.indexOf(path)
  if (i >= 0) selected.value.splice(i, 1)
  else selected.value.push(path)
}

function removeSelected(path: string) {
  const i = selected.value.indexOf(path)
  if (i >= 0) selected.value.splice(i, 1)
}

/** 当前列表里所有目录的完整路径（「全选」只作用于本页，不做远程递归） */
const pagePaths = computed(() => dirs.value.map((d) => dirFullPath(d.path)).filter(Boolean))

const allPageSelected = computed(
  () => pagePaths.value.length > 0 && pagePaths.value.every((p) => selected.value.includes(p)),
)

function selectAllPage() {
  const set = new Set(selected.value)
  for (const p of pagePaths.value) set.add(p)
  selected.value = [...set]
}

/** 只取消当前列表里被勾的（其它层级的勾选不受影响） */
function clearPageSelect() {
  const page = new Set(pagePaths.value)
  selected.value = selected.value.filter((p) => !page.has(p))
}

function clearSelected() {
  selected.value = []
}

// ---- 确认 ----

function confirmSelect() {
  if (!mountId.value) return
  emit('select', displayPath.value)
  visible.value = false
}

function confirmMulti() {
  if (!selected.value.length) return
  emit('select-multi', [...selected.value])
  visible.value = false
}

defineExpose({ open })
</script>

<style scoped>
.picker-body {
  min-height: 200px;
}
.picker-mode {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}
.picker-mode-hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
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
.picker-dir-row.is-selected {
  background: var(--el-color-primary-light-9);
}
.picker-dir-row.is-selected:hover {
  background: var(--el-color-primary-light-8);
}
.picker-dir-row:last-child {
  border-bottom: none;
}
.picker-up {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
/* 多选勾选框：已选 = 主色底 + 白勾；未选 = 描边空框 */
.picker-box {
  width: 18px;
  height: 18px;
  flex: none;
  border: 1px solid var(--el-border-color);
  border-radius: 4px;
  background: var(--el-fill-color-blank);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  line-height: 1;
  color: transparent;
  cursor: pointer;
  user-select: none;
}
.picker-box.on {
  background: var(--el-color-primary);
  border-color: var(--el-color-primary);
  /* 勾选态底色是主色（深浅色主题下都是主色）：白勾不依赖主题变量，令牌检查也只认被引入的定义 */
  color: #fff;
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
/* 多选：已选清单 + 底部计数条 */
.picker-sel {
  margin-top: 10px;
}
.picker-sel-list {
  max-height: 104px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px;
  margin-bottom: 8px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  background: var(--el-fill-color-light);
}
.picker-sel-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.picker-sel-item code {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  background: var(--el-fill-color);
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 11.5px;
  color: var(--el-text-color-regular);
}
.picker-sel-x {
  flex: none;
  border: none;
  background: transparent;
  padding: 2px 4px;
  font-size: 15px;
  line-height: 1;
  color: var(--el-text-color-secondary);
  cursor: pointer;
}
.picker-sel-x:hover {
  color: var(--el-color-danger);
}
.picker-sel-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.picker-sel-count {
  font-size: 13px;
  color: var(--el-text-color-regular);
}
.picker-sel-count b {
  font-size: 16px;
  color: var(--el-color-primary);
}
.picker-sel-hint {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
</style>
