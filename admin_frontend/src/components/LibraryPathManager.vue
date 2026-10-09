<script setup lang="ts">
/**
 * 媒体库「媒体路径」区块：一份列表 + 一个添加按钮 + 一个浏览/更换弹窗
 *
 * 这一块刻意做得极简——一行一条路径、旁边两个图标：
 *   📁 浏览/更换目录（就地改这一条）   ✕ 删除这一条
 *
 * 「按类型添加路径」是添加的唯一入口（v2.46.0）：弹窗里先选类型（默认本地硬盘）再浏览
 * 目录，类型与挂载都在弹窗里定，所以库里不再有第二个「选挂载」的地方。
 *
 * 之前这块是一个多行文本框加一段“mount://<id>/子目录”的格式说明，而那种路径对人
 * 没有信息量（id 是数据库主键）。现在路径与存储后端分开展示：路径写 `/电影`，后端
 * 单独一个标签（本地文件 / Rclone / 115 网盘），改后端也不影响已选的目录。
 */
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { FolderOpen, FolderSearch, Plus, X } from 'lucide-vue-next'
import LibraryPathDialog from './LibraryPathDialog.vue'
import { EmptyState } from '@/components/ui'
import type { LibraryPathEntry, StorageBackend, StorageMount } from '@/types'

const props = withDefaults(defineProps<{
  modelValue: LibraryPathEntry[]
  mounts?: StorageMount[]
  backends?: StorageBackend[]
}>(), {
  mounts: () => [],
  backends: () => [],
})

const emit = defineEmits<{ 'update:modelValue': [LibraryPathEntry[]] }>()

const entries = computed(() => props.modelValue || [])

/** 后端下拉：以后端下发的为准；后端没给就退回三种固定选项（不至于一个都选不了） */
const backendOptions = computed<StorageBackend[]>(() => (
  props.backends.length
    ? props.backends
    : [
        { value: 'local', label: '本地文件' },
        { value: 'rclone', label: 'Rclone' },
        { value: '115', label: '115 网盘' },
      ]
))

const dialogVisible = ref(false)
/** null = 新建；非 null = 编辑这一条（弹窗直接定位到它当前目录） */
const editingIndex = ref<number | null>(null)

const editingEntry = computed<LibraryPathEntry | null>(
  () => (editingIndex.value == null ? null : entries.value[editingIndex.value] || null),
)

/** 弹窗里的“已存在”比对：编辑时要把**自己**排除，否则在同一个目录上确认会被当成重复而没反应 */
const otherEntries = computed<LibraryPathEntry[]>(() => (
  editingIndex.value == null
    ? entries.value
    : entries.value.filter((_, i) => i !== editingIndex.value)
))

function labelOf(entry: LibraryPathEntry): string {
  return entry.backend_label || entry.backend || '未知来源'
}

/** 本机来源与远程来源的补充说明：远程那条带挂载名，删了挂载的显示成「挂载已删除」 */
function hintOf(entry: LibraryPathEntry): string {
  if (entry.mount_id == null) return ''
  return entry.mount_name ? `挂载：${entry.mount_name}` : '挂载已删除'
}

function openAdd() {
  editingIndex.value = null
  dialogVisible.value = true
}

function openBrowse(index: number) {
  editingIndex.value = index
  dialogVisible.value = true
}

/** 编辑模式下弹窗确认的是“替换”：先把被替换的那条摘掉，新条目插回原位（顺序不变） */
function onConfirm(added: Array<{ path: string; backend: string; mount_id: number | null }>) {
  const next = entries.value.slice()
  let at = next.length
  if (editingIndex.value != null) {
    at = editingIndex.value
    next.splice(at, 1)
  }
  for (const item of added) {
    const mount = item.mount_id == null
      ? null
      : props.mounts.find((m) => m.id === item.mount_id)
    next.splice(at++, 0, {
      path: item.path,
      backend: item.backend,
      backend_label: backendOptions.value.find((b) => b.value === item.backend)?.label || item.backend,
      mount_id: item.mount_id,
      mount_name: mount?.name || '',
      source: item.mount_id == null ? 'local' : 'mount',
      raw: item.mount_id == null
        ? item.path
        : `mount://${item.mount_id}${item.path.startsWith('/') ? item.path : `/${item.path}`}`,
    })
  }
  emit('update:modelValue', next)
}

