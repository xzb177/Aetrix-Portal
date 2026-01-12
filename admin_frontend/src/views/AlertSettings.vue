<script setup lang="ts">
import { ref } from 'vue'
import { Bell, Server, HardDrive, Activity, Zap, Plus, Trash2, Save } from 'lucide-vue-next'

interface AlertRule {
  id: number
  name: string
  type: 'server_offline' | 'disk_high' | 'cpu_high' | 'transcode_stuck'
  enabled: boolean
  threshold?: number
  recipients: string[]
}

const rules = ref<AlertRule[]>([
  {
    id: 1,
    name: '服务器离线告警',
    type: 'server_offline',
    enabled: true,
    recipients: ['admin', 'ops'],
  },
  {
    id: 2,
    name: '磁盘空间告警',
    type: 'disk_high',
    enabled: true,
    threshold: 85,
    recipients: ['admin'],
  },
  {
    id: 3,
    name: 'CPU 负载告警',
    type: 'cpu_high',
    enabled: true,
    threshold: 80,
    recipients: ['admin'],
  },
  {
    id: 4,
    name: '转码卡死告警',
    type: 'transcode_stuck',
    enabled: true,
    recipients: ['admin', 'ops'],
  },
])

const testNotification = ref('')

const toggleRule = (id: number) => {
  const rule = rules.value.find(r => r.id === id)
  if (rule) {
    rule.enabled = !rule.enabled
  }
}

const deleteRule = (id: number) => {
  rules.value = rules.value.filter(r => r.id !== id)
}

const sendTest = () => {
  testNotification.value = '正在发送测试通知...'
  setTimeout(() => {
    testNotification.value = '测试通知已发送！'
  }, 1000)
}

const getTypeLabel = (type: string) => {
  const map = {
    server_offline: '服务器离线',
    disk_high: '磁盘空间',
    cpu_high: 'CPU 负载',
    transcode_stuck: '转码卡死',
  }
  return map[type as keyof typeof map] || type
}

const getTypeIcon = (type: string) => {
  return Server
}
</script>

<template>
  <div class="alert-settings-page">
    <!-- 告警规则列表 -->
    <div class="rules-section">
      <h2 class="section-title">告警规则</h2>
      <div class="rules-list">
        <div v-for="rule in rules" :key="rule.id" class="rule-card" :class="{ disabled: !rule.enabled }">
          <div class="rule-header">
            <div class="rule-type" :class="`type-${rule.type}`">
              <component :is="getTypeIcon(rule.type)" :size="20" />
            </div>
            <div class="rule-info">
              <h3 class="rule-name">{{ rule.name }}</h3>
              <span class="rule-type-label">{{ getTypeLabel(rule.type) }}</span>
            </div>
            <label class="rule-toggle">
              <input type="checkbox" :checked="rule.enabled" @change="toggleRule(rule.id)" />
              <span class="toggle-slider"></span>
            </label>
          </div>

          <div class="rule-config">
            <!-- 阈值配置 -->
            <div v-if="rule.threshold !== undefined" class="config-item">
              <span class="config-label">触发阈值</span>
              <div class="config-value">
                <input type="number" :value="rule.threshold" class="threshold-input" />
                <span class="config-unit">%</span>
              </div>
            </div>

            <!-- 通知接收人 -->
            <div class="config-item">
              <span class="config-label">通知接收人</span>
              <div class="recipients">
                <span v-for="recipient in rule.recipients" :key="recipient" class="recipient-badge">
                  {{ recipient }}
                </span>
                <button class="add-recipient">+</button>
              </div>
            </div>
          </div>

          <div class="rule-actions">
            <button class="btn-delete" @click="deleteRule(rule.id)">
              <Trash2 :size="16" />
              删除
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- 全局设置 -->
    <div class="global-settings">
      <h2 class="section-title">全局设置</h2>
      <div class="settings-grid">
        <div class="setting-item">
          <div class="setting-info">
            <h4>告警静默期</h4>
            <p>同一告警的最小发送间隔</p>
          </div>
          <select class="setting-select">
            <option>5 分钟</option>
            <option selected>15 分钟</option>
            <option>30 分钟</option>
            <option>1 小时</option>
          </select>
        </div>

        <div class="setting-item">
          <div class="setting-info">
            <h4>告警恢复通知</h4>
            <p>故障恢复时发送通知</p>
          </div>
          <label class="rule-toggle">
            <input type="checkbox" checked />
            <span class="toggle-slider"></span>
          </label>
        </div>

        <div class="setting-item">
          <div class="setting-info">
            <h4>告警升级</h4>
            <p>未确认告警自动升级</p>
          </div>
          <label class="rule-toggle">
            <input type="checkbox" checked />
            <span class="toggle-slider"></span>
          </label>
        </div>
      </div>
    </div>

    <!-- 测试通知 -->
    <div class="test-section">
      <h2 class="section-title">测试通知</h2>
      <div class="test-content">
        <p class="test-desc">发送一条测试通知，检查配置是否正常</p>
        <button class="btn-secondary" @click="sendTest">
          <Bell :size="18" />
          发送测试通知
        </button>
        <span v-if="testNotification" class="test-result" :class="{ success: testNotification.includes('已发送') }">
          {{ testNotification }}
        </span>
      </div>
    </div>

    <!-- 保存按钮 -->
    <div class="save-section">
      <button class="btn-save">
        <Save :size="18" />
        保存配置
      </button>
    </div>
  </div>
</template>

