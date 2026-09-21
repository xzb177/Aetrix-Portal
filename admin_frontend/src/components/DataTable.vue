<script setup lang="ts" generic="T">
/**
 * DataTable —— 桌面表格 / 手机卡片列表，一套标记两种形态
 *
 * 为什么需要它：Element Plus 的表格在 390px 宽的手机上必然要横向拖，操作列还会被
 * 固定在右侧压住中间列的文字（之前「按钮被文字盖住」就是这么来的）。逐页手写两套
 * 标记维护成本高，所以把两种形态收敛到一个组件：
 *
 * - ≥641px：普通 el-table，列的宽窄、固定列与分页行为都不变
 * - ≤640px：每行变一张卡片——`mobile: 'title'` 的列当标题，其余列渲染成「标签 / 值」
 *   两列，`key === 'actions'` 的列渲染到卡片底部作为操作区
 *
 * 页面只需要声明列 + 提供 `#cell-<key>` 插槽（桌面与手机共用同一份渲染逻辑）。
 */
import { computed } from 'vue'
import { useBreakpoint } from '@/composables/useBreakpoint'

export interface DataColumn {
  /** 列标识；`actions` 视为操作列（手机端渲染在卡片底部） */
  key: string
  label: string
  width?: number | string
  minWidth?: number | string
  align?: 'left' | 'center' | 'right'
  fixed?: boolean | 'left' | 'right'
  className?: string
  /** 桌面端表头可点排序（客户端排序；手机卡片不排序） */
  sortable?: boolean
  /** 手机端行为：title（标题行，建议每表一个）· hide（手机上不显示）· 默认显示为键值行 */
  mobile?: 'title' | 'hide'
}

const props = withDefaults(
  defineProps<{
    rows: T[]
    columns: DataColumn[]
    loading?: boolean
    empty?: string
    rowKey?: string
    /** 点整行触发 row-click（手机卡片同样生效） */
    clickable?: boolean
  }>(),
  { loading: false, empty: '暂无数据', rowKey: 'id', clickable: false },
)

const emit = defineEmits<{ 'row-click': [row: T] }>()

// 插槽按列定义：`#cell-<列 key>` 同时用于桌面单元格与手机卡片取值
// （插槽名是动态的，必须显式声明类型，否则页面里解构不到 row）
defineSlots<{
  [name: `cell-${string}`]: (props: { row: T; index: number }) => unknown
  /** 手机卡片底部补充内容（桌面端不渲染，例如展开行里的明细） */
  'card-extra'?: (props: { row: T; index: number }) => unknown
  /** 空状态（桌面表格的 #empty 与手机端共用一套内容） */
  empty?: () => unknown
}>()

const { isPhone } = useBreakpoint()

const titleColumn = computed(
  () => props.columns.find((c) => c.mobile === 'title') ?? props.columns[0],
)

/** 操作列：桌面是表格列，手机是卡片底部按钮区 */
const actionColumns = computed(() => props.columns.filter((c) => c.key === 'actions'))

/** 手机卡片里除标题与操作列之外的键值行 */
const detailColumns = computed(() =>
  props.columns.filter(
    (c) => c !== titleColumn.value && c.mobile !== 'hide' && c.key !== 'actions',
  ),
)

/** 取值兜底：泛型行对象直接用字符串下标会触发 TS 报错，统一走这里 */
function field(row: T, key: string): unknown {
  return (row as Record<string, unknown>)[key]
}

function cellText(row: T, key: string): string {
  const value = field(row, key)
  return value === undefined || value === null ? '' : String(value)
}

function rowId(row: T, index: number): string {
  const value = field(row, props.rowKey)
  return value === undefined || value === null ? String(index) : String(value)
}

function onRowClick(row: T) {
  if (props.clickable) emit('row-click', row)
}
</script>

<template>
  <!-- 桌面 / 平板：普通表格 -->
  <el-table
    v-if="!isPhone"
    v-loading="loading"
    :data="rows"
    :row-key="rowKey"
    :class="{ 'is-clickable': clickable }"
    @row-click="onRowClick"
  >
    <el-table-column
      v-for="col in columns"
      :key="col.key"
      :prop="col.key"
      :label="col.label"
      :width="col.width"
      :min-width="col.minWidth"
      :align="col.align"
      :sortable="col.sortable"
      :fixed="col.fixed"
      :class-name="col.className"
      show-overflow-tooltip
    >
      <template #default="{ row, $index }">
        <slot :name="`cell-${col.key}`" :row="row" :index="$index">
          {{ cellText(row, col.key) }}
        </slot>
      </template>
    </el-table-column>

    <template #empty>
      <slot name="empty">
        <span class="dt-empty-text">{{ empty }}</span>
      </slot>
    </template>
  </el-table>

  <!-- 手机：卡片列表 -->
  <div v-else class="dt-cards">
    <div v-if="loading" class="dt-loading">加载中…</div>

    <template v-else-if="rows.length">
      <article
        v-for="(row, index) in rows"
        :key="rowId(row, index)"
        class="dt-card"
        :class="{ 'is-clickable': clickable }"
        @click="onRowClick(row)"
      >
        <div class="dt-title">
          <slot :name="`cell-${titleColumn.key}`" :row="row" :index="index">
            {{ cellText(row, titleColumn.key) }}
          </slot>
        </div>

        <div v-if="detailColumns.length" class="kv-list dt-fields">
          <div v-for="col in detailColumns" :key="col.key" class="kv-row">
            <span class="kv-key">{{ col.label }}</span>
            <span class="kv-value">
              <slot :name="`cell-${col.key}`" :row="row" :index="index">
                {{ cellText(row, col.key) }}
              </slot>
            </span>
          </div>
        </div>

        <div v-if="$slots['card-extra']" class="dt-extra">
          <slot name="card-extra" :row="row" :index="index" />
        </div>

        <div v-if="actionColumns.length" class="dt-actions">
          <template v-for="col in actionColumns" :key="col.key">
            <slot :name="`cell-${col.key}`" :row="row" :index="index" />
          </template>
        </div>
      </article>
    </template>

    <div v-else class="dt-empty">
      <slot name="empty">{{ empty }}</slot>
    </div>
  </div>
</template>

<style scoped>
.dt-cards {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.dt-empty {
  padding: 32px 12px;
  text-align: center;
  color: var(--text-muted);
  font-size: var(--font-size-sm);
}

.dt-empty-text { color: var(--text-muted); font-size: var(--font-size-sm); }

.dt-loading {
  padding: 28px 0;
  text-align: center;
  color: var(--text-muted);
  font-size: var(--font-size-sm);
}

.dt-card {
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  padding: 13px 14px;
  transition: border-color var(--transition-fast), background var(--transition-fast);
}

.dt-card.is-clickable:active { background: var(--bg-hover); }

.dt-title {
  font-size: var(--font-size-md);
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
  line-height: var(--line-height-normal);
  word-break: break-word;
}

.dt-fields {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid var(--border-subtle);
}

.dt-extra {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid var(--border-subtle);
}

.dt-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--border-subtle);
}

.dt-actions :deep(.el-button) { flex: 1 1 auto; min-width: 84px; margin-left: 0; }

:deep(.el-table.is-clickable .el-table__row) { cursor: pointer; }
</style>
