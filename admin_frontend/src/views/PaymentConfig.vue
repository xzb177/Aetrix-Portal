<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { CreditCard, Save, CheckCircle2, AlertCircle } from 'lucide-vue-next'
import request from '@/utils/request'

interface PaymentConfig {
  is_configured: boolean
  gateway_url: string
  partner_id: string
  key: string
  notify_url: string
  return_url: string
}

const config = ref<PaymentConfig>({
  is_configured: false,
  gateway_url: '',
  partner_id: '',
  key: '',
  notify_url: '',
  return_url: ''
})

const saving = ref(false)
const testResult = ref<{ success: boolean; message: string } | null>(null)

const form = ref({
  gateway_url: '',
  partner_id: '',
  key: ''
})

const loadConfig = async () => {
  try {
    const res = await request.get<any>('/payment/config') as any
    config.value = res as PaymentConfig
    form.value = {
      gateway_url: res.gateway_url || '',
      partner_id: res.partner_id || '',
      key: ''  // 不回填密钥
    }
  } catch (err) {
    console.error('加载配置失败:', err)
  }
}

const saveConfig = async () => {
  if (!form.value.gateway_url || !form.value.partner_id || !form.value.key) {
    testResult.value = { success: false, message: '请填写必填项' }
    return
  }

  saving.value = true
  try {
    await request.post('/payment/config', form.value)
    testResult.value = { success: true, message: '配置保存成功！' }
    await loadConfig()
  } catch (err: any) {
    testResult.value = { success: false, message: err.message || '保存失败' }
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  loadConfig()
})
</script>

<template>
  <div class="payment-config-page">
    <!-- 配置状态 -->
    <div v-if="config.is_configured" class="status-banner status-success">
      <CheckCircle2 :size="18" />
      <span>支付已配置</span>
    </div>
    <div v-else class="status-banner status-warning">
      <AlertCircle :size="18" />
      <span>支付未配置</span>
    </div>

    <!-- 测试结果 -->
    <div v-if="testResult" class="test-result" :class="{ success: testResult.success, error: !testResult.success }">
      <CheckCircle2 v-if="testResult.success" :size="16" />
      <AlertCircle v-else :size="16" />
      <span>{{ testResult.message }}</span>
    </div>

    <!-- 配置表单 -->
    <div class="config-card">
      <h2 class="config-title">易支付配置</h2>

      <div class="form-group">
        <label class="form-label">支付网关地址 *</label>
        <input
          v-model="form.gateway_url"
          type="url"
          class="form-input"
          placeholder="https://pay.example.com/submit.php"
        />
      </div>

      <div class="form-group">
        <label class="form-label">商户ID *</label>
        <input
          v-model="form.partner_id"
          type="text"
          class="form-input"
          placeholder="1000"
        />
      </div>

      <div class="form-group">
        <label class="form-label">商户密钥 *</label>
        <input
          v-model="form.key"
          type="password"
          class="form-input"
          placeholder="请输入商户密钥"
        />
        <div class="field-hint">
          <p><strong>密钥类型说明：</strong></p>
          <ul>
            <li><strong>易支付 MD5 签名密钥</strong> - 用于签名验证的字符串密钥</li>
            <li>从易支付商户后台获取，通常位于「商户信息」或「API设置」中</li>
            <li><strong>不是</strong> RSA 私钥/公钥对，而是纯文本密钥字符串</li>
            <li>通常为 16-32 位随机字符，如：<code>a1b2c3d4e5f6g7h8</code></li>
          </ul>
        </div>
      </div>

      <button
        class="save-btn"
        :class="{ loading: saving }"
        :disabled="saving"
        @click="saveConfig"
      >
        <Save :size="16" />
        {{ saving ? '保存中...' : '保存配置' }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.payment-config-page {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

/* 状态横幅 */
.status-banner {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem 1rem;
  border-radius: 8px;
  font-size: 0.875rem;
}

.status-success {
  background: rgba(76, 175, 80, 0.1);
  color: #4CAF50;
  border: 1px solid rgba(76, 175, 80, 0.2);
}

.status-warning {
  background: rgba(255, 152, 0, 0.1);
  color: #FF9800;
  border: 1px solid rgba(255, 152, 0, 0.2);
}

/* 测试结果 */
.test-result {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem 1rem;
  border-radius: 8px;
  font-size: 0.875rem;
}

.test-result.success {
  background: rgba(76, 175, 80, 0.1);
  color: #4CAF50;
}

.test-result.error {
  background: rgba(244, 67, 54, 0.1);
  color: #F44336;
}

/* 配置卡片 */
.config-card {
  background: var(--bg-card, white);
  border-radius: 12px;
  padding: 1.5rem;
  border: 1px solid var(--border-subtle, #e8edf3);
}

.config-title {
  font-size: 1rem;
  font-weight: 600;
  color: #1a1f35;
  margin: 0 0 1rem 0;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  margin-bottom: 1rem;
}

.form-label {
  font-size: 0.875rem;
  font-weight: 500;
  color: var(--text-secondary, #475569);
}

.form-input {
  padding: 0.625rem 0.875rem;
  border: 1px solid var(--border-subtle, #e2e8f0);
  border-radius: 8px;
  font-size: 0.875rem;
  color: #1a1f35;
  transition: border-color 0.2s;
}

.form-input::placeholder {
  color: #94a3b8;
}

.form-input:focus {
  outline: none;
  border-color: var(--primary, #673AB7);
}

/* 字段提示 */
.field-hint {
  margin-top: 0.5rem;
  padding: 0.75rem;
  background: rgba(103, 58, 183, 0.05);
  border-left: 3px solid var(--primary, #673AB7);
  border-radius: 4px;
  font-size: 0.75rem;
  color: var(--text-secondary, #475569);
}

.field-hint p {
  margin: 0 0 0.5rem 0;
}

.field-hint ul {
  margin: 0;
  padding-left: 1.25rem;
}

.field-hint li {
  margin-bottom: 0.25rem;
}

.field-hint code {
  padding: 2px 6px;
  background: rgba(0, 0, 0, 0.05);
  border-radius: 3px;
  font-family: 'SF Mono', 'Monaco', 'Inconsolata', 'Fira Code', monospace;
  font-size: 0.7rem;
}

.save-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  padding: 0.625rem 1.5rem;
  background: var(--primary, #673AB7);
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.2s;
}

.save-btn:hover:not(:disabled) {
  background: var(--primary-hover, #552b9f);
}

.save-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.save-btn.loading svg {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 移动端适配 */
@media (max-width: 640px) {
  .config-card {
    padding: 1rem;
  }
}
</style>
