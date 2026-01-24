<script setup lang="ts">
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import { FileText, Download, RefreshCw, Search, Play, Pause, Trash2 } from 'lucide-vue-next'
import { ElMessage } from 'element-plus'
import request from '@/utils/request'

// ==================== 类型定义 ====================
interface LogFile {
  name: string
  path: string
  size: string
  modified: string
}

// ==================== 状态 ====================
const logFiles = ref<LogFile[]>([])
const selectedFile = ref<string | null>(null)
const logContent = ref<string[]>([])
const loading = ref(false)

// 实时查看
const isTailing = ref(false)
const tailInterval = ref<number | null>(null)
const currentPosition = ref(0)

// 筛选
const searchKeyword = ref('')

// ==================== 获取日志文件列表 ====================
const fetchLogFiles = async () => {
  loading.value = true
  try {
    const response = await request.get<any>('/system-logs/files') as any
    logFiles.value = response || []
  } catch (error: any) {
    console.error('获取日志文件失败:', error)
    ElMessage.error('获取日志文件失败: ' + (error.message || '未知错误'))
  } finally {
    loading.value = false
  }
}

// ==================== 读取日志内容 ====================
const fetchLogContent = async (fileName: string) => {
  selectedFile.value = fileName
  logContent.value = []
  loading.value = true
  stopTail()

  try {
    const response = await request.get<any>('/system-logs/view', {
      params: { filename: fileName, lines: 500 }
    }) as any
    logContent.value = response.content || []
    currentPosition.value = response.total_lines || logContent.value.length
  } catch (error: any) {
    console.error('读取日志失败:', error)
    ElMessage.error('读取日志失败: ' + (error.response?.data?.detail || error.message || '未知错误'))
  } finally {
    loading.value = false
  }
}

// ==================== 实时 tailf ====================
const startTail = async () => {
  if (!selectedFile.value) return

  isTailing.value = true

  // 定时获取新日志
  tailInterval.value = window.setInterval(async () => {
    try {
      const response = await request.get<any>('/system-logs/tailf', {
        params: { filename: selectedFile.value, position: currentPosition.value }
      }) as any

      if (response.content && response.content.length > 0) {
        logContent.value.push(...response.content)
        currentPosition.value = response.position || currentPosition.value + response.content.length

        // 限制日志行数，避免内存溢出
        if (logContent.value.length > 1000) {
          logContent.value = logContent.value.slice(-1000)
        }

        await nextTick()
        scrollToBottom()
      }
    } catch (error) {
      console.error('Tailf 失败:', error)
    }
  }, 2000)
}

const stopTail = () => {
  isTailing.value = false
  if (tailInterval.value) {
    clearInterval(tailInterval.value)
    tailInterval.value = null
  }
}

const scrollToBottom = () => {
  const container = document.querySelector('.log-content')
  if (container) {
    container.scrollTop = container.scrollHeight
  }
}

// ==================== 日志操作 ====================
const refreshLogs = () => {
  if (selectedFile.value) {
    fetchLogContent(selectedFile.value)
  } else {
    fetchLogFiles()
  }
}

const clearLogs = () => {
  logContent.value = []
  ElMessage.info('日志显示已清空')
}

const downloadLogs = () => {
  if (!selectedFile.value || logContent.value.length === 0) {
    ElMessage.warning('请先选择日志文件')
    return
  }

  const content = logContent.value.join('\n')
  const blob = new Blob([content], { type: 'text/plain' })
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = selectedFile.value || 'logs.txt'
  link.click()
  ElMessage.success('日志下载成功')
}

// ==================== 搜索过滤 ====================
const filteredLogs = () => {
  if (!searchKeyword.value) return logContent.value
  const keyword = searchKeyword.value.toLowerCase()
  return logContent.value.filter(line => line.toLowerCase().includes(keyword))
}

// ==================== 生命周期 ====================
onMounted(() => {
  fetchLogFiles()
})

onUnmounted(() => {
  stopTail()
})
</script>