function removeAt(index: number) {
  const entry = entries.value[index]
  if (!entry) return
  const next = entries.value.slice()
  next.splice(index, 1)
  emit('update:modelValue', next)
  ElMessage.success(`已移除：${entry.path}（保存后生效）`)
}
</script>

<template>
  <div class="lpm">
    <div v-if="!entries.length" class="lpm-empty">
      <EmptyState
        compact
        :icon="FolderOpen"
        title="还没有媒体路径"
        description="点下方「按类型添加路径」，默认就是服务器本地硬盘，选个目录就行。"
      />
    </div>

    <div v-for="(e, i) in entries" :key="`${e.backend}-${e.mount_id ?? 0}-${e.path}-${i}`" class="lpm-row">
      <FolderOpen :size="15" class="lpm-icon" />
      <div class="lpm-main">
        <span class="lpm-path" :title="e.raw">{{ e.path }}</span>
        <div class="lpm-meta">
          <el-tag size="small" :type="e.mount_id == null ? 'info' : 'primary'" effect="plain">
            {{ labelOf(e) }}
          </el-tag>
          <span v-if="hintOf(e)" class="lpm-hint">{{ hintOf(e) }}</span>
        </div>
      </div>
      <button
        type="button"
        class="lpm-op"
        :aria-label="`浏览或更换目录 ${e.path}`"
        :title="`浏览或更换目录 ${e.path}`"
        @click="openBrowse(i)"
      >
        <FolderSearch :size="15" />
      </button>
      <button
        type="button"
        class="lpm-op lpm-op--danger"
        :aria-label="`删除路径 ${e.path}`"
        :title="`删除路径 ${e.path}`"
        @click="removeAt(i)"
      >
        <X :size="15" />
      </button>
    </div>

    <el-button style="margin-top: 10px" @click="openAdd">
      <Plus :size="14" style="margin-right: 4px" />按类型添加路径
    </el-button>
    <p class="lpm-hint-block">
      一行一条路径。点「按类型添加路径」选好类型再浏览目录，默认是服务器本地硬盘；
      115 / Rclone 在弹窗的「高级」里。点文件夹图标可以重新浏览这个目录；保存后需要重新扫描一次才会生效。
    </p>

    <LibraryPathDialog
      v-model="dialogVisible"
      :mounts="mounts"
      :backends="backendOptions"
      :preset="editingEntry"
      :existing="otherEntries"
      @confirm="onConfirm"
    />
  </div>
</template>

<style scoped>
.lpm { width: 100%; }
.lpm-empty {
  border: 1px dashed var(--au-border-strong);
  border-radius: var(--au-r-md);
  background: var(--au-bg-soft);
}
.lpm-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border: 1px solid var(--au-border);
  border-radius: var(--au-r-md);
  margin-bottom: 8px;
  background: var(--au-surface);
  transition: border-color var(--au-fast) var(--au-ease);
}
.lpm-row:hover { border-color: var(--au-border-strong); }
.lpm-icon { flex: none; color: var(--au-text-3); }
.lpm-main { flex: 1; min-width: 0; }
.lpm-path {
  display: block;
  font-size: var(--font-size-sm);
  font-family: var(--font-mono);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.lpm-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 4px;
}
.lpm-hint, .lpm-hint-block {
  font-size: var(--font-size-xs);
  color: var(--au-text-3);
}
.lpm-hint-block { margin: 8px 0 0; line-height: 1.6; }
.lpm-op {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: none;
  border-radius: var(--au-r-sm);
  background: transparent;
  color: var(--au-text-3);
  cursor: pointer;
}
.lpm-op:focus-visible { outline: 2px solid var(--au-border-focus); outline-offset: 1px; }
.lpm-op:hover { background: var(--au-violet-soft); color: var(--au-primary); }
.lpm-op--danger:hover { background: var(--au-danger-soft); color: var(--au-danger); }
@media (max-width: 768px) {
  .lpm-row { padding: 8px 10px; gap: 8px; }
  .lpm-op { width: 34px; height: 34px; }
  .lpm-meta { flex-wrap: wrap; }
}
</style>