<style scoped>
.alert-settings-page {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.btn-primary {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.625rem 1.25rem;
  background: #673AB7;
  color: white;
  border: none;
  border-radius: 10px;
  font-size: 0.875rem;
  cursor: pointer;
  white-space: nowrap;
}

.btn-primary:hover {
  background: #552b9f;
}

/* 移动端适配 */
@media (max-width: 768px) {

  .page-title {
    font-size: 1.25rem;
  }

  .btn-primary {
    width: 100%;
    justify-content: center;
  }
}

/* 区域 */
.rules-section,
.global-settings,
.test-section {
  background: white;
  border-radius: 12px;
  padding: 1.5rem;
  border: 1px solid #e8edf3;
}

.section-title {
  font-size: 1.1rem;
  font-weight: 600;
  color: #1a1a2e;
  margin: 0 0 1rem 0;
}

/* 规则卡片 */
.rules-list {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.rule-card {
  padding: 1.25rem;
  background: #f8fafc;
  border-radius: 10px;
  border: 1px solid #e2e8f0;
}

.rule-card.disabled {
  opacity: 0.6;
}

.rule-header {
  display: flex;
  align-items: center;
  gap: 1rem;
  margin-bottom: 1rem;
}

.rule-type {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
}

.type-server_offline { background: linear-gradient(135deg, #F44336, #D32F2F); }
.type-disk_high { background: linear-gradient(135deg, #FF9800, #F57C00); }
.type-cpu_high { background: linear-gradient(135deg, #673AB7, #7B1FA2); }
.type-transcode_stuck { background: linear-gradient(135deg, #2196F3, #1976D2); }

.rule-info {
  flex: 1;
}

.rule-name {
  font-size: 0.95rem;
  font-weight: 600;
  color: #1a1a2e;
  margin: 0;
}

.rule-type-label {
  font-size: 0.75rem;
  color: #94a3b8;
}

/* Toggle */
.rule-toggle {
  position: relative;
  width: 48px;
  height: 26px;
}

.rule-toggle input {
  opacity: 0;
  width: 0;
  height: 0;
}

.toggle-slider {
  position: absolute;
  cursor: pointer;
  inset: 0;
  background: #cbd5e1;
  border-radius: 26px;
  transition: 0.3s;
}

.toggle-slider::before {
  position: absolute;
  content: '';
  height: 20px;
  width: 20px;
  left: 3px;
  bottom: 3px;
  background: white;
  border-radius: 50%;
  transition: 0.3s;
}

input:checked + .toggle-slider {
  background: #4CAF50;
}

input:checked + .toggle-slider::before {
  transform: translateX(22px);
}

/* 规则配置 */
.rule-config {
  display: flex;
  gap: 2rem;
  margin-bottom: 1rem;
  flex-wrap: wrap;
}

@media (max-width: 640px) {
  .rule-config {
    flex-direction: column;
    gap: 1rem;
  }
}

.config-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.config-label {
  font-size: 0.8rem;
  color: #64748b;
}

.config-value {
  display: flex;
  align-items: center;
  gap: 0.25rem;
}

.threshold-input {
  width: 60px;
  padding: 0.25rem 0.5rem;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  text-align: center;
}

.config-unit {
  font-size: 0.8rem;
  color: #94a3b8;
}

.recipients {
  display: flex;
  gap: 0.5rem;
}

.recipient-badge {
  padding: 0.125rem 0.5rem;
  background: rgba(103, 58, 183, 0.15);
  color: #673AB7;
  border-radius: 4px;
  font-size: 0.75rem;
}

.add-recipient {
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px dashed #cbd5e1;
  border-radius: 4px;
  background: transparent;
  color: #94a3b8;
  cursor: pointer;
}

.rule-actions {
  display: flex;
  gap: 0.5rem;
}

.btn-delete {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.375rem 0.75rem;
  background: transparent;
  border: 1px solid #ef4444;
  color: #ef4444;
  border-radius: 6px;
  font-size: 0.8rem;
  cursor: pointer;
}

.btn-delete:hover {
  background: rgba(239, 68, 68, 0.1);
}

/* 全局设置 */
.settings-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1.5rem;
}

@media (max-width: 1024px) {
  .settings-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 640px) {
  .settings-grid {
    grid-template-columns: 1fr;
  }
}

.setting-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1rem;
  background: #f8fafc;
  border-radius: 8px;
}

.setting-info h4 {
  font-size: 0.9rem;
  font-weight: 500;
  color: #1a1a2e;
  margin: 0 0 0.25rem 0;
}

.setting-info p {
  font-size: 0.75rem;
  color: #94a3b8;
  margin: 0;
}

.setting-select {
  padding: 0.375rem 0.75rem;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  font-size: 0.8rem;
  color: #475569;
  background: white;
}

/* 测试区域 */
.test-content {
  display: flex;
  align-items: center;
  gap: 1rem;
  flex-wrap: wrap;
}

@media (max-width: 640px) {
  .test-content {
    flex-direction: column;
    align-items: flex-start;
  }

  .btn-secondary {
    width: 100%;
    justify-content: center;
  }
}

.test-desc {
  font-size: 0.875rem;
  color: #64748b;
}

.btn-secondary {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 1rem;
  background: white;
  border: 1px solid #e2e8f0;
  color: #475569;
  border-radius: 8px;
  font-size: 0.875rem;
  cursor: pointer;
}

.btn-secondary:hover {
  border-color: #673AB7;
  color: #673AB7;
}

.test-result {
  font-size: 0.875rem;
  color: #64748b;
}

.test-result.success {
  color: #4CAF50;
}

/* 保存 */
.save-section {
  display: flex;
  justify-content: center;
}

.btn-save {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem 2rem;
  background: #4CAF50;
  color: white;
  border: none;
  border-radius: 10px;
  font-size: 0.9rem;
  font-weight: 500;
  cursor: pointer;
}

.btn-save:hover {
  background: #43A047;
}
</style>