<template>
  <div class="system-logs">
    <!-- 操作按钮 -->
    <div class="page-actions">
      <button
        v-if="selectedFile"
        :class="['btn', isTailing ? 'btn-danger' : 'btn-secondary']"
        @click="isTailing ? stopTail() : startTail()"
      >
        <Pause v-if="isTailing" :size="16" />
        <Play v-else :size="16" />
        <span>{{ isTailing ? '停止监控' : '实时监控' }}</span>
      </button>
      <button class="btn btn-secondary" @click="refreshLogs">
        <RefreshCw :size="16" />
        <span>刷新</span>
      </button>
      <button class="btn btn-secondary" @click="downloadLogs" :disabled="!selectedFile">
        <Download :size="16" />
        <span>下载</span>
      </button>
    </div>

    <!-- 主内容区 -->
    <div class="logs-container">
      <!-- 文件列表 -->
      <div class="files-panel">
        <div class="panel-header">
          <h3>日志文件</h3>
        </div>
        <div class="files-list">
          <div v-if="loading && !selectedFile" class="loading">加载中...</div>
          <div v-else-if="logFiles.length === 0" class="empty">暂无日志文件</div>
          <div
            v-for="file in logFiles"
            :key="file.name"
            :class="['file-item', { active: selectedFile === file.name }]"
            @click="fetchLogContent(file.name)"
          >
            <FileText :size="16" />
            <div class="file-info">
              <span class="file-name">{{ file.name }}</span>
              <span class="file-meta">{{ file.size }} · {{ file.modified }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 日志内容 -->
      <div class="logs-panel">
        <div v-if="!selectedFile" class="empty-state">
          <FileText :size="48" />
          <p>选择一个日志文件开始查看</p>
        </div>

        <template v-else>
          <!-- 工具栏 -->
          <div class="logs-toolbar">
            <div class="toolbar-left">
              <span class="file-name">{{ selectedFile }}</span>
              <span v-if="isTailing" class="live-indicator">
                <span class="live-dot"></span>
                实时监控中
              </span>
            </div>
            <div class="toolbar-right">
              <div class="search-box">
                <Search :size="14" />
                <input
                  v-model="searchKeyword"
                  type="text"
                  placeholder="搜索日志..."
                  class="search-input"
                />
              </div>
              <button class="icon-btn" @click="clearLogs" title="清空显示">
                <Trash2 :size="16" />
              </button>
            </div>
          </div>

          <!-- 日志内容 -->
          <div class="log-content">
            <div v-if="loading && logContent.length === 0" class="loading">加载中...</div>
            <div v-else-if="filteredLogs().length === 0" class="empty">无匹配日志</div>
            <div v-else>
              <div
                v-for="(line, index) in filteredLogs()"
                :key="index"
                :class="['log-line', getLogLevel(line)]"
              >
                {{ line }}
              </div>
            </div>
          </div>

          <!-- 状态栏 -->
          <div class="logs-footer">
            <span>共 {{ filteredLogs().length }} 行</span>
            <span v-if="searchKeyword" class="filter-info">
              已筛选: {{ searchKeyword }}
            </span>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<script lang="ts">
// 获取日志级别用于着色
function getLogLevel(line: string): string {
  const upper = line.toUpperCase()
  if (upper.includes('ERROR')) return 'log-error'
  if (upper.includes('WARN')) return 'log-warn'
  if (upper.includes('INFO')) return 'log-info'
  if (upper.includes('DEBUG')) return 'log-debug'
  return ''
}
</script>

<style scoped>
.system-logs {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
  height: calc(100vh - 180px);
}

/* 页面头部 */




/* 主容器 */
.logs-container {
  display: flex;
  gap: 1rem;
  flex: 1;
  min-height: 0;
}

/* 文件面板 */
.files-panel {
  width: 280px;
  background: white;
  border-radius: 12px;
  border: 1px solid #e8edf3;
  display: flex;
  flex-direction: column;
}

.panel-header {
  padding: 1rem;
  border-bottom: 1px solid #f1f5f9;
}

.panel-header h3 {
  font-size: 1rem;
  font-weight: 600;
  margin: 0;
}

.files-list {
  flex: 1;
  overflow-y: auto;
  padding: 0.5rem;
}

.file-item {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s ease;
  color: var(--text-secondary);
}

.file-item:hover {
  background: #f8fafc;
}

.file-item.active {
  background: rgba(76, 175, 80, 0.1);
  color: #4CAF50;
}

.file-info {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
}

.file-name {
  font-size: 0.875rem;
  font-weight: 500;
}

.file-meta {
  font-size: 0.75rem;
  color: var(--text-muted);
}

/* 日志面板 */
.logs-panel {
  flex: 1;
  background: white;
  border-radius: 12px;
  border: 1px solid #e8edf3;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.logs-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.75rem 1rem;
  border-bottom: 1px solid #f1f5f9;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.live-indicator {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.25rem 0.5rem;
  background: rgba(76, 175, 80, 0.15);
  color: #4CAF50;
  border-radius: 6px;
  font-size: 0.75rem;
  font-weight: 500;
}

.live-dot {
  width: 8px;
  height: 8px;
  background: #4CAF50;
  border-radius: 50%;
  animation: pulse 1.5s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.5; transform: scale(1.2); }
}

.search-box {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.375rem 0.75rem;
  background: #f8fafc;
  border-radius: 8px;
}

.search-input {
  border: none;
  background: transparent;
  font-size: 0.875rem;
  outline: none;
  width: 150px;
}

/* 日志内容 */
.log-content {
  flex: 1;
  padding: 1rem;
  overflow-y: auto;
  font-family: 'Courier New', monospace;
  font-size: 0.8rem;
  line-height: 1.6;
  background: #1a1a2e;
  color: #e2e8f0;
}

.log-line {
  padding: 0.125rem 0;
  white-space: pre-wrap;
  word-break: break-all;
}

.log-line.log-error {
  color: #ef4444;
}

.log-line.log-warn {
  color: #f59e0b;
}

.log-line.log-info {
  color: #60a5fa;
}

.log-line.log-debug {
  color: #94a3b8;
}

.logs-footer {
  display: flex;
  justify-content: space-between;
  padding: 0.5rem 1rem;
  border-top: 1px solid #f1f5f9;
  font-size: 0.75rem;
  color: var(--text-muted);
}

.filter-info {
  color: #4CAF50;
}

/* 按钮 */
.btn {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.625rem 1rem;
  border-radius: 8px;
  border: none;
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
}

.btn-primary {
  background: var(--gradient-brand);
  color: white;
}

.btn-secondary {
  background: #f1f5f9;
  color: var(--text-secondary);
}

.btn-secondary:hover {
  background: #e2e8f0;
}

.btn-danger {
  background: #ef4444;
  color: white;
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.icon-btn {
  width: 32px;
  height: 32px;
  border: none;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
}

.icon-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

/* 空状态 */
.empty-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--text-muted);
  gap: 1rem;
}

.loading, .empty {
  text-align: center;
  padding: 2rem;
  color: var(--text-muted);
}
</style>